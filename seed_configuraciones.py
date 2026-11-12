"""
Fachada retrocompatible de seed_configuraciones.py para OPSATEL.
Re-exporta y ejecuta desde scripts/seed_configuraciones.py.
"""
from scripts.seed_configuraciones import *

if __name__ == "__main__":
    seed_configuraciones()
