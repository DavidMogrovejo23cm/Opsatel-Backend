"""
Fachada retrocompatible de sync_db.py para OPSATEL.
Re-exporta y ejecuta desde scripts/sync_db.py.
"""
from scripts.sync_db import *

if __name__ == "__main__":
    sync_schema()
