#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_detraccion_maykol.py — SOLO LECTURA.

Identifica de dónde sale la detracción en las facturas de Maykol (AUTOMOTRIZ
INTEGRAL CASTILLO, RUC 10736459791): lista los comprobantes NO aceptados y los
que tienen detraccion_monto guardado, con su fecha de creación (antes/después
del deploy del fix Bug 1 = 2026-09-09) y sus intentos de envío.

Hipótesis a confirmar: los que fallan con 3128 al re-enviarse fueron CREADOS
antes del fix (era del auto-marcado) y tienen detraccion_monto persistido; el
re-envío regenera el XML SPOT desde esas columnas, sin pasar por el formulario.

No escribe NADA. Ejecutar EN RAILWAY:
    python -m src.scripts.diag_detraccion_maykol
"""
from datetime import date

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante

RUC = '10736459791'
FIX_BUG1 = date(2026, 9, 9)   # deploy del Bug 1 (quitó el auto-marcado)


def main():
    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == RUC).first()
        if not emisor:
            print(f"❌ No existe emisor {RUC}")
            return

        cfg = (emisor.config_json or {}).get('detraccion') or {}
        print("=" * 92)
        print(f"EMISOR {emisor.ruc} — {emisor.razon_social}")
        print(f"config_json.detraccion = {cfg}")
        print(f"emisor.cuenta_detraccion = {getattr(emisor, 'cuenta_detraccion', None)}")
        print("=" * 92)

        # 1) Comprobantes CON detraccion_monto guardado (origen del SPOT en el XML)
        con_det = (db.query(Comprobante)
                   .filter(Comprobante.emisor_id == emisor.id,
                           Comprobante.detraccion_monto.isnot(None))
                   .order_by(Comprobante.serie, Comprobante.numero.desc()).all())
        print(f"\n[A] Comprobantes con detraccion_monto GUARDADO: {len(con_det)}")
        print(f"    {'serie-num':16} {'estado':14} {'creado_en':19} {'det_monto':10} {'cod':5} {'int':3} pre-fix?")
        for c in con_det:
            creado = c.creado_en.strftime('%Y-%m-%d %H:%M') if c.creado_en else '—'
            pre = 'SÍ (era auto-marcado)' if (c.creado_en and c.creado_en.date() < FIX_BUG1) else 'no'
            print(f"    {c.serie}-{c.numero:<10} {str(c.estado):14} {creado:19} "
                  f"{str(c.detraccion_monto):10} {str(c.detraccion_codigo_bien or '-'):5} "
                  f"{str(c.intentos_envio or 0):3} {pre}")

        # 2) Comprobantes NO aceptados (candidatos a re-envío → pueden re-generar SPOT)
        no_ok = (db.query(Comprobante)
                 .filter(Comprobante.emisor_id == emisor.id,
                         Comprobante.tipo_documento == '01',
                         Comprobante.estado != 'aceptado')
                 .order_by(Comprobante.numero.desc()).limit(20).all())
        print(f"\n[B] Facturas (01) NO aceptadas (últimas {len(no_ok)}):")
        print(f"    {'serie-num':16} {'estado':16} {'creado_en':19} {'det_monto':10} {'int':3}")
        for c in no_ok:
            creado = c.creado_en.strftime('%Y-%m-%d %H:%M') if c.creado_en else '—'
            print(f"    {c.serie}-{c.numero:<10} {str(c.estado):16} {creado:19} "
                  f"{str(c.detraccion_monto):10} {str(c.intentos_envio or 0):3}")

        print("\n" + "=" * 92)
        print("LECTURA:")
        print(" - En [A], los marcados 'pre-fix' con estado != aceptado son los que, al re-enviarse,")
        print("   regeneran el bloque SPOT → 3128. Ese es el/los comprobante(s) a corregir.")
        print(" - Si en [A] hay alguno creado DESPUÉS del 2026-09-09 con detraccion_monto, ahí la")
        print("   casilla SÍ se marcó al emitir (revisar ese caso puntual).")
        print(" - Corrección (fase siguiente, con tu OK): limpiar detraccion_monto/codigo/porcentaje")
        print("   en esos comprobantes concretos antes de re-enviarlos (venta de bienes = sin SPOT).")
        print("=" * 92)
    finally:
        db.close()


if __name__ == '__main__':
    main()
