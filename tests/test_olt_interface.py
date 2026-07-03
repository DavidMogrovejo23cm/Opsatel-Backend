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
        self.assertIn('ont add 0/0/3 5 sn-auth', commands[1])
        self.assertIn('ont port native-vlan 0/0/3 5 eth 1 vlan 200 priority 0', commands[2])
        self.assertIn('service-port 100 vlan 200 gpon 0/0/3 ont 5 gemport 100 multi-service user-vlan 200 tag-transform translate', commands[3])


if __name__ == '__main__':
    unittest.main()
