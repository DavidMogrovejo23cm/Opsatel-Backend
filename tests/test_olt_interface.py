import unittest

from services.olt_interface import OLTInterface


class OLTInterfaceTests(unittest.TestCase):
    def test_extract_gpon_interface(self):
        olt = OLTInterface(host='172.25.0.2', username='root', password='admin')

        self.assertEqual(olt._get_gpon_interface('0/0/3'), '0/0')
        self.assertEqual(olt._get_gpon_interface('0/1/8'), '0/1')
        self.assertEqual(olt._get_gpon_interface('0/0'), '0/0')

    def test_build_connect_config_uses_ssh(self):
        olt = OLTInterface(host='172.25.0.2', username='root', password='admin', port=22)
        config = olt._build_connect_config()

        self.assertEqual(config['device_type'], 'huawei')
        self.assertEqual(config['host'], '172.25.0.2')
        self.assertEqual(config['port'], 22)
        self.assertEqual(config['username'], 'root')
        self.assertEqual(config['password'], 'admin')

    def test_build_activation_commands(self):
        olt = OLTInterface(host='172.25.0.2', username='root', password='admin')
        payload = {
            'mac': 'AABBCCDDEEFF',
            'gpon_port': '0/0/3',
            'ont_id': '5',
            'description': 'Test Cliente',
            'profile_id': '100',
            'srvprofile_id': '100',
            'service_port': '100',
            'vlan': '200',
            'user_vlan': '200',
        }

        commands = olt.build_activation_commands(payload)

        self.assertEqual(commands[0], 'interface gpon 0/0')
        self.assertIn('ont add 3 5 sn-auth', commands[1])
        self.assertIn('ont port native-vlan 3 5 eth 1 vlan 200 priority 0', commands[2])
        self.assertEqual(commands[3], 'quit')
        self.assertIn('service-port 100 vlan 200 gpon 0/0/3 ont 5 gemport 100 multi-service user-vlan 200 tag-transform translate', commands[4])


    def test_parse_autofind_output(self):
        olt = OLTInterface(host='172.25.0.2', username='root', password='admin')

        # Simular salida de display ont autofind all
        sample_output = """
  -----------------------------------------------------------------------------
  Failure No.  GPON   ONT        Equipment    GPON                 GPON
               port   ID         ID           SN                   Password
  -----------------------------------------------------------------------------
            1  0/2/0  1          HG8245H      48575443E8224E93     -
            2  0/16/1 5          -            HWTC12345678         -
            3  0/0/3  12         -            AA:BB:CC:DD:EE:FF    -
            4  0/1/4  0          -            aabbccddeeff         -
  -----------------------------------------------------------------------------
        """
        candidates = olt.parse_autofind_output(sample_output)
        
        self.assertEqual(len(candidates), 4)
        
        # Candidato 1: Slot 2, GPON SN de 16 hex
        self.assertEqual(candidates[0]['gpon_port'], '0/2/0')
        self.assertEqual(candidates[0]['ont_id'], '1')
        self.assertEqual(candidates[0]['mac'], '48575443E8224E93')
        
        # Candidato 2: Slot 16, GPON SN con vendor prefix
        self.assertEqual(candidates[1]['gpon_port'], '0/16/1')
        self.assertEqual(candidates[1]['ont_id'], '5')
        self.assertEqual(candidates[1]['mac'], 'HWTC12345678')
        
        # Candidato 3: Slot 0, MAC con separadores
        self.assertEqual(candidates[2]['gpon_port'], '0/0/3')
        self.assertEqual(candidates[2]['ont_id'], '12')
        self.assertEqual(candidates[2]['mac'], 'AA:BB:CC:DD:EE:FF')
        
        # Candidato 4: Slot 1, MAC sin separadores (normalizada)
        self.assertEqual(candidates[3]['gpon_port'], '0/1/4')
        self.assertEqual(candidates[3]['ont_id'], '0')
        self.assertEqual(candidates[3]['mac'], 'AA:BB:CC:DD:EE:FF')


if __name__ == '__main__':
    unittest.main()
