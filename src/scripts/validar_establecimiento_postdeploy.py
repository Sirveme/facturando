#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validar_establecimiento_postdeploy.py — READ-ONLY. Valida tras el deploy:
  (1) La 1ª emisión de Gourmet (RUC 10467016283) → AddressTypeCode = 0003 + CDR aceptado.
  (2) La 1ª emisión de CUALQUIER otro emisor → AddressTypeCode = 0000 + aceptada
      (no se rompió el default para el resto).

Lee el XML FIRMADO real (Comprobante.xml) de la BD. No escribe nada.

USO (en Railway, tras el deploy de la noche):
    python -m src.scripts.validar_establecimiento_postdeploy --desde "2026-11-04 23:00"
    # --desde = momento del deploy (hora Lima). Default: hoy 00:00.
"""
import re
import sys
from datetime import datetime

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RUC_GOURMET = '10467016283'
RUC_OTRO = '20615446565'   # Perú Sistemas Pro — control del default 0000 (boleta B999 consumidor final)
ACEPTADOS = ('aceptado', 'aceptado_con_observaciones')


def _address_type_code(xml):
    if not xml:
        return None
    t = xml.decode('utf-8', 'replace') if isinstance(xml, (bytes, bytearray)) else str(xml)
    m = re.search(r'<cbc:AddressTypeCode>([^<]*)</cbc:AddressTypeCode>', t)
    return m.group(1) if m else None


def _primera_emision(db, desde, ruc):
    """Primera emisión (con XML) de un emisor concreto desde `desde`."""
    return (db.query(Comprobante).join(Emisor, Comprobante.emisor_id == Emisor.id)
            .filter(Comprobante.creado_en >= desde, Comprobante.xml.isnot(None), Emisor.ruc == ruc)
            .order_by(Comprobante.creado_en.asc()).first())


def _reporta(db, comp, etiqueta, estab_esperado):
    emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
    atc = _address_type_code(comp.xml)
    resp = comp.respuesta
    cdr_cod = resp.codigo_cdr if resp else None
    cdr_desc = resp.descripcion if resp else None
    aceptada = comp.estado in ACEPTADOS
    estab_ok = (atc == estab_esperado)
    print(f"\n── {etiqueta} ──")
    print(f"  Emisor         : {emisor.ruc if emisor else '?'} — {emisor.razon_social if emisor else '?'}")
    print(f"  Comprobante    : {comp.numero_formato}  creado={comp.creado_en}")
    print(f"  AddressTypeCode: {atc}   (esperado {estab_esperado})  {'✅' if estab_ok else '❌'}")
    print(f"  Estado         : {comp.estado}   {'✅ aceptada' if aceptada else '❌ NO aceptada'}")
    print(f"  CDR            : {cdr_cod} — {cdr_desc}")
    return estab_ok and aceptada


def main():
    desde_str = None
    if '--desde' in sys.argv:
        i = sys.argv.index('--desde')
        if i + 1 < len(sys.argv):
            desde_str = sys.argv[i + 1]
    ruc_otro = RUC_OTRO
    if '--otro-ruc' in sys.argv:
        j = sys.argv.index('--otro-ruc')
        if j + 1 < len(sys.argv):
            ruc_otro = sys.argv[j + 1].strip()
    if desde_str:
        try:
            desde = datetime.strptime(desde_str, "%Y-%m-%d %H:%M")
        except ValueError:
            print("🛑 --desde debe ser 'YYYY-MM-DD HH:MM'."); sys.exit(1)
    else:
        desde = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    print("=" * 72)
    print(f"VALIDACIÓN POST-DEPLOY — emisiones desde {desde}")
    print("=" * 72)

    db = SessionLocal()
    ok = True
    try:
        g = _primera_emision(db, desde, RUC_GOURMET)
        if not g:
            print(f"\n⚠️ Aún no hay emisión de Gourmet ({RUC_GOURMET}) con XML desde esa fecha.")
            ok = False
        else:
            ok &= _reporta(db, g, "GOURMET (esperado 0003)", '0003')

        o = _primera_emision(db, desde, ruc_otro)
        if not o:
            print(f"\n⚠️ Aún no hay emisión de {ruc_otro} (control 0000) con XML desde esa fecha.")
            ok = False
        else:
            ok &= _reporta(db, o, f"CONTROL {ruc_otro} (esperado 0000)", '0000')

        print("\n" + "=" * 72)
        print("RESULTADO:", "TODO OK ✅" if ok else "REVISAR ❌ (ver detalle arriba)")
    finally:
        db.close()


if __name__ == '__main__':
    main()
