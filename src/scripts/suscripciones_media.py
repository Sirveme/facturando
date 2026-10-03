#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suscripciones_media.py — Gestión de suscripciones en revisión manual (nivel 'media').

LISTAR (default):
    python -m src.scripts.suscripciones_media

CONFIRMAR una (elegir el candidato correcto de PagoOK):
    python -m src.scripts.suscripciones_media --confirmar <suscripcion_id> --pago <pago_id>
    → marca_usado(pago_id) y, si 200, activa la suscripción + emite la factura FF50.
"""
import os
import sys

import certifi
_CA = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = _CA
os.environ['SSL_CERT_FILE'] = _CA
os.environ['CURL_CA_BUNDLE'] = _CA

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Suscripcion
from src.services import pagook_client, suscripcion_service as SS


def _arg(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else None


def main():
    db = SessionLocal()
    try:
        susc_id = _arg('--confirmar')
        pago_id = _arg('--pago')

        if not susc_id:
            filas = db.query(Suscripcion).filter(Suscripcion.estado == 'media').order_by(Suscripcion.creado_en).all()
            print("=" * 90)
            print(f"SUSCRIPCIONES EN REVISIÓN MANUAL (media): {len(filas)}")
            print("=" * 90)
            for s in filas:
                cli = db.query(Emisor).filter(Emisor.id == s.emisor_id).first()
                print(f"  id={s.id}")
                print(f"     cliente: {cli.ruc if cli else '?'} — {cli.razon_social if cli else '?'}")
                print(f"     plan={s.plan}/{s.periodicidad}  monto={s.monto}  creado={s.creado_en}")
                print(f"     {s.notas or ''}")
                print(f"     → confirmar: python -m src.scripts.suscripciones_media --confirmar {s.id} --pago <pago_id>")
            if not filas:
                print("  (ninguna)")
            return

        # ── CONFIRMAR ──
        if not pago_id:
            print("🛑 Falta --pago <pago_id>"); return
        s = db.query(Suscripcion).filter(Suscripcion.id == susc_id).first()
        if not s:
            print(f"🛑 No existe suscripción {susc_id}"); return
        if s.estado != 'media':
            print(f"🛑 La suscripción no está en 'media' (estado={s.estado})"); return
        cli = db.query(Emisor).filter(Emisor.id == s.emisor_id).first()

        print(f"Confirmando {s.id} con pago_id={pago_id} (cliente {cli.ruc})...")
        u = pagook_client.marcar_usado(int(pago_id), referencia_externa=s.id)
        print(f"  marcar_usado → status {u['status']}")
        if u['status'] != 200:
            print("  ⚠️ No se pudo marcar el pago (409=ya usado / 404=no existe). No se activó nada.")
            return

        s.pagook_pago_id = int(pago_id)
        s.pagook_nivel = 'media-confirmada'
        s.referencia_externa = s.id
        SS._activar(cli, s)
        try:
            f = SS._emitir_factura_psp(db, cli, s)
            s.factura_id = f.id; s.factura_numero = f.numero_formato; s.factura_estado = f.estado
            print(f"  ✅ Activada + factura {s.factura_numero} ({s.factura_estado})")
        except Exception as e:
            s.factura_estado = 'error_emision'
            s.notas = (s.notas or '') + f" | emision_fallo: {e}"
            print(f"  ⚠️ Activada, pero la emisión falló: {e} (resolver con suscripciones_facturas --reintentar)")
        db.commit()
    finally:
        db.close()


if __name__ == '__main__':
    main()
