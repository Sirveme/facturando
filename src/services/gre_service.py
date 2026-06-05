"""
Orquestación de emisión de Guía de Remisión Electrónica Remitente (GRE, tipo 09).

Flujo síncrono (la GRE necesita el CDR antes del traslado; el usuario espera la
respuesta). El servicio está estructurado para poder envolverse en una task
Celery más adelante sin reescribirlo (todas las funciones reciben `db`).

Reutiliza:
  - asignar_numero_gre  → mismo patrón anti-race de Comprobante (max+1 por serie)
                          usando emisor.gre_correlativo + UNIQUE(emisor, serie, numero)
  - firmar_y_empaquetar_gre (gre_packaging)
  - enviar_gre / consultar_ticket (gre_client)
"""

import time
import zipfile
import logging
from io import BytesIO
from datetime import datetime, timezone, timedelta

import requests
from lxml import etree
from sqlalchemy.exc import IntegrityError
from cryptography.fernet import Fernet

from src.core.config import settings
from src.models.models import Emisor, Certificado, GuiaRemision
from src.services.gre_packaging import firmar_y_empaquetar_gre
from src.services.gre_client import enviar_gre, consultar_ticket
from src.services.pdf_generator_gre import generar_pdf_gre

logger = logging.getLogger(__name__)

# Hora de Perú (America/Lima = UTC-5, sin DST)
PERU_TZ = timezone(timedelta(hours=-5))

# Polling de ticket: intentos a 2s, 5s, 10s, 20s (máx 4)
POLL_INTERVALS = (2, 5, 10, 20)


def peru_now() -> datetime:
    """Datetime actual en hora de Perú (naive, igual que Comprobante)."""
    return datetime.now(tz=PERU_TZ).replace(tzinfo=None)


def _emisor_dict(emisor: Emisor) -> dict:
    return {
        "ruc": emisor.ruc,
        "razon_social": emisor.razon_social,
        "nombre_comercial": getattr(emisor, "nombre_comercial", "") or emisor.razon_social,
    }


# =====================================================================
# FASE 1 — Asignación de correlativo
# =====================================================================

def asignar_numero_gre(db, emisor: Emisor) -> tuple[str, int]:
    """Asigna serie y número correlativo a una GRE.

    Mismo patrón anti-race que Comprobante: expire_all() + max(numero) por
    (emisor, serie) + 1. Se siembra con emisor.gre_correlativo cuando aún no
    hay guías de esa serie, y se mantiene gre_correlativo en sync. El
    UNIQUE(emisor_id, serie, numero) es el respaldo final ante carreras.
    """
    db.expire_all()
    serie = emisor.gre_serie or "T060"

    ultimo = (
        db.query(GuiaRemision)
        .filter(GuiaRemision.emisor_id == emisor.id, GuiaRemision.serie == serie)
        .order_by(GuiaRemision.numero.desc())
        .first()
    )
    base = ultimo.numero if (ultimo and ultimo.numero) else (emisor.gre_correlativo or 0)
    numero = base + 1

    emisor.gre_correlativo = numero  # mantener el contador en sync
    return serie, numero


# =====================================================================
# CDR
# =====================================================================

