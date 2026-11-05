#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config_emisor_gourmet.py — READ/WRITE mínimo. Configura la cuenta de Rest Gourmet
(RUC 10467016283, TTITO HUAMANI SARA):
  - config_json.codigo_establecimiento = '0003'  (AddressTypeCode del XML)
  - emisión ilimitada: produccion=True, modo_test=False, plan='ilimitado',
    docs_mes_limite=999999, config_json.plan_vence='2028-11-03'
  - certificado activo: fecha_vencimiento = 2029-11-03

Flujo seguro: primero MUESTRA el emisor (dry-run). Solo ESCRIBE con --confirm.

USO (en Railway):
    python -m src.scripts.config_emisor_gourmet            # dry-run (no escribe)
    python -m src.scripts.config_emisor_gourmet --confirm  # aplica
"""
import sys
from datetime import date, datetime, timezone

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Certificado

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RUC = '10467016283'
ESTAB = '0003'
PLAN_VENCE = '2028-11-03'
CERT_VENCE = date(2029, 11, 3)


def main():
    confirm = '--confirm' in sys.argv
    db = SessionLocal()
    try:
        em = db.query(Emisor).filter(Emisor.ruc == RUC).first()
        if not em:
            print(f"\n🛑 No existe emisor con RUC {RUC}.\n"); sys.exit(1)
        cert = (db.query(Certificado).filter_by(emisor_id=em.id, activo=True)
                .order_by(Certificado.creado_en.desc()).first())
        cfg = dict(em.config_json or {})

        print("=" * 72)
        print(f"EMISOR {em.ruc} — {em.razon_social}")
        print(f"  produccion       : {em.produccion}  → True")
        print(f"  modo_test        : {em.modo_test}  → False")
        print(f"  plan             : {em.plan}  → 'ilimitado'")
        print(f"  docs_mes_limite  : {em.docs_mes_limite}  → 999999")
        print(f"  cfg.codigo_establecimiento : {cfg.get('codigo_establecimiento')}  → {ESTAB}")
        print(f"  cfg.plan_vence   : {cfg.get('plan_vence')}  → {PLAN_VENCE}")
        print(f"  certificado      : {'(activo)' if cert else 'NINGUNO'}"
              f"  fecha_vencimiento: {getattr(cert, 'fecha_vencimiento', None)}  → {CERT_VENCE}")
        print("=" * 72)

        if not confirm:
            print("[DRY-RUN] Nada escrito. Para aplicar: --confirm\n")
            return

        cfg['codigo_establecimiento'] = ESTAB
        cfg['plan_vence'] = PLAN_VENCE
        em.config_json = cfg            # reasignar: el ORM detecta el cambio del JSON
        em.produccion = True
        em.modo_test = False
        em.plan = 'ilimitado'
        em.docs_mes_limite = 999999
        if hasattr(em, 'actualizado_en'):
            em.actualizado_en = datetime.now(timezone.utc)
        if cert:
            cert.fecha_vencimiento = CERT_VENCE
        else:
            print("   ⚠️ El emisor NO tiene certificado activo; no se tocó fecha_vencimiento.")
        db.commit()
        print("✅ Aplicado. Reemite para ver el AddressTypeCode=0003 en el XML.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
