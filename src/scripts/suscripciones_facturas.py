#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suscripciones_facturas.py — Suscripciones ACTIVAS cuya factura NO está aceptada
(caso borde: pago confirmado pero la emisión quedó pendiente/fallida/rechazada).

LISTAR (default): refresca factura_estado desde el comprobante y muestra las que
no están aceptadas:
    python -m src.scripts.suscripciones_facturas

REINTENTAR la emisión de una:
    python -m src.scripts.suscripciones_facturas --reintentar <suscripcion_id>
    - error_emision / sin factura → crea la factura FF50 de nuevo y la encola.
    - pendiente/enviando/rechazado → re-encola el envío de la factura existente.
"""
import os
import sys

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante, Suscripcion
from src.api.referencias_ui import COMP_ACEPTADOS
from src.services import suscripcion_service as SS


def _arg(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else None


def _refrescar(db, s):
    """Sincroniza s.factura_estado con el estado real del comprobante."""
    if s.factura_id:
        comp = db.query(Comprobante).filter(Comprobante.id == s.factura_id).first()
        if comp and s.factura_estado != comp.estado:
            s.factura_estado = comp.estado
            return comp
        return comp
    return None


def main():
    db = SessionLocal()
    try:
        susc_id = _arg('--reintentar')

        if not susc_id:
            activas = db.query(Suscripcion).filter(Suscripcion.estado == 'activa').all()
            pendientes = []
            for s in activas:
                _refrescar(db, s)
                if (not s.factura_id) or (s.factura_estado not in COMP_ACEPTADOS):
                    pendientes.append(s)
            db.commit()
            print("=" * 90)
            print(f"SUSCRIPCIONES ACTIVAS CON FACTURA NO ACEPTADA: {len(pendientes)}")
            print("=" * 90)
            for s in pendientes:
                cli = db.query(Emisor).filter(Emisor.id == s.emisor_id).first()
                print(f"  id={s.id}  cliente={cli.ruc if cli else '?'}  "
                      f"factura={s.factura_numero or '(no emitida)'}  factura_estado={s.factura_estado or '—'}")
                print(f"     → reintentar: python -m src.scripts.suscripciones_facturas --reintentar {s.id}")
            if not pendientes:
                print("  (ninguna — todas las facturas de suscripción están aceptadas)")
            return

        # ── REINTENTAR ──
        s = db.query(Suscripcion).filter(Suscripcion.id == susc_id).first()
        if not s:
            print(f"🛑 No existe suscripción {susc_id}"); return
        cli = db.query(Emisor).filter(Emisor.id == s.emisor_id).first()
        comp = _refrescar(db, s); db.commit()

        if (not s.factura_id) or s.factura_estado == 'error_emision':
            print(f"Re-emitiendo factura para {s.id} (no había factura válida)...")
            try:
                f = SS._emitir_factura_psp(db, cli, s)
                s.factura_id = f.id; s.factura_numero = f.numero_formato; s.factura_estado = f.estado
                db.commit()
                print(f"  ✅ Emitida {s.factura_numero} ({s.factura_estado})")
            except Exception as e:
                db.rollback()
                print(f"  🛑 Falló la re-emisión: {e}")
        elif s.factura_estado in COMP_ACEPTADOS:
            print(f"  ✔ La factura {s.factura_numero} ya está ACEPTADA; nada que reintentar.")
        else:
            print(f"Re-encolando envío de {s.factura_numero} (estado {s.factura_estado})...")
            try:
                from src.tasks.celery_app import celery_app
                celery_app.send_task('enviar_comprobante_sunat', args=[s.factura_id])
                if comp:
                    comp.estado = 'enviando'; s.factura_estado = 'enviando'
                db.commit()
                print("  ✅ Re-encolada; revisa el estado en unos minutos.")
            except Exception as e:
                print(f"  🛑 No se pudo re-encolar: {e}")
    finally:
        db.close()


if __name__ == '__main__':
    main()
