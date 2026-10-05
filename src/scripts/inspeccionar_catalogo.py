#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspeccionar_catalogo.py — READ-ONLY. Confirma que el catálogo del central quedó
sembrado completo, SIN emitir ni escribir nada.

Muestra: los productos con su serie; los planes por producto (publicables e
internos); y valida que (a) hay 5 productos con series distintas, (b) facturalo y
quevendi tienen sus planes publicables, (c) hay un plan 'prueba' S/4 publico=false
por CADA producto.

USO (en Railway):
    python -m src.scripts.inspeccionar_catalogo
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from src.api.dependencies import SessionLocal
from src.models.models import SuscProducto, SuscPlan, SuscPlanIncluye

SERIES_ESPERADAS = {
    'facturalo': 'FF50', 'quevendi': 'FQ50', 'metraes': 'FM50',
    'alerta': 'FA50', 'pagook': 'FP50',
}

ok = True
def chk(n, c, extra=""):
    global ok; ok = ok and c
    print(f"  [{'OK ' if c else 'FAIL'}] {n}{(' — ' + extra) if extra else ''}")


def main():
    db = SessionLocal()
    try:
        productos = db.query(SuscProducto).order_by(SuscProducto.codigo).all()

        print("=" * 72)
        print("PRODUCTOS")
        print("=" * 72)
        for p in productos:
            print(f"  {p.codigo:12} serie={p.serie_factura:6} activo={p.activo}  nombre={p.nombre}")

        print("\n" + "=" * 72)
        print("PLANES POR PRODUCTO (precio_mensual / precio_anual)")
        print("=" * 72)
        for p in productos:
            planes = db.query(SuscPlan).filter(SuscPlan.producto_id == p.id)\
                       .order_by(SuscPlan.orden, SuscPlan.codigo).all()
            print(f"\n  {p.codigo} ({p.serie_factura}):")
            if not planes:
                print("    (sin planes)")
            for pl in planes:
                etq = 'PUBLICO ' if pl.publico else 'interno '
                act = 'activo' if pl.activo else 'INACTIVO'
                print(f"    - {pl.codigo:18} {etq} {act:8} "
                      f"S/{pl.precio_mensual}/mes  S/{pl.precio_anual}/año   {pl.nombre}")

        # Inclusiones (informativo)
        inc = db.query(SuscPlanIncluye).count()
        print(f"\n  Inclusiones (susc_plan_incluye): {inc} fila(s).")

        # ── Validaciones ────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("VALIDACIONES")
        print("=" * 72)

        por_codigo = {p.codigo: p for p in productos}

        # (a) 5 productos con las series esperadas
        chk("5 productos", len(productos) == 5, str(len(productos)))
        for cod, serie in SERIES_ESPERADAS.items():
            p = por_codigo.get(cod)
            chk(f"producto {cod} con serie {serie}",
                bool(p) and p.serie_factura == serie,
                (p.serie_factura if p else 'FALTA'))
        series = [p.serie_factura for p in productos]
        chk("series distintas (sin duplicados)", len(set(series)) == len(series), str(series))

        # (b) planes publicables de facturalo y quevendi
        def publicables(cod):
            p = por_codigo.get(cod)
            if not p:
                return []
            return sorted(pl.codigo for pl in db.query(SuscPlan).filter(
                SuscPlan.producto_id == p.id, SuscPlan.publico.is_(True),
                SuscPlan.activo.is_(True)).all())
        chk("facturalo publicables = emprendedor, negocio",
            publicables('facturalo') == ['emprendedor', 'negocio'], str(publicables('facturalo')))
        chk("quevendi publicables = crece, pro",
            publicables('quevendi') == ['crece', 'pro'], str(publicables('quevendi')))

        # (c) un plan 'prueba' S/4, publico=false, por cada producto
        for cod, p in por_codigo.items():
            pr = db.query(SuscPlan).filter(
                SuscPlan.producto_id == p.id, SuscPlan.codigo == 'prueba').first()
            bien = bool(pr) and (pr.publico is False) and (pr.activo is True) \
                and str(pr.precio_mensual) == '4.00' and str(pr.precio_anual) == '4.00'
            detalle = "falta" if not pr else \
                f"publico={pr.publico} activo={pr.activo} S/{pr.precio_mensual}/{pr.precio_anual}"
            chk(f"prueba en {cod} (S/4, interno, activo)", bien, detalle)

        print("\nRESULTADO:", "CATÁLOGO COMPLETO ✅" if ok else "REVISAR — hay faltantes ❌")
    finally:
        db.close()


if __name__ == '__main__':
    main()
