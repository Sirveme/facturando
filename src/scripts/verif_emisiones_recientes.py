#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verif_emisiones_recientes.py — READ-ONLY. Verifica que las emisiones nuevas guarden
el estado correcto según el CDR (post-deploy de la clasificación).

Marca ANOMALÍAS: estado 'aceptado_con_observaciones' con código 2xxx/3xxx (bug viejo),
'aceptado' con código != 0, o 'rechazado' con código 0.

USO:
    python -m src.scripts.verif_emisiones_recientes --desde "2026-11-10 22:43"
"""
import sys
from datetime import datetime
from collections import Counter

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, RespuestaSunat

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    desde_str = "2026-11-10 22:43"
    if '--desde' in sys.argv:
        i = sys.argv.index('--desde')
        if i + 1 < len(sys.argv):
            desde_str = sys.argv[i + 1]
    desde = datetime.strptime(desde_str, "%Y-%m-%d %H:%M")

    db = SessionLocal()
    try:
        rows = (db.query(Comprobante, Emisor)
                .join(Emisor, Emisor.id == Comprobante.emisor_id)
                .filter(Comprobante.creado_en >= desde)
                .order_by(Comprobante.creado_en.asc()).all())

        print("=" * 96)
        print(f"EMISIONES DESDE {desde} UTC — {len(rows)} comprobante(s)")
        print("=" * 96)

        est_count = Counter()
        obs_cod_count = Counter()
        con_obs = []
        anomalias = []
        for comp, em in rows:
            resp = (db.query(RespuestaSunat)
                    .filter(RespuestaSunat.comprobante_id == comp.id)
                    .order_by(RespuestaSunat.recibido_en.desc()).first())
            cod = (resp.codigo_cdr if resp else None)
            obs_list = (resp.observaciones if (resp and resp.observaciones) else []) or []
            nobs = len(obs_list)
            obs_cods = ','.join(sorted({str(o.get('codigo')) for o in obs_list})) if obs_list else ''
            est = comp.estado
            est_count[est] += 1
            for o in obs_list:
                obs_cod_count[str(o.get('codigo'))] += 1
            if est == 'aceptado_con_observaciones':
                con_obs.append((em.ruc, comp.numero_formato, obs_cods))
            # Detección de anomalías
            anom = ''
            c = str(cod or '')
            if est == 'aceptado_con_observaciones' and (c.startswith('2') or c.startswith('3')):
                anom = '  ❌ ANOMALÍA: obs con código de RECHAZO'
            elif est == 'aceptado' and c and c != '0':
                anom = f'  ❌ ANOMALÍA: aceptado con código {c}'
            elif est == 'rechazado' and c == '0':
                anom = '  ❌ ANOMALÍA: rechazado con código 0'
            if anom:
                anomalias.append((em.ruc, comp.numero_formato, est, cod, anom))
            print(f"  {em.ruc:<11} {comp.numero_formato:<16} {str(comp.creado_en)[:19]}  "
                  f"estado={est:<26} cod={cod}  obs={nobs}{(' ['+obs_cods+']') if obs_cods else ''}{anom}")

        print("\n" + "-" * 96)
        print(f"TOTAL emisiones: {len(rows)}")
        print("Resumen por estado:", dict(est_count))
        print(f"aceptado_con_observaciones: {est_count.get('aceptado_con_observaciones', 0)}"
              + (f"  códigos={dict(obs_cod_count)}" if obs_cod_count else ""))
        for ruc, num, cods in con_obs:
            print(f"    · {ruc} {num}  obs[{cods}]")
        if anomalias:
            print(f"\n❌ {len(anomalias)} ANOMALÍA(S):")
            for a in anomalias:
                print("   ", a)
        else:
            print("✅ Sin anomalías: todos los estados concuerdan con el código del CDR.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
