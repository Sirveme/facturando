#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reclasificar_rechazos_malclasificados.py

(a) Los comprobantes en estado 'aceptado_con_observaciones' cuyo codigo_cdr empieza en
    2 o 3 son RECHAZOS mal clasificados (bug viejo). Este script los pasa a 'rechazado'.

DRY-RUN por defecto (no escribe). Con --confirm aplica.
Siempre imprime la lista agrupada por emisor (con el cliente) para avisar a cada uno.

⚠️ NO revierte stock: si alguno descontó stock al marcarse 'aceptado', eso se evalúa aparte.

USO:
    python -m src.scripts.reclasificar_rechazos_malclasificados            # dry-run
    python -m src.scripts.reclasificar_rechazos_malclasificados --confirm  # aplica
"""
import sys
from collections import defaultdict

from sqlalchemy import text

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, RespuestaSunat

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    confirm = '--confirm' in sys.argv
    expect = None
    if '--expect' in sys.argv:
        j = sys.argv.index('--expect')
        if j + 1 < len(sys.argv):
            expect = int(sys.argv[j + 1])
    db = SessionLocal()
    try:
        if confirm:
            # Todo en UNA transacción; si no toma el lock en 3s, FALLA (no bloquea).
            db.execute(text("SET lock_timeout = '3s'"))
        q = (db.query(Comprobante, RespuestaSunat, Emisor)
             .join(RespuestaSunat, RespuestaSunat.comprobante_id == Comprobante.id)
             .join(Emisor, Emisor.id == Comprobante.emisor_id)
             .filter(Comprobante.estado == 'aceptado_con_observaciones'))
        objetivos = [(c, r, e) for (c, r, e) in q.all()
                     if (r.codigo_cdr or '').startswith(('2', '3'))]

        print("=" * 90)
        print(f"RECLASIFICAR RECHAZOS MAL CLASIFICADOS — {len(objetivos)} comprobante(s)")
        print(f"MODO: {'APLICAR (--confirm)' if confirm else 'DRY-RUN (no escribe)'}")
        print("=" * 90)

        por_emisor = defaultdict(list)
        for c, r, e in objetivos:
            por_emisor[(e.ruc, e.razon_social)].append((c, r))

        for (ruc, razon), items in sorted(por_emisor.items()):
            print(f"\n■ Emisor {ruc} — {razon}  ({len(items)} doc):")
            for c, r in items:
                print(f"    {c.numero_formato}  {str(c.fecha_emision)[:10]}  S/{c.monto_total}"
                      f"  cod={r.codigo_cdr}")
                print(f"        cliente: {c.cliente_numero_documento} — {c.cliente_razon_social}")
                print(f"        motivo SUNAT: {(r.descripcion or '')[:90]}")
                print(f"        estado: {c.estado} → rechazado")

        if not confirm:
            print("\n[DRY-RUN] Nada escrito. Para aplicar: --confirm")
            return

        # Verificación de conteo exacto ANTES de tocar nada: si no coincide → ROLLBACK (abortar).
        if expect is not None and len(objetivos) != expect:
            db.rollback()
            print(f"\n🛑 ROLLBACK: encontrados={len(objetivos)} != esperado={expect}. NADA aplicado.")
            sys.exit(2)

        for c, r, e in objetivos:
            c.estado = 'rechazado'   # SOLO estado; no se toca stock ni nada más
            c.descripcion_respuesta = (f"[reclasificado] Rechazo SUNAT {r.codigo_cdr}: "
                                       f"{(r.descripcion or '')}")[:500]
        db.commit()
        print(f"\n✅ COMMIT: {len(objetivos)} comprobante(s) → 'rechazado'.")
        print("⚠️ Recordar: avisar a cada cliente y evaluar reversa de stock si aplicó (no tocado aquí).")
    finally:
        db.close()


if __name__ == '__main__':
    main()