def _parse_cdr_gre(cdr_zip_bytes: bytes) -> dict:
    """Extrae ResponseCode, Description y Notes (observaciones) del CDR.

    Returns: {"codigo": str|None, "descripcion": str|None, "notas": [str, ...]}
    """
    out = {"codigo": None, "descripcion": None, "notas": []}
    if not cdr_zip_bytes:
        return out
    try:
        with zipfile.ZipFile(BytesIO(cdr_zip_bytes)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            cdr_xml = zf.read(xml_names[0] if xml_names else zf.namelist()[0])
        doc = etree.fromstring(cdr_xml)

        def _first(name):
            els = doc.xpath(".//*[local-name()='%s']" % name)
            return els[0].text.strip() if els and els[0].text else None

        out["codigo"] = _first("ResponseCode")
        out["descripcion"] = _first("Description")
        notas = doc.xpath(".//*[local-name()='Note']")
        out["notas"] = [n.text.strip() for n in notas if n.text and n.text.strip()]
    except Exception as e:
        logger.warning("[GRE_SVC] No se pudo parsear CDR: %s", e)
    return out


def _generar_y_guardar_pdf(db, guia: GuiaRemision) -> None:
    """Genera la representación impresa (A4 + QR) y la cachea en guia.pdf.
    No-fatal: un error de PDF no debe revertir la aceptación de la guía."""
    try:
        guia.pdf = generar_pdf_gre(db, guia.id)
        db.commit()
        logger.info("[GRE_SVC] PDF generado para guía %s (%d bytes)", guia.id, len(guia.pdf or b""))
    except Exception as e:
        db.rollback()
        logger.exception("[GRE_SVC] No se pudo generar el PDF de la guía %s: %s", guia.id, e)


def _descontar_stock_no_fatal(db, guia: GuiaRemision) -> None:
    """Descuenta stock por la GRE aceptada (solo si no está vinculada a factura).
    No-fatal: un error de stock no debe afectar la emisión."""
    try:
        from src.services.stock_service import descontar_por_guia
        descontar_por_guia(db, guia.id)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("[GRE_SVC] Descuento de stock no-fatal falló para guía %s: %s", guia.id, e)


def _aplicar_resultado_ticket(db, guia: GuiaRemision, resultado: dict) -> bool:
    """Aplica a la guía el resultado de consultar_ticket. Devuelve True si el
    ticket quedó resuelto (aceptado/observado/rechazado), False si sigue en proceso."""
    cod = resultado.get("cod_respuesta")
    cdr_zip = resultado.get("cdr_zip_bytes")

    if cod == "0":
        guia.cdr_zip = cdr_zip
        cdr = _parse_cdr_gre(cdr_zip)
        guia.cdr_codigo = cdr.get("codigo") or "0"
        if cdr.get("notas"):
            guia.estado = "aceptado_observado"
            obs = "; ".join(cdr["notas"])
            guia.cdr_descripcion = f"{cdr.get('descripcion') or 'Aceptado'} | Observaciones: {obs}"
        else:
            guia.estado = "aceptado"
            guia.cdr_descripcion = cdr.get("descripcion") or "Aceptado por SUNAT"
        db.commit()
        logger.info("[GRE_SVC] Guía %s %s (cdr=%s)", guia.id, guia.estado, guia.cdr_codigo)
        _generar_y_guardar_pdf(db, guia)
        _descontar_stock_no_fatal(db, guia)
        return True

    if cod == "99":
        guia.estado = "rechazado"
        guia.cdr_zip = cdr_zip
        cdr = _parse_cdr_gre(cdr_zip)
        detalle = resultado.get("errores")
        guia.cdr_codigo = cdr.get("codigo")
        guia.cdr_descripcion = (
            cdr.get("descripcion")
            or (str(detalle) if detalle else "Rechazado por SUNAT")
        )
        db.commit()
        logger.info("[GRE_SVC] Guía %s RECHAZADA (cdr=%s): %s",
                    guia.id, guia.cdr_codigo, guia.cdr_descripcion)
        return True

    # cod == "98" o desconocido → sigue en proceso
    return False


# =====================================================================
# FASE 2 — Orquestación
# =====================================================================

def _cargar_certificado(db, emisor: Emisor) -> tuple[bytes, str]:
    """Carga y descifra el PFX + contraseña del emisor (patrón facturas)."""
    certificado = (
        db.query(Certificado)
        .filter_by(emisor_id=emisor.id, activo=True)
        .order_by(Certificado.creado_en.desc())
        .first()
    )
    if not certificado:
        raise ValueError(f"Emisor {emisor.ruc} sin certificado activo")

    f = Fernet(settings.encryption_key.encode())
    pfx_bytes = f.decrypt(
        certificado.pfx_encriptado.encode()
        if isinstance(certificado.pfx_encriptado, str)
        else certificado.pfx_encriptado
    )
    password = f.decrypt(
        certificado.password_encriptado.encode()
        if isinstance(certificado.password_encriptado, str)
        else certificado.password_encriptado
    ).decode()
    return pfx_bytes, password


def emitir_guia(db, guia_id: str) -> dict:
    """Emite una GRE de punta a punta (asignar nº → firmar → enviar → polling CDR).

    Returns un dict con el estado final y datos relevantes.
    """
    guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
    if not guia:
        return {"exito": False, "error": "Guía no encontrada"}

    # 1. Validar estado de entrada
    if guia.num_ticket and guia.estado == "enviado":
        # Ya enviada: ir directo a polling/consulta
        logger.info("[GRE_SVC] Guía %s ya enviada (ticket=%s), consultando", guia_id, guia.num_ticket)
        return _emitir_paso_polling(db, guia)

    if guia.estado not in ("pendiente", "error"):
        return {"exito": False, "error": f"Guía en estado '{guia.estado}', no emitible"}

    emisor = db.query(Emisor).filter(Emisor.id == guia.emisor_id).first()
    if not emisor:
        guia.estado = "error"
        guia.cdr_descripcion = "Emisor no encontrado"
        db.commit()
        return {"exito": False, "error": "Emisor no encontrado"}

    # 2. Asignar correlativo si numero es NULL
    if guia.numero is None:
        serie, numero = asignar_numero_gre(db, emisor)
        guia.serie = serie
        guia.numero = numero
    if not guia.fecha_emision:
        guia.fecha_emision = peru_now().date()

    # 3. Generar XML + firmar + empaquetar
    try:
        pfx_bytes, password = _cargar_certificado(db, emisor)
        paquete = firmar_y_empaquetar_gre(guia, _emisor_dict(emisor), pfx_bytes, password)
        guia.xml_firmado = paquete["signed_xml"]
        guia.hash_cpe = paquete["digest_value"]
        db.commit()  # consume el correlativo solo al confirmar el envío
    except IntegrityError:
        # Colisión de correlativo (carrera) → reintentar una vez con número nuevo
        db.rollback()
        logger.warning("[GRE_SVC] Colisión de correlativo para guía %s, reintentando", guia_id)
        guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
        serie, numero = asignar_numero_gre(db, emisor)
        guia.serie, guia.numero = serie, numero
        pfx_bytes, password = _cargar_certificado(db, emisor)
        paquete = firmar_y_empaquetar_gre(guia, _emisor_dict(emisor), pfx_bytes, password)
        guia.xml_firmado = paquete["signed_xml"]
        guia.hash_cpe = paquete["digest_value"]
        db.commit()
    except Exception as e:
        db.rollback()
        guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
        guia.estado = "error"
        guia.cdr_descripcion = f"Error generando/firmando XML: {e}"
        db.commit()
        logger.exception("[GRE_SVC] Error XML/firma guía %s", guia_id)
        return {"exito": False, "error": str(e), "estado": "error"}

    # 4. Enviar a SUNAT
    zip_name = paquete["zip_name"]
    try:
        num_ticket = enviar_gre(emisor, zip_name, paquete["zip_bytes"])
        guia.num_ticket = num_ticket
        guia.estado = "enviado"
        db.commit()
        logger.info("[GRE_SVC] Guía %s enviada, ticket=%s", guia_id, num_ticket)
    except requests.exceptions.RequestException as e:
        # Timeout/conexión → reintentable
        guia.estado = "error"
        guia.cdr_descripcion = f"Error de conexión al enviar: {e}"
        db.commit()
        logger.exception("[GRE_SVC] Conexión al enviar guía %s", guia_id)
        return {"exito": False, "error": str(e), "estado": "error"}
    except Exception as e:
        # HTTP sin evaluación del XML (404, 5xx, etc.) → transporte, reintentable.
        # 'rechazado' se reserva para CDR codRespuesta=99 (ver _aplicar_resultado_ticket).
        guia.estado = "error"
        guia.cdr_descripcion = f"Error de transporte al enviar: {e}"
        db.commit()
        logger.error("[GRE_SVC] Error de transporte al enviar guía %s: %s", guia_id, e)
        return {"exito": False, "error": str(e), "estado": "error"}

    # 5. Polling del ticket
    return _emitir_paso_polling(db, guia)


def _emitir_paso_polling(db, guia: GuiaRemision) -> dict:
    """Paso 5: polling del ticket con intentos a 2s, 5s, 10s, 20s (máx 4)."""
    emisor = db.query(Emisor).filter(Emisor.id == guia.emisor_id).first()

    for intento, espera in enumerate(POLL_INTERVALS, start=1):
        time.sleep(espera)
        try:
            resultado = consultar_ticket(emisor, guia.num_ticket)
        except requests.exceptions.RequestException as e:
            logger.warning("[GRE_SVC] Conexión en consulta ticket %s (intento %d): %s",
                            guia.num_ticket, intento, e)
            continue
        except Exception as e:
            # HTTP sin evaluación del XML en la consulta → transporte, reintentable.
            logger.error("[GRE_SVC] Error de transporte consultando ticket %s: %s",
                         guia.num_ticket, e)
            guia.estado = "error"
            guia.cdr_descripcion = f"Error de transporte al consultar ticket: {e}"
            db.commit()
            return _resumen(guia, exito=False)

        logger.info("[GRE_SVC] Ticket %s intento %d → cod=%s",
                    guia.num_ticket, intento, resultado.get("cod_respuesta"))

        if _aplicar_resultado_ticket(db, guia, resultado):
            return _resumen(guia, exito=guia.estado in ("aceptado", "aceptado_observado"))

    # Sigue en proceso tras 4 intentos → queda 'enviado' (consulta posterior)
    logger.info("[GRE_SVC] Ticket %s sigue en proceso; queda 'enviado'", guia.num_ticket)
    return _resumen(guia, exito=True, pendiente=True)


def consultar_estado_guia(db, guia_id: str) -> dict:
    """FASE 2.6 — Re-consulta el ticket de una guía que quedó en 'enviado'."""
    guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
    if not guia:
        return {"exito": False, "error": "Guía no encontrada"}
    if guia.estado != "enviado" or not guia.num_ticket:
        return _resumen(guia, exito=guia.estado in ("aceptado", "aceptado_observado"))

    emisor = db.query(Emisor).filter(Emisor.id == guia.emisor_id).first()
    try:
        resultado = consultar_ticket(emisor, guia.num_ticket)
    except requests.exceptions.RequestException as e:
        logger.warning("[GRE_SVC] Conexión en consulta_estado %s: %s", guia_id, e)
        return _resumen(guia, exito=True, pendiente=True)

    resuelto = _aplicar_resultado_ticket(db, guia, resultado)
    return _resumen(guia, exito=guia.estado in ("aceptado", "aceptado_observado"),
                    pendiente=not resuelto)


def _resumen(guia: GuiaRemision, exito: bool, pendiente: bool = False) -> dict:
    return {
        "exito": exito,
        "pendiente": pendiente,
        "guia_id": guia.id,
        "serie": guia.serie,
        "numero": guia.numero,
        "num_ticket": guia.num_ticket,
        "estado": guia.estado,
        "cdr_codigo": guia.cdr_codigo,
        "cdr_descripcion": guia.cdr_descripcion,
        "hash_cpe": guia.hash_cpe,
    }
