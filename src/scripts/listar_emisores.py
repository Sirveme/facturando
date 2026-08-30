#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
listar_emisores.py — AUDITORÍA DE SOLO LECTURA: todos los emisores y su modo SUNAT.

Muestra por emisor: RUC, razón social, produccion (sí/no), modo_test, sol_usuario,
certificado activo (sí/no) y cuántos comprobantes aceptados tiene. No escribe NADA.

Sirve para: ver beta vs prod, confirmar que los emisores reales están en produccion=True,
y detectar un emisor de prueba en beta reutilizable para A2.

Ejecutar EN RAILWAY:
    python -m src.scripts.listar_emisores
"""
from sqlalchemy import func

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Certificado, Comprobante

# Emisores reales que DEBEN estar en producción (chequeo de seguridad). Ajusta los RUC si aplica.
PROD_ESPERADOS = {
    '10736459791': 'Maykol (taller)',
    '20103830991': 'CCPL',
    '20615643735': 'Shevalche',
    '20615446565': 'Peru Sistemas'
}


def _si(v):
    return 'sí' if v else 'no'


def main():
    db = SessionLocal()
    try:
        emisores = (db.query(Emisor)
                    .order_by(Emisor.produccion.desc(), Emisor.razon_social)
                    .all())

        cert_ids = {r[0] for r in db.query(Certificado.emisor_id)
                    .filter(Certificado.activo == True).distinct().all()}  # noqa: E712

        aceptados = dict(db.query(Comprobante.emisor_id, func.count())
                         .filter(Comprobante.estado.in_(('aceptado', 'aceptado_con_observaciones')))
                         .group_by(Comprobante.emisor_id).all())

        print("=" * 104)
        print(f"EMISORES ({len(emisores)})")
        print("=" * 104)
        print(f"{'RUC':<12} {'RAZÓN SOCIAL':<34} {'PROD':<5} {'TEST':<5} {'SOL_USUARIO':<14} {'CERT':<5} {'ACEPT':>6}")
        print("-" * 104)
        for e in emisores:
            razon = (e.razon_social or '')[:33]
            print(f"{e.ruc:<12} {razon:<34} {_si(e.produccion):<5} {_si(e.modo_test):<5} "
                  f"{(e.sol_usuario or '—'):<14} {_si(e.id in cert_ids):<5} {aceptados.get(e.id, 0):>6}")

        # ============ CHEQUEO DE SEGURIDAD ============
        print("\n" + "=" * 104)
        print("CHEQUEO DE SEGURIDAD")
        print("=" * 104)

        # (a) Emisores reales esperados en prod: confirmar produccion=True
        print("\n[a] Emisores reales que deben estar en produccion=True:")
        by_ruc = {e.ruc: e for e in emisores}
        for ruc, nombre in PROD_ESPERADOS.items():
            e = by_ruc.get(ruc)
            if not e:
                print(f"    {ruc} ({nombre}): ❓ no encontrado")
            elif e.produccion:
                print(f"    {ruc} ({nombre}): ✅ produccion=True")
            else:
                print(f"    {ruc} ({nombre}): 🔴 ¡EN BETA! (produccion=False) — REVISAR")

        # (b) Emisores en BETA que parecen productivos (cert o aceptados) -> posible error
        print("\n[b] Emisores en BETA (produccion=False) que parecen productivos:")
        sospechosos = [e for e in emisores if not e.produccion
                       and (e.id in cert_ids or aceptados.get(e.id, 0) > 0)]
        if not sospechosos:
            print("    (ninguno) ✅")
        else:
            for e in sospechosos:
                print(f"    ⚠️ {e.ruc} {e.razon_social} — cert={_si(e.id in cert_ids)} "
                      f"aceptados={aceptados.get(e.id, 0)}  (¿debería estar en prod?)")

        # (c) Emisores en BETA candidatos para probar A2 (produccion=False)
        print("\n[c] Emisores en BETA (produccion=False) — candidatos para probar A2:")
        beta = [e for e in emisores if not e.produccion]
        if not beta:
            print("    (ninguno — habría que crear un emisor de prueba beta)")
        else:
            for e in beta:
                listo = (e.id in cert_ids) and e.sol_usuario
                print(f"    {e.ruc} {e.razon_social[:30]:<30} sol={e.sol_usuario or '—'} "
                      f"cert={_si(e.id in cert_ids)}  -> {'LISTO para A2' if listo else 'falta cert/SOL'}")
        print("=" * 104)

    finally:
        db.close()


if __name__ == '__main__':
    main()
