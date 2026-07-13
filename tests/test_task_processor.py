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

if __name__ == '__main__':
    unittest.main()
