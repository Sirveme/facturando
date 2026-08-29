#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
referencia_nc.py — Resumen del documento que una Nota de Crédito/Débito anula o modifica.

SOLO PRESENTACIÓN. No cambia emisión, XML ni SOAP. Usado por:
  - el detalle del comprobante (dashboard, routes.get_comprobante_detalle)
  - el PDF (api/v1/pdf_generator) — vía resumen_referencia_autonomo (abre su propia
    sesión de solo lectura y la CIERRA siempre)

Fuente de los datos del documento referenciado: se busca el comprobante original por su
numero_formato (== doc_referencia_numero) dentro del mismo emisor. Si no se encuentra, se
usa como respaldo el cliente que la propia nota ya lleva y se marca original.encontrado=False.
"""
from datetime import timezone, timedelta

from src.models.models import Comprobante

# Catálogo 09 SUNAT — tipos de Nota de Crédito
MOTIVOS_NC = {
    '01': 'Anulación de la operación',
    '02': 'Anulación por error en el RUC',
    '03': 'Corrección por error en la descripción',
    '04': 'Descuento global',
    '05': 'Descuento por ítem',
    '06': 'Devolución total',
    '07': 'Devolución por ítem',
    '08': 'Bonificación',
    '09': 'Disminución en el valor',
    '10': 'Otros conceptos',
}

# Catálogo 10 SUNAT — tipos de Nota de Débito
MOTIVOS_ND = {
    '01': 'Intereses por mora',
    '02': 'Aumento en el valor',
    '03': 'Penalidades / otros conceptos',
}

TIPO_LABEL = {
    '01': 'Factura', '03': 'Boleta', '07': 'Nota de Crédito', '08': 'Nota de Débito', '12': 'Ticket',
}
CLIENTE_TIPO_LABEL = {'6': 'RUC', '1': 'DNI', '4': 'CE', '7': 'Pasaporte', '0': 'Doc'}

PERU_TZ = timezone(timedelta(hours=-5))


def motivo_texto(tipo_documento, codigo):
    """Texto del motivo. NC -> catálogo 09, ND -> catálogo 10. Fallback: 'Motivo [codigo]'."""
    codigo = str(codigo or '').strip()
    tabla = MOTIVOS_ND if str(tipo_documento or '') == '08' else MOTIVOS_NC
    if not codigo:
        return 'Motivo no especificado'
    return tabla.get(codigo, f'Motivo [{codigo}]')


def _hora_peru(creado_en):
    """HH:MM en hora Perú a partir de creado_en (DateTime UTC naive). None si no aplica."""
    if not creado_en or not hasattr(creado_en, 'strftime'):
        return None
    try:
        dt = creado_en
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(PERU_TZ).strftime('%H:%M')
    except Exception:
        return None


def resumen_referencia(db, comp):
    """Devuelve el resumen de referencia si `comp` es NC(07)/ND(08); si no, None.

    `db` puede ser None (sin acceso a BD): en ese caso original.encontrado=False y los datos
    del cliente salen de la propia nota.
    """
    tipo = str(getattr(comp, 'tipo_documento', '') or '')
    if tipo not in ('07', '08'):
        return None

    ref_num = getattr(comp, 'doc_referencia_numero', None)
    ref_tipo = str(getattr(comp, 'doc_referencia_tipo', '') or '')
    motivo_cod = str(getattr(comp, 'motivo_nota', '') or '')

    original = {
        'encontrado': False,
        'fecha': None, 'hora': None, 'monto': None, 'moneda': None,
        'cliente_tipo': getattr(comp, 'cliente_tipo_documento', None),
        'cliente_doc': getattr(comp, 'cliente_numero_documento', None),
        'cliente_nombre': getattr(comp, 'cliente_razon_social', None),
    }

    if db is not None and ref_num:
        try:
            orig = (db.query(Comprobante)
                    .filter(Comprobante.emisor_id == comp.emisor_id,
                            Comprobante.numero_formato == ref_num)
                    .first())
            if orig:
                original['encontrado'] = True
                original['fecha'] = orig.fecha_emision.strftime('%d/%m/%Y') if orig.fecha_emision else None
                original['hora'] = _hora_peru(getattr(orig, 'creado_en', None))
                original['monto'] = float(orig.monto_total or 0)
                original['moneda'] = orig.moneda or 'PEN'
                # Datos del cliente del documento original (más autoritativos que la copia)
                original['cliente_tipo'] = orig.cliente_tipo_documento or original['cliente_tipo']
                original['cliente_doc'] = orig.cliente_numero_documento or original['cliente_doc']
                original['cliente_nombre'] = orig.cliente_razon_social or original['cliente_nombre']
        except Exception:
            # No-fatal: se reporta como no localizado y se usan los datos de la nota.
            pass

    cli_tipo_lbl = CLIENTE_TIPO_LABEL.get(str(original['cliente_tipo'] or ''), 'Doc')

    return {
        'es_nota': True,
        'nota_label': TIPO_LABEL.get(tipo, 'Nota'),
        'verbo': 'anula' if tipo == '07' else 'modifica',
        'ref_tipo_label': TIPO_LABEL.get(ref_tipo, 'Documento'),
        'ref_numero': ref_num,
        'motivo_codigo': motivo_cod,
        'motivo_texto': motivo_texto(tipo, motivo_cod),
        'cliente_tipo_label': cli_tipo_lbl,
        'original': original,
    }


def resumen_referencia_autonomo(comp):
    """Como resumen_referencia, pero abre su PROPIA sesión de solo lectura y la CIERRA
    SIEMPRE (finally). Para usar donde no hay `db` a mano (ej. generación de PDF).
    Nunca fuga conexiones del pool: si algo falla, cae a la ruta sin BD."""
    tipo = str(getattr(comp, 'tipo_documento', '') or '')
    if tipo not in ('07', '08'):
        return None
    db = None
    try:
        from src.api.dependencies import SessionLocal
        db = SessionLocal()
        return resumen_referencia(db, comp)
    except Exception:
        return resumen_referencia(None, comp)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
