"""
src/services/suscripcion_service.py — Motor de cobro de suscripciones de Facturalo.

Orquesta: PagoOK (consultar + marcar-usado) → activación de la suscripción →
emisión de la factura de suscripción de PSP (EXONERADA, Amazonía, afectación '20').

ORDEN SEGURO (dinero): consultar → crear suscripción 'pendiente' → marcar_usado →
SOLO si 200: activar + emitir. **Nunca** se activa antes de marcar_usado.

Barreras anti-doble-cobro:
  1. Idempotencia a nivel app: si el pago_id ya tiene suscripción viva → 'ya_procesado'.
  2. UNIQUE(pagook_pago_id) en Postgres (índice parcial) → IntegrityError manejado.
  3. marcar_usado de PagoOK (UNIQUE(pago_id) remoto) → 409 si otro lo usó.

CASO BORDE: si marcar_usado=200 y la EMISIÓN falla, la suscripción queda 'activa'
con factura_estado='error_emision' (el cliente pagó y está activo; la factura
queda listada para resolver). No se cae todo.

CONSUME el pipeline de emisión (crea filas + encola 'enviar_comprobante_sunat');
NO modifica xml_generator/envio_sunat/tasks/firma.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from src.models.models import Emisor, Comprobante, LineaDetalle, Suscripcion
from src.services import pagook_client

logger = logging.getLogger(__name__)

RUC_PSP = '20615446565'
SERIE_SUSCRIPCION = 'FF50'          # serie dedicada de PSP para Facturalo (nueva, ≠ F050)
DIAS = {'mensual': 30, 'anual': 365}
PLANES = {
    'emprendedor': {'mensual': Decimal('29.00'), 'anual': Decimal('290.00')},
    'negocio':     {'mensual': Decimal('55.00'), 'anual': Decimal('550.00')},
    # ⚠️ TEMPORAL — plan de prueba S/4 para la prueba de fuego (quitar después).
    'prueba':      {'mensual': Decimal('4.00'),  'anual': Decimal('4.00')},
}


def monto_plan(plan, periodicidad) -> Decimal:
    try:
        return PLANES[plan][periodicidad]
    except KeyError:
        raise ValueError(f"Plan/periodicidad inválidos: {plan}/{periodicidad}")


def _siguiente_numero(db, emisor_id, serie, tipo='01') -> int:
    """Correlativo por (emisor, serie, tipo). FF50 arranca en 1, sin chocar con F050."""
    m = db.query(func.max(Comprobante.numero)).filter(
        Comprobante.emisor_id == emisor_id, Comprobante.serie == serie,
        Comprobante.tipo_documento == tipo).scalar()
    return (m + 1) if m else 1


def _emitir_factura_psp(db, cliente, s) -> Comprobante:
    """Factura de suscripción: PSP emisor, adquirente = cliente, EXONERADA (afectación
    '20'). Crea Comprobante + LineaDetalle y encola el envío (reusa el pipeline)."""
    psp = db.query(Emisor).filter(Emisor.ruc == RUC_PSP).first()
    if not psp:
        raise RuntimeError(f"Emisor PSP {RUC_PSP} no existe")

    numero = _siguiente_numero(db, psp.id, SERIE_SUSCRIPCION, '01')
    monto = Decimal(str(s.monto))
    desc = f"Suscripcion Facturalo - plan {s.plan} ({s.periodicidad})"

    comp = Comprobante(
        id=str(uuid4()), emisor_id=psp.id, tipo_documento='01',
        serie=SERIE_SUSCRIPCION, numero=numero,
        numero_formato=f"{SERIE_SUSCRIPCION}-{str(numero).zfill(8)}",
        fecha_emision=date.today(), moneda='PEN',
        cliente_tipo_documento='6', cliente_numero_documento=cliente.ruc,
        cliente_razon_social=cliente.razon_social,
        cliente_direccion=getattr(cliente, 'direccion', '') or '',
        monto_base=monto, monto_igv=Decimal('0.00'), monto_total=monto,
        op_gravada=Decimal('0.00'), op_exonerada=monto, op_inafecta=Decimal('0.00'),
        estado='pendiente',
    )
    db.add(comp)
    db.add(LineaDetalle(
        id=str(uuid4()), comprobante_id=comp.id, orden=1, descripcion=desc,
        cantidad=Decimal('1'), unidad='ZZ', precio_unitario=monto, monto_linea=monto,
        tipo_afectacion_igv='20', es_bonificacion=False,
    ))
    db.flush()

    # Encolar envío a SUNAT (task intocable). No-fatal: si no se puede, queda 'pendiente'
    # y el caso borde lo captura (factura_estado pendiente/fallido).
    try:
        from src.tasks.celery_app import celery_app
        celery_app.send_task('enviar_comprobante_sunat', args=[comp.id])
        comp.estado = 'enviando'
    except Exception as e:
        logger.warning("[SUSC] no se pudo encolar envío de %s: %s", comp.numero_formato, e)
    return comp


def _activar(cliente, s):
    """Activa la suscripción y la cuenta. SOLO se llama tras marcar_usado=200."""
    s.estado = 'activa'
    cliente.modo_test = False
    cliente.plan = 'pagado'


def procesar_confirmacion(db, *, cliente, plan, periodicidad, pagador=None,
                          fecha_hora=None, canal=None, codigo=None) -> dict:
    """Flujo "ya pagué". `cliente` es el emisor LOGUEADO (adquirente), resuelto de la
    sesión por el endpoint — nunca de un input. Devuelve dict con `nivel` para el front:
    alta | ya_procesado | media | voucher | error."""
    # (B) Guarda anti-autofactura: el emisor de la plataforma (PSP) no se suscribe a sí mismo.
    if cliente.ruc == RUC_PSP:
        return {"nivel": "error", "mensaje": "El emisor de la plataforma no puede suscribirse."}

    monto = monto_plan(plan, periodicidad)

    logger.warning("[DIAG][SUSC] ANTES de consultar PagoOK monto=%s fecha=%s canal=%s",
                   monto, fecha_hora, canal)
    res = pagook_client.consultar_pago(
        str(monto), fecha_hora, nombre_pagador_declarado=pagador, canal=canal, codigo_operacion=codigo)
    nivel = res.get("nivel")
    logger.warning("[DIAG][SUSC] DESPUES de consultar PagoOK → nivel=%s motivo=%s",
                   nivel, res.get("motivo"))

    # ── NIVEL ALTA ──────────────────────────────────────────────────────────
    if nivel == "alta":
        pago = res.get("pago") or {}
        pago_id = pago.get("pago_id")

        # (1) Idempotencia app: ¿este pago ya tiene una suscripción viva? → ya_procesado
        ya = db.query(Suscripcion).filter(
            Suscripcion.pagook_pago_id == pago_id,
            Suscripcion.estado.in_(['pendiente', 'activa', 'media'])).first()
        if ya:
            return {"nivel": "ya_procesado", "suscripcion_id": ya.id,
                    "factura_numero": ya.factura_numero, "factura_estado": ya.factura_estado,
                    "mensaje": "Tu pago ya fue procesado."}

        # Crear suscripción 'pendiente' ANTES de marcar_usado (orden seguro)
        vence = date.today() + timedelta(days=DIAS[periodicidad])
        s = Suscripcion(id=str(uuid4()), emisor_id=cliente.id, plan=plan, periodicidad=periodicidad,
                        monto=monto, moneda='PEN', vence=vence, estado='pendiente',
                        pagook_pago_id=pago_id, pagook_nivel='alta')
        s.referencia_externa = s.id
        db.add(s)
        try:
            db.flush()   # (2) 2da barrera: UNIQUE(pagook_pago_id) en Postgres
        except IntegrityError as e:
            db.rollback()
            # [DIAG] CLAVE: NO asumir "pago duplicado". Loguear el error REAL de la BD:
            # si es UNIQUE(pagook_pago_id) → sí es duplicado; si es NOT NULL / FK / tipo /
            # columna inexistente → es un DESAJUSTE DE ESQUEMA disfrazado de ya_procesado.
            logger.error("[DIAG][SUSC] IntegrityError en flush (pago_id=%s, emisor_id=%s): %r",
                         pago_id, cliente.id, getattr(e, "orig", e))
            return {"nivel": "ya_procesado", "mensaje": "Tu pago ya fue procesado."}

        # marcar_usado ANTES de activar
        u = pagook_client.marcar_usado(pago_id, referencia_externa=s.id)
        if u["status"] == 200:
            _activar(cliente, s)
            # CASO BORDE: si la emisión falla, la suscripción queda 'activa' igual.
            try:
                f = _emitir_factura_psp(db, cliente, s)
                s.factura_id = f.id
                s.factura_numero = f.numero_formato
                s.factura_estado = f.estado
            except Exception as e:
                s.factura_estado = 'error_emision'
                s.notas = (s.notas or '') + f" | emision_fallo: {e}"
                logger.error("[SUSC] activada pero EMISIÓN falló (susc=%s): %s", s.id, e)
            db.commit()
            return {"nivel": "alta", "suscripcion_id": s.id, "factura_numero": s.factura_numero,
                    "factura_estado": s.factura_estado, "mensaje": "Suscripción activada."}
        elif u["status"] == 409:
            s.estado = 'anulada'; s.notas = 'marcar_usado 409 (pago ya usado)'; db.commit()
            return {"nivel": "voucher", "mensaje": "Ese pago ya fue usado. Sube tu voucher."}
        else:  # 404 / red (status 0) → NO activar
            s.estado = 'anulada'; s.notas = f'marcar_usado status {u["status"]}'; db.commit()
            return {"nivel": "error",
                    "mensaje": "No se pudo confirmar el pago. Intenta de nuevo o sube tu voucher."}

    # ── NIVEL MEDIA (revisión manual de Duilio) ─────────────────────────────
    if nivel == "media":
        vence = date.today() + timedelta(days=DIAS[periodicidad])
        s = Suscripcion(id=str(uuid4()), emisor_id=cliente.id, plan=plan, periodicidad=periodicidad,
                        monto=monto, moneda='PEN', vence=vence, estado='media', pagook_nivel='media',
                        notas="candidatos: " + str([c.get('pago_id') for c in res.get('candidatos', [])]))
        db.add(s); db.commit()
        return {"nivel": "media", "suscripcion_id": s.id, "candidatos": res.get("candidatos", []),
                "mensaje": "Estamos revisando tu pago; te confirmamos a la brevedad."}

    # ── SIN_COINCIDENCIA / ERROR → voucher ──────────────────────────────────
    return {"nivel": "voucher", "mensaje": "No encontramos tu pago. Sube tu voucher."}
