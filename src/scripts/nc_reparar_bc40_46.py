#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nc_reparar_bc40_46.py — FASE 2: reparar el hash_cpe faltante de la NC BC40-46.

La BC40-46 ya fue ACEPTADA por SUNAT (ResponseCode 0), pero quedó con hash_cpe=NULL por
el bug del script de prueba. El hash NO viene del CDR: es el DigestValue del XML firmado
que se envió, y ese XML ya está guardado en comprobante.xml. Por tanto la reparación es
un UPDATE local, SIN re-consultar SUNAT.

Ejecutar EN RAILWAY:
  Dry-run (muestra el hash recuperado, no escribe):
      python -m src.scripts.nc_reparar_bc40_46
  Aplicar el UPDATE:
      python -m src.scripts.nc_reparar_bc40_46 --send

Al final imprime la verificación de BC40-39/40/46 (las tres deben tener hash_cpe no nulo).
"""

import sys

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante
from src.scripts.nc_prueba_bingazo import _extraer_hash_cpe

NC_SERIE = 'BC40'
NC_NUMERO_REPARAR = 46


def _verificar(db):
    print("\n--- Verificación BC40 39/40/46 ---")
    filas = (
        db.query(Comprobante)
        .filter(Comprobante.serie == NC_SERIE, Comprobante.numero.in_([39, 40, 46]))
        .order_by(Comprobante.numero)
        .all()
    )
    for c in filas:
        marca = "OK" if c.hash_cpe else "❌ NULL"
        print(f"  {c.serie}-{c.numero}  estado={c.estado}  hash_cpe={c.hash_cpe or '(NULL)'}  [{marca}]")
    faltan = [f"{c.serie}-{c.numero}" for c in filas if not c.hash_cpe]
    if faltan:
        print(f"  ⚠️ Aún sin hash: {', '.join(faltan)}")
    else:
        print("  ✅ Las tres tienen hash_cpe.")
    print("--- fin verificación ---")


def main():
    send_mode = '--send' in sys.argv
    print("=" * 72)
    print(f"REPARAR hash_cpe de {NC_SERIE}-{NC_NUMERO_REPARAR}")
    print("MODO:", "🚨 APLICAR UPDATE" if send_mode else "🧪 DRY-RUN (sin escribir)")
    print("=" * 72)

    db = SessionLocal()
    try:
        nc = (
            db.query(Comprobante)
            .filter(Comprobante.serie == NC_SERIE, Comprobante.numero == NC_NUMERO_REPARAR)
            .first()
        )
        if not nc:
            print(f"🛑 No se encontró {NC_SERIE}-{NC_NUMERO_REPARAR}."); sys.exit(1)

        print(f"[1] {nc.numero_formato}  estado={nc.estado}  hash_cpe_actual={nc.hash_cpe or '(NULL)'}  "
              f"ref={nc.doc_referencia_numero}")

        if nc.hash_cpe:
            print("[2] Ya tiene hash_cpe; no se modifica.")
            _verificar(db)
            return

        if not nc.xml:
            print("🛑 La NC no tiene XML firmado guardado (comprobante.xml vacío). No se puede recuperar "
                  "el DigestValue localmente. Sería necesario re-consultar SUNAT — DETENERSE y reportar "
                  "a Duilio para decidir el camino.")
            sys.exit(1)

        hash_recuperado = _extraer_hash_cpe(nc.xml)
        if not hash_recuperado:
            print("🛑 No se encontró DigestValue en el XML guardado. DETENERSE y reportar.")
            sys.exit(1)

        print(f"[2] Hash recuperado del XML firmado: {hash_recuperado}")

        if not send_mode:
            print("\n🧪 DRY-RUN: no se escribió. Para aplicar:  python -m src.scripts.nc_reparar_bc40_46 --send")
            _verificar(db)
            return

        nc.hash_cpe = hash_recuperado
        db.commit()
        print(f"[3] ✅ UPDATE aplicado: {nc.numero_formato}.hash_cpe = {hash_recuperado}")
        _verificar(db)
        print("\n🛑 FIN FASE 2. Reportar esta verificación a Duilio ANTES de emitir el lote (FASE 3).")

    finally:
        db.close()


if __name__ == '__main__':
    main()
