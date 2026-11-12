"""
Fachada retrocompatible de init_db.py para OPSATEL.
Re-exporta y ejecuta desde scripts/init_db.py.
"""
from scripts.init_db import *

if __name__ == "__main__":
    init_db()
