"""
Fachada retrocompatible de force_fix.py para OPSATEL.
Re-exporta y ejecuta desde scripts/force_fix.py.
"""
from scripts.force_fix import *

if __name__ == "__main__":
    force_fix_columns()
