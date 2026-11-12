#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emitir_control_psp.py — Factura de CONTROL de PSP post-deploy.

Emisor PSP (RUC 20615446565), serie F999, factura a SUNAT (RUC 20131312955),
1 ítem de S/ 1.00 EXONERADO (afectación 20, el perfil de PSP). Se envía a SUNAT
PASANDO POR EL TASK DESPLEGADO `enviar_comprobante_sunat`, para validar la
clasificación nueva (estado + código + observaciones) end-to-end.

DRY-RUN por defecto (muestra el XML, NO escribe BD, NO transmite).
Con --send crea el comprobante, lo envía por el task real y muestra el resultado guardado.

Reusa un F999 que nunca llegó a SUNAT si existe (no quema correlativo).

USO:
    python -m src.scripts.emitir_control_psp            # dry-run
    python -m src.scripts.emitir_control_psp --send     # emite de verdad
"""
import sys
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import func

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, LineaDetalle, RespuestaSunat
from src.services.xml_generator import build_invoice_xml
from src.tasks.envio_sunat import (
    enviar_comprobante_task, _build_comprobante_xml_obj, _build_emisor_dict,
)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

RUC_PSP   = '20615446565'
SERIE     = 'F999'
TIPO      = '01'                 # factura
CLI_TIPO  = '6'                  # RUC
CLI_NUM   = '20131312955'
CLI_RAZON = 'SUPERINTENDENCIA NACIONAL DE ADUANAS Y DE ADMINISTRACION TRIBUTARIA'
PRECIO    = Decimal('1.00')
AFECT     = '20'                 # exonerado (perfil PSP)
PERU_TZ   = timezone(timedelta(hours=-5))


def _siguiente_numero(db, emisor_id):
    m = db.query(func.max(Comprobante.numero)).filter(
        Comprobante.emisor_id == emisor_id, Comprobante.serie == SERIE,
        Comprobante.tipo_documento == TIPO).scalar()
    return (m + 1) if m else 1


def _reusable(db, emisor):
    cands = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id, Comprobante.serie == SERIE,
        Comprobante.tipo_documento == TIPO,
        Comprobante.estado.in_(['error', 'pendiente', 'enviando', 'rechazado']),
    ).order_by(Comprobante.numero.asc()).all()
    for c in cands:
        r = c.respuesta
        if not (r is not None and (r.codigo_cdr not in (None, ''))):
            return c
    return None


def _nueva_factura(db, emisor):
    numero = _siguiente_numero(db, emisor.id)
    base = PRECIO
    comp = Comprobante(
        id=str(uuid4()), emisor_id=emisor.id, tipo_documento=TIPO,
        serie=SERIE, numero=numero, numero_formato=f"{SERIE}-{numero:08d}",
        fecha_emision=datetime.now(PERU_TZ).date(), moneda='PEN', forma_pago='Contado',
        cliente_tipo_documento=CLI_TIPO, cliente_numero_documento=CLI_NUM,
        cliente_razon_social=CLI_RAZON, cliente_direccion='',
        monto_base=base, monto_igv=Decimal('0.00'), monto_total=base,
        op_gravada=Decimal('0.00'), op_exonerada=base, op_inafecta=Decimal('0.00'),
        estado='pendiente',
    )
    comp.lineas = [LineaDetalle(
        id=str(uuid4()), comprobante_id=comp.id, orden=1,
        descripcion='Servicio de control post-deploy', cantidad=Decimal('1'),
        unidad='NIU', precio_unitario=base, valor_unitario=base,
        subtotal=base, igv=Decimal('0.00'), monto_linea=base,
        tipo_afectacion_igv=AFECT, es_bonificacion=False,
    )]
    return comp


def main():
    send_mode = '--send' in sys.argv
    print("=" * 72)
    print("FACTURA DE CONTROL PSP → SUNAT  (F999, exonerada S/1.00, cliente RUC 20131312955)")
    print("MODO:", "🚨 ENVÍO REAL (task desplegado)" if send_mode else "🧪 DRY-RUN (sin BD, sin SUNAT)")
    print("=" * 72)

    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == RUC_PSP).first()
        if not emisor:
            print(f"🛑 No existe emisor PSP (RUC {RUC_PSP})."); sys.exit(1)
        print(f"[emisor] {emisor.ruc} — {emisor.razon_social}  produccion={getattr(emisor,'produccion',False)}")

        reuso = _reusable(db, emisor)
        comp = reuso or _nueva_factura(db, emisor)
        print(f"[{'reuso' if reuso else 'nueva'}] {comp.numero_formato}  "
              f"exonerado base={comp.monto_base} igv={comp.monto_igv} total={comp.monto_total}")

        if not send_mode:
            comp_xml = _build_comprobante_xml_obj(comp)
            xmlb = build_invoice_xml(comp_xml, _build_emisor_dict(emisor))
            print("\n--- XML que se enviaría (DRY-RUN) ---")
            print(xmlb.decode('utf-8', errors='replace'))
            print("--- fin XML ---")
            db.rollback()
            print("\n🧪 DRY-RUN completado. NADA en BD ni SUNAT.")
            print("   Envío real:  python -m src.scripts.emitir_control_psp --send")
            return

        # ENVÍO REAL vía el task desplegado (valida la clasificación nueva)
        if not reuso:
            db.add(comp)
            for ln in comp.lineas:
                db.add(ln)
        else:
            comp.estado = 'pendiente'
            comp.fecha_emision = datetime.now(PERU_TZ).date()
        db.commit()
        comp_id = comp.id
        print(f"\n➡️  Enviando {comp.numero_formato} por enviar_comprobante_sunat (síncrono)…")
        res = enviar_comprobante_task.run(comp_id)
        print(f"   return del task: {res}")

        # Releer resultado guardado
        db.expire_all()
        comp = db.query(Comprobante).filter(Comprobante.id == comp_id).first()
        resp = (db.query(RespuestaSunat)
                .filter(RespuestaSunat.comprobante_id == comp_id)
                .order_by(RespuestaSunat.recibido_en.desc()).first())
        print("\n" + "=" * 72)
        print(f"RESULTADO GUARDADO — {comp.numero_formato}")
        print(f"  estado         : {comp.estado}")
        print(f"  codigo_cdr     : {resp.codigo_cdr if resp else None}")
        print(f"  descripcion    : {(resp.descripcion if resp else '')[:90]}")
        print(f"  observaciones  : {resp.observaciones if resp else None}")
        print("=" * 72)
    finally:
        db.close()


if __name__ == '__main__':
    main()
