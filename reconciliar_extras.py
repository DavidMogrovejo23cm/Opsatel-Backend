"""
Fachada retrocompatible de reconciliar_extras.py para OPSATEL.
Re-exporta y ejecuta desde scripts/reconciliar_extras.py.
"""
from scripts.reconciliar_extras import *

if __name__ == "__main__":
    reconciliar_extras_con_planes()
