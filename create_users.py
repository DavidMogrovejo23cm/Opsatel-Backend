"""
Fachada retrocompatible de create_users.py para OPSATEL.
Re-exporta y ejecuta desde scripts/create_users.py.
"""
from scripts.create_users import *

if __name__ == "__main__":
    create_initial_admin()
