import unittest
from unittest.mock import MagicMock, patch
from services.task_processor import TaskProcessor
from services.olt_interface import OLTInterface, OLTConnectionError
import models


class TaskProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = TaskProcessor()
        # Mock database session
        self.processor.db = MagicMock()

    def test_get_olt_connection_caches_failure(self):
        """
        If connection to an OLT fails, its ID should be added to failed_olts_this_run,
        and subsequent calls to get_olt_connection for that OLT in the same run
        should immediately return None without attempting to connect again.
        """
        olt_config = models.OLTConfig(
            id=1,
            nombre="OLT-Test",
            host="192.168.1.100",
            port=22,
            username="admin",
            password="wrongpassword",
            connection_timeout=5,
            max_retries=1,
            retry_backoff_base=1,
            active=True
        )
        self.processor.db.query().filter().first.return_value = olt_config

        # Mock OLTInterface.connect to raise a connection error
        with patch('services.task_processor.OLTInterface.connect', side_effect=OLTConnectionError("Connection failed")) as mock_connect:
            # First attempt
            conn1 = self.processor.get_olt_connection(olt_id=1)
            self.assertIsNone(conn1)
            self.assertEqual(mock_connect.call_count, 1)
            self.assertIn(1, self.processor.failed_olts_this_run)

            # Second attempt in the same run should be skipped
            conn2 = self.processor.get_olt_connection(olt_id=1)
            self.assertIsNone(conn2)
            # mock_connect call count should still be 1 (skipped second attempt)
            self.assertEqual(mock_connect.call_count, 1)

    def test_process_pending_tasks_clears_failed_olts_cache(self):
        """
        failed_olts_this_run cache should be cleared at the start of a new process_pending_tasks loop cycle.
        """
        self.processor.failed_olts_this_run.add(1)
        self.processor.failed_olts_this_run.add(2)

        # Mock database return for pending tasks (return empty list to exit early)
        self.processor.db.query().filter().order_by().limit().all.return_value = []

        self.processor.process_pending_tasks()

        # Cache should be cleared
        self.assertEqual(len(self.processor.failed_olts_this_run), 0)

    def test_get_olt_connection_reuses_cached_connection(self):
        """
        get_olt_connection should reuse active connections stored in olt_connections cache.
        """
        mock_conn = MagicMock(spec=OLTInterface)
        mock_conn.is_connected = True
        self.processor.olt_connections[5] = mock_conn

        # Mock _check_olt_alive to return True
        with patch.object(self.processor, '_check_olt_alive', return_value=True) as mock_alive:
            conn = self.processor.get_olt_connection(olt_id=5)

            self.assertEqual(conn, mock_conn)
            mock_alive.assert_called_once_with(mock_conn)

    def test_process_task_add_ont_autoscales(self):
        """
        When processing an 'add_ont' task, the TaskProcessor must:
        1. Query the OLT to find used ONT IDs.
        2. Find the first free ONT ID not used on the OLT or in pending tasks.
        3. Find the first free service port not used in the DB or in pending tasks.
        4. Inject both values into the payload and call execute_activation_sequence.
        """
        import json

        task = models.OLTTask(
            id=123,
            cliente_id=456,
            olt_id=1,
            action="add_ont",
            payload=json.dumps({
                "gpon_port": "0/0/15",
                "mac": "485754432B3A9079",
                "description": "Test Client"
            }),
            status="pending"
        )

        # --- Mock OLT interface ---
        mock_olt = MagicMock()
        mock_olt.is_connected = True
        # ONT IDs 0, 1, 2 already exist on the OLT — so the next free one is 3
        mock_olt.get_existing_ont_ids.return_value = [0, 1, 2]
        # Service ports 1000 and 1001 are busy; 1002 is free
        mock_olt.is_service_port_free.side_effect = lambda sp: sp not in (1000, 1001)
        mock_olt.execute_activation_sequence.return_value = {
            "success": True,
            "status": "SUCCESS",
            "ont_id": "3",
            "service_port": "1002",
            "mac": "485754432B3A9079",
            "port_num": "15",
            "cmd_ont": "ont add 15 3 sn-auth...",
            "cmd_servicio": "service-port 1002 vlan...",
            "cmd_breach": "ont port native-vlan 15 3 eth 1..."
        }

        self.processor.get_olt_connection = MagicMock(return_value=mock_olt)

        # --- Mock DB queries by call order ---
        # Call 1: db.query(models.OLTTask).filter(...).first()  → fetch task
        mock_task_by_id = MagicMock()
        mock_task_by_id.filter.return_value.first.return_value = task

        # Call 2: db.query(models.OLTTask).filter(...).all()   → pending tasks (none)
        mock_pending_tasks = MagicMock()
        mock_pending_tasks.filter.return_value.all.return_value = []

        # Call 3: db.query(models.Cliente.service_port).all()  → existing SPs in DB
        mock_sp_query = MagicMock()
        mock_sp_query.all.return_value = [("1000",), ("1001",)]

        # Call 4: db.query(models.Cliente).filter(...).first() → fetch client to update
        mock_client = MagicMock()
        mock_client_query = MagicMock()
        mock_client_query.filter.return_value.first.return_value = mock_client

        # Fall-through for any other queries (OLTTaskLog inserts, etc.)
        mock_misc = MagicMock()

        _call_n = [0]

        def ordered_mock_query(*args):
            _call_n[0] += 1
            n = _call_n[0]
            if n == 1:
                return mock_task_by_id      # 1st: fetch the task by its ID
            elif n == 2:
                return mock_pending_tasks   # 2nd: check concurrent pending tasks
            elif n == 3:
                return mock_sp_query        # 3rd: get all service_ports from Cliente
            elif n == 4:
                return mock_client_query    # 4th: fetch the client record to update
            else:
                return mock_misc

        self.processor.db.query.side_effect = ordered_mock_query

        # --- Run the processor ---
        self.processor.process_task(task.id)

        # The autoscale block should have injected ont_id=3 (first free after 0,1,2)
        # and service_port=1002 (first free after 1000,1001)
        updated_payload = json.loads(task.payload)
        self.assertEqual(updated_payload['ont_id'], '3')
        self.assertEqual(updated_payload['service_port'], '1002')

        # execute_activation_sequence must have been called with the updated payload
        mock_olt.execute_activation_sequence.assert_called_once_with(updated_payload)

        # Client OLT fields must be updated
        self.assertEqual(mock_client.id_port, '3')
        self.assertEqual(mock_client.service_port, '1002')


if __name__ == '__main__':
    unittest.main()
