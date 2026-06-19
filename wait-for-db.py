import os
import sys
import time
import pymysql
from pymysql.err import OperationalError

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DATABASE", "opsatel")
MAX_ATTEMPTS = int(os.getenv("DB_WAIT_ATTEMPTS", "30"))
DELAY = int(os.getenv("DB_WAIT_DELAY", "2"))

print(f"Esperando a MySQL en {DB_HOST}:{DB_PORT}...")

attempts = 0
while attempts < MAX_ATTEMPTS:
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            connect_timeout=5,
        )
        conn.close()
        print("MySQL está listo para conexiones.")
        break
    except OperationalError as e:
        attempts += 1
        print(f"MySQL no listo ({attempts}/{MAX_ATTEMPTS}): {e}")
        time.sleep(DELAY)
else:
    print("No se pudo conectar a MySQL después de varios intentos.")
    sys.exit(1)

print("Iniciando backend...")
os.execvp("uvicorn", ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"])
