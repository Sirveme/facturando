#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reclasificar_observaciones_4xxx.py

(b) Comprobantes con codigo_cdr = 0 cuyo cdr_xml trae notas 4xxx → en realidad son
    'aceptado_con_observaciones'. Este script:
      - reclasifica estado → 'aceptado_con_observaciones'
      - extrae las notas 4xxx del cdr_xml y las guarda en respuesta_sunat.observaciones

Usa el MISMO extractor que el flujo real (sunat_client._extraer_observaciones_4xxx),
para que el histórico quede igual que las emisiones nuevas.

DRY-RUN por defecto. Con --confirm aplica.
⚠️ --confirm requiere que la columna respuesta_sunat.observaciones EXISTA
   (correr sql/zClaude-observaciones-cdr.sql y desplegar el código primero).

USO:
    python -m src.scripts.reclasificar_observaciones_4xxx            # dry-run
    python -m src.scripts.reclasificar_observaciones_4xxx --confirm  # aplica
    python -m src.scripts.reclasificar_observaciones_4xxx --limit 50 # acota (dry-run)
"""
import sys
from collections import Counter

from lxml import etree
from sqlalchemy import text

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, RespuestaSunat
from src.services.sunat_client import _extraer_observaciones_4xxx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _obs_de_cdr(cdr_xml):
    if not cdr_xml:
        return []
    t = cdr_xml.decode('utf-8', 'replace') if isinstance(cdr_xml, (bytes, bytearray)) else str(cdr_xml)
    try:
        doc = etree.fromstring(t.encode('utf-8'))
    except Exception:
        return []
    return _extraer_observaciones_4xxx(doc)


def main():
    confirm = '--confirm' in sys.argv
    limit = None
    if '--limit' in sys.argv:
        i = sys.argv.index('--limit')
        if i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    expect = None
    if '--expect' in sys.argv:
        j = sys.argv.index('--expect')
        if j + 1 < len(sys.argv):
            expect = int(sys.argv[j + 1])

    db = SessionLocal()
    try:
        if confirm:
            # Todo en UNA transacción; si no puede tomar el lock en 3s, FALLA (no bloquea).
            db.execute(text("SET lock_timeout = '3s'"))
        q = (db.query(Comprobante, RespuestaSunat)
             .join(RespuestaSunat, RespuestaSunat.comprobante_id == Comprobante.id)
             .filter(RespuestaSunat.codigo_cdr == '0', RespuestaSunat.cdr_xml.isnot(None)))

        print("=" * 90)
        print("RECLASIFICAR OBSERVACIONES 4xxx (codigo 0 con notas → aceptado_con_observaciones)")
        print(f"MODO: {'APLICAR (--confirm)' if confirm else 'DRY-RUN (no escribe)'}"
              + (f"  [limit {limit}]" if limit else ""))
        print("=" * 90)

        cambiados = 0
        revisados = 0
        cont_cod = Counter()
        for comp, resp in q.all():
            revisados += 1
            obs = _obs_de_cdr(resp.cdr_xml)
            if not obs:
                continue
            cambiados += 1
            for o in obs:
                cont_cod[o['codigo']] += 1
            if cambiados <= 15:
                codes = ', '.join(sorted({o['codigo'] for o in obs}))
                print(f"  {comp.numero_formato}  estado {comp.estado} → aceptado_con_observaciones"
                      f"  OBS[{codes}]")
            if confirm:
                comp.estado = 'aceptado_con_observaciones'
                resp.observaciones = obs
            if limit and cambiados >= limit and not confirm:
                break

        print(f"\n  revisados {revisados} | con observaciones 4xxx: {cambiados}")
        print(f"  conteo por código: {dict(cont_cod.most_common())}")

        if not confirm:
            print("\n[DRY-RUN] Nada escrito. Para aplicar: --confirm (requiere columna observaciones).")
            return

        # Verificación de conteo exacto ANTES de commit: si no coincide → ROLLBACK.
        if expect is not None and cambiados != expect:
            db.rollback()
            print(f"\n🛑 ROLLBACK: cambiados={cambiados} != esperado={expect}. NADA aplicado.")
            sys.exit(2)

        db.commit()
        print(f"\n✅ COMMIT: {cambiados} comprobante(s) → 'aceptado_con_observaciones' + observaciones guardadas.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
