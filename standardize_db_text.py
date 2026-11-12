"""
Fachada retrocompatible de standardize_db_text.py para OPSATEL.
Re-exporta y ejecuta desde scripts/standardize_db_text.py.
"""
from scripts.standardize_db_text import *

if __name__ == "__main__":
    standardize_texts()
