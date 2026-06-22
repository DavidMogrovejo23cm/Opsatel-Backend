import os
import sys
import time
import urllib.parse
import pymysql
from pymysql.err import OperationalError

def get_clean_env(name, default=""):
    val = os.getenv(name, default)
    if val is not None:
        val = str(val).strip().replace("\r", "")
    return val

DB_HOST = get_clean_env("DB_HOST", "db")
DB_PORT_str = get_clean_env("DB_PORT", "3306")
DB_PORT = int(DB_PORT_str) if DB_PORT_str.isdigit() else 3306
DB_USER = get_clean_env("MYSQL_USER", "root")
DB_PASSWORD = get_clean_env("MYSQL_ROOT_PASSWORD", "")
DB_NAME = get_clean_env("MYSQL_DATABASE", "opsatel")
DATABASE_URL = get_clean_env("DATABASE_URL", "")

if DATABASE_URL:
    parsed = urllib.parse.urlparse(DATABASE_URL)
    if parsed.scheme.startswith("mysql"):
        if parsed.hostname:
            DB_HOST = parsed.hostname
        if parsed.port:
            DB_PORT = parsed.port
        if parsed.username:
            DB_USER = parsed.username
        if parsed.password:
            DB_PASSWORD = parsed.password
        if parsed.path:
            DB_NAME = parsed.path.lstrip("/")

MAX_ATTEMPTS_str = get_clean_env("DB_WAIT_ATTEMPTS", "30")
MAX_ATTEMPTS = int(MAX_ATTEMPTS_str) if MAX_ATTEMPTS_str.isdigit() else 30
DELAY_str = get_clean_env("DB_WAIT_DELAY", "2")
DELAY = int(DELAY_str) if DELAY_str.isdigit() else 2

masked_password = "***" if DB_PASSWORD else "NO PASSWORD"
print(f"Esperando a MySQL en {DB_HOST}:{DB_PORT} (Usuario: {DB_USER}, DB: {DB_NAME}, Password: {masked_password})...")

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
