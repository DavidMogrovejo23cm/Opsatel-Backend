import sys
import logging
# pyrefly: ignore [missing-import]
from netmiko import ConnectHandler

logging.basicConfig(filename='scratch/netmiko.log', level=logging.DEBUG)

config = {
    'device_type': 'huawei_olt',
    'host': '172.25.0.2',
    'username': 'root',
    'password': 'admin',
    'port': 22,
    'global_delay_factor': 2,
}

print("Trying connection with huawei_olt...")
try:
    conn = ConnectHandler(**config)
    print("Success with huawei_olt!")
    print("Prompt:", conn.find_prompt())
    conn.disconnect()
except Exception as e:
    print("Failed with huawei_olt:", e)

config['device_type'] = 'huawei'
print("Trying connection with huawei...")
try:
    conn = ConnectHandler(**config)
    print("Success with huawei!")
    print("Prompt:", conn.find_prompt())
    conn.disconnect()
except Exception as e:
    print("Failed with huawei:", e)
