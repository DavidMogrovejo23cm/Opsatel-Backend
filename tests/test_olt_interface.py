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

        self.assertEqual(config['device_type'], 'huawei_olt')
        self.assertEqual(config['host'], '172.25.0.2')
        self.assertEqual(config['port'], 22)
        self.assertEqual(config['username'], 'root')
        self.assertEqual(config['password'], 'admin')

    def test_build_activation_commands(self):
        """
        build_activation_commands returns a dict with:
          - gpon_commands: list of commands to run inside (config-if-gpon-X/X)#
          - config_commands: list of commands to run inside (config)#
          - metadata: dict with all computed provisioning values
        """
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

        result = olt.build_activation_commands(payload)

        # Verify the return type is a dict with the expected structure
        self.assertIsInstance(result, dict)
        self.assertIn('gpon_commands', result)
        self.assertIn('config_commands', result)
        self.assertIn('metadata', result)

        gpon_cmds = result['gpon_commands']
        config_cmds = result['config_commands']
        metadata = result['metadata']

        # gpon_commands: ont add + ont port native-vlan
        self.assertEqual(len(gpon_cmds), 2)
        self.assertIn('ont add 3 5 sn-auth', gpon_cmds[0])
        self.assertIn('ont port native-vlan 3 5 eth 1 vlan 200 priority 0', gpon_cmds[1])

        # config_commands: service-port
        self.assertEqual(len(config_cmds), 1)
        self.assertIn('service-port 100 vlan 200 gpon 0/0/3 ont 5', config_cmds[0])

        # metadata fields
        self.assertEqual(metadata['gpon_port'], '0/0/3')
        self.assertEqual(metadata['ont_id'], '5')
        self.assertEqual(metadata['mac'], 'AABBCCDDEEFF')
        self.assertEqual(metadata['service_port'], '100')
        self.assertEqual(metadata['vlan'], '200')
        self.assertEqual(metadata['user_vlan'], '200')

    def test_parse_autofind_output(self):
        """
        parse_autofind_output parses Huawei multi-line block format separated by dashes.
        """
        olt = OLTInterface(host='172.25.0.2', username='root', password='admin')

        # Simulated real Huawei OLT output (multi-line block format)
        sample_output = """
 -------------------------------------------------------
 Number              : 1
 F/S/L               : 0/2/0
 Ont SN              : 48575443E8224E93 (HWTCE8224E93)
 Password            : 0x00000000000000000000(          )
 Loid                :
 Checkcode           :
 VendorID            : HWTC
 Ont Version         : 255B.B
 Ont SoftwareVersion : V5.B.1.5
 Ont EquipmentID     : HG8245H
 Ont Customized Info :
 Ont autofind time   : 06/07/2026 10:15:08-05:00
 -------------------------------------------------------
 Number              : 2
 F/S/L               : 0/16/1
 Ont SN              : HWTC12345678
 Password            : 0x00000000000000000000(          )
 Loid                :
 Checkcode           :
 VendorID            : HWTC
 Ont Version         : 255B.B
 Ont SoftwareVersion : V5.B.1.5
 Ont EquipmentID     :
 Ont Customized Info :
 Ont autofind time   : 06/07/2026 10:16:00-05:00
 -------------------------------------------------------
        """
        candidates = olt.parse_autofind_output(sample_output)

        self.assertEqual(len(candidates), 2)

        # Candidate 1: Slot 2
        self.assertEqual(candidates[0]['gpon_port'], '0/2/0')
        self.assertEqual(candidates[0]['ont_id'], '1')
        self.assertIsNotNone(candidates[0]['mac'])  # sn_raw should be set

        # Candidate 2: Slot 16
        self.assertEqual(candidates[1]['gpon_port'], '0/16/1')
        self.assertEqual(candidates[1]['ont_id'], '2')
        self.assertIsNotNone(candidates[1]['mac'])


if __name__ == '__main__':
    unittest.main()
