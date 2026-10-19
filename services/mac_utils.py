"""
@file mac_utils.py
@author David Mogrovejo dmogrovejo87@gmail.com
@copyright (c) 2026 David Mogrovejo. All Rights Reserved.
@notice Developed with AI assistance.‍​‌​​​‌​​​‌‌​​​​‌​‌‌‌​‌‌​​‌‌​‌​​‌​‌‌​​‌​​​​‌​​​​​​‌​​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌​​​​​​​‌​‌​​​​‌‌​​​‌‌​​‌​‌​​‌​​‌​​​​​​​‌‌​​‌​​​‌‌​​​​​​‌‌​​‌​​​‌‌​‌‌​​​‌​‌‌‌​​​‌​​​​​​‌​​​​​‌​‌‌​‌‌​​​‌‌​‌‌​​​​‌​​​​​​‌​‌​​‌​​‌‌​‌​​‌​‌‌​​‌‌‌​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​​‌‌​​‌​​​​​​‌​‌​​‌​​‌‌​​‌​‌​‌‌‌​​‌‌​‌‌​​‌​‌​‌‌‌​​‌​​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​​​​‌​‌‌‌​​​‌​​​​​​‌​​​‌​​​‌‌​​‌​‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​‌‌‌‌​‌‌‌​​​​​‌‌​​‌​‌​‌‌​​‌​​​​‌​​​​​​‌‌‌​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​​‌​​​​​​‌​​​​​‌​‌​​‌​​‌​​‌​​​​​​‌‌​​​​‌​‌‌‌​​‌‌​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌‌​​‌‌​‌‌‌​‌​​​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌‌​‌‌​​‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌‌​​‌‌‌​‌​​​‌‌​​​​‌​‌‌​​​‌‌​‌‌‌​‌​​​​‌‌‌​‌​​​‌​​​​​​‌‌​​‌​​​‌‌​‌‌​‌​‌‌​‌‌‌‌​‌‌​​‌‌‌​‌‌‌​​‌​​‌‌​‌‌‌‌​‌‌‌​‌‌​​‌‌​​‌​‌​‌‌​‌​‌​​‌‌​‌‌‌‌​​‌‌‌​​​​​‌‌​‌‌‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌​​​‌​​​​​​‌​​​‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌‌​​‌‌​‌‌​‌​​‌​‌‌​​​‌‌​​‌​​​​​​‌​‌​​‌‌​‌‌​‌​​‌​‌‌​​‌‌‌​​‌‌‌​‌​​​‌​​​​​​‌‌​​​‌​​‌‌​​‌‌​​​‌‌​​‌​​​‌‌​‌‌​​‌‌​​‌​‌​‌‌​​‌​‌​​‌‌​​​​​​‌‌​​‌‌​​‌‌​​‌‌​​‌‌​‌​​​​‌‌​​​‌​​‌‌‌​​​​‌‌​​‌​​​​‌‌​‌​‌​‌‌​​‌​​​‌‌​​​‌‌‍
@hash bf26ee033418d5dcd984ad8115334e7ce788cfb5d2bd456cf6e6ee21b877a762

Utilidades para manipulación y formato de direcciones MAC (ONT/Bridge y Router).
"""
import re
from typing import Optional

def extract_ont_mac(mac_str: Optional[str], clean: bool = False) -> Optional[str]:
    """Extrae la MAC o SN correspondiente a la ONT/Bridge."""
    if not mac_str:
        return None
    mac_str = str(mac_str).strip()
    res = None
    m = re.search(r'ONT:\s*([0-9A-Za-z:\.\-]+)', mac_str, re.IGNORECASE)
    if m:
        res = m.group(1).strip()
    elif '|' in mac_str:
        res = mac_str.split('|')[0].replace('ONT:', '').strip()
    elif '/' in mac_str:
        res = mac_str.split('/')[0].replace('ONT:', '').strip()
    else:
        res = mac_str

    if clean and res:
        return re.sub(r'[^A-Fa-f0-9]', '', res).upper()
    return res

def extract_router_mac(mac_str: Optional[str], clean: bool = False) -> Optional[str]:
    """Extrae la MAC correspondiente al Router."""
    if not mac_str:
        return None
    mac_str = str(mac_str).strip()
    res = None
    m = re.search(r'(?:ROUTER|R):\s*([0-9A-Za-z:\.\-]+)', mac_str, re.IGNORECASE)
    if m:
        res = m.group(1).strip()
    elif '|' in mac_str:
        parts = mac_str.split('|')
        if len(parts) > 1:
            res = parts[1].replace('ROUTER:', '').replace('R:', '').strip()
    elif '/' in mac_str:
        parts = mac_str.split('/')
        if len(parts) > 1:
            res = parts[1].replace('ROUTER:', '').replace('R:', '').strip()
    else:
        res = mac_str

    if clean and res:
        return re.sub(r'[^A-Fa-f0-9]', '', res).upper()
    return res

def format_mac_standard(mac_str: Optional[str]) -> Optional[str]:
    """Formatea una MAC a formato estándar XX:XX:XX:XX:XX:XX si tiene 12 hex."""
    if not mac_str:
        return None
    raw = re.sub(r'[^A-Fa-f0-9]', '', str(mac_str)).upper()
    if len(raw) == 12:
        return ':'.join(raw[i:i+2] for i in range(0, 12, 2))
    return str(mac_str).strip().upper()

def combine_macs(current_mac: Optional[str], new_router_mac: Optional[str]) -> Optional[str]:
    """
    Combina la MAC de la ONT/Bridge y la MAC del Router en un solo campo legible.
    Formato: ONT: <mac_ont> | R: <mac_router>
    """
    if not current_mac and not new_router_mac:
        return None
    if not new_router_mac:
        return current_mac
    if not current_mac:
        return format_mac_standard(new_router_mac)

    ont_part = extract_ont_mac(current_mac)
    rtr_part = extract_router_mac(new_router_mac) or new_router_mac

    norm_ont = re.sub(r'[^A-Fa-f0-9]', '', ont_part or '').upper()
    norm_rtr = re.sub(r'[^A-Fa-f0-9]', '', rtr_part or '').upper()

    # Si son exactamente la misma MAC (ej: ONT pura sin router secundario), mantener una sola
    if norm_ont == norm_rtr and norm_ont:
        return format_mac_standard(ont_part)

    fmt_ont = format_mac_standard(ont_part) if (len(norm_ont) == 12) else (ont_part or '').strip()
    fmt_rtr = format_mac_standard(rtr_part) if (len(norm_rtr) == 12) else (rtr_part or '').strip()

    if not fmt_ont:
        return fmt_rtr
    if not fmt_rtr:
        return fmt_ont

    return f"ONT: {fmt_ont} | R: {fmt_rtr}"
