#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspeccionar_suscripciones.py — SOLO LECTURA. Vuelca TODAS las suscripciones
(sin filtrar), las facturas FF50, y las banderas del emisor PSP (para detectar
si una autofactura o un rollback dejó algo a medias). No escribe nada.

Ejecutar EN RAILWAY:
    python -m src.scripts.inspeccionar_suscripciones
"""
from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante, Suscripcion

RUC_PSP = '20615446565'


def main():
    db = SessionLocal()
    try:
        ruc = {e.id: e.ruc for e in db.query(Emisor).all()}

        subs = db.query(Suscripcion).order_by(Suscripcion.creado_en).all()
        print("=" * 100)
        print(f"TODAS LAS SUSCRIPCIONES: {len(subs)}")
        print("=" * 100)
        for s in subs:
            print(f"  id={s.id}")
            print(f"     cliente(emisor_id)={ruc.get(s.emisor_id,'?')}  plan={s.plan}/{s.periodicidad}  monto={s.monto}")
            print(f"     estado={s.estado}  factura_estado={s.factura_estado}  factura_id={s.factura_id}  factura_numero={s.factura_numero}")
            print(f"     pagook_pago_id={s.pagook_pago_id}  pagook_nivel={s.pagook_nivel}  creado={s.creado_en}")
            print(f"     notas={s.notas}")
        if not subs:
            print("  (ninguna fila — se revirtió todo, o nunca se creó)")

        print("\n" + "=" * 100)
        print("COMPROBANTES SERIE FF50 (facturas de suscripción de PSP)")
        print("=" * 100)
        ff = db.query(Comprobante).filter(Comprobante.serie == 'FF50').order_by(Comprobante.numero).all()
        for c in ff:
            emi = ruc.get(c.emisor_id, '?')
            auto = ' ⚠️ AUTOFACTURA (emisor==adquirente)' if emi == (c.cliente_numero_documento or '') else ''
            print(f"  {c.serie}-{c.numero}  emisor={emi}  adquirente={c.cliente_numero_documento}  "
                  f"estado={c.estado}  creado={c.creado_en}{auto}")
        if not ff:
            print("  (ninguna FF50 — no se emitió comprobante de suscripción)")

        print("\n" + "=" * 100)
        print("EMISOR PSP — banderas (para ver si _activar lo tocó por autofactura)")
        print("=" * 100)
        psp = db.query(Emisor).filter(Emisor.ruc == RUC_PSP).first()
        if psp:
            print(f"  {psp.ruc} — {psp.razon_social}")
            print(f"  modo_test={psp.modo_test}  plan={psp.plan}  produccion={psp.produccion}")
            print("  (si plan='pagado' o modo_test=False por esta prueba, _activar actuó sobre PSP")
            print("   al haberse usado el RUC de PSP como adquirente → confirmar el bug de autofactura)")
    finally:
        db.close()


if __name__ == '__main__':
    main()
