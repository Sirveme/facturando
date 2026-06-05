"""
Cliente REST para envío y consulta de Guías de Remisión Electrónica (GRE, tipo 09)
contra la API REST de SUNAT (canal distinto al SOAP).

Flujo:
  1. enviar_gre(emisor, nombre_archivo, zip_bytes) -> num_ticket
  2. consultar_ticket(emisor, num_ticket) -> {estado, cod_respuesta, cdr_zip_bytes, errores}

Usa Bearer token de gre_auth.get_gre_token(). Reintenta una vez ante 401.
No se loguea client_secret ni password.
"""

import base64
import hashlib
import logging
import os

import requests

from src.core.config import settings
from src.services.gre_auth import get_gre_token

logger = logging.getLogger(__name__)

# Host base de la API REST GRE (gem = guías electrónicas de movilización).
# Override sin tocar código con la variable de entorno GRE_API_BASE.
# Default: api-cpe (el host api.sunat.gob.pe devolvía HTTP 404).
GRE_API_BASE = os.environ.get(
    "GRE_API_BASE", "https://api-cpe.sunat.gob.pe/v1/contribuyente/gem"
).rstrip("/")

SUNAT_GRE_ENVIO_URL = GRE_API_BASE + "/comprobantes/{nombreArchivo}"
SUNAT_GRE_TICKET_URL = GRE_API_BASE + "/comprobantes/envios/{numTicket}"


def _post_envio(token: str, nombre_archivo: str, body: dict) -> requests.Response:
    # El path lleva el nombre del archivo SIN la extensión .zip (incluirla da HTTP 404).
    # El body (nomArchivo) sí conserva el .zip; aquí solo se ajusta la URL.
    nombre_path = (
        nombre_archivo[:-4] if nombre_archivo.lower().endswith(".zip") else nombre_archivo
    )
    url = SUNAT_GRE_ENVIO_URL.format(nombreArchivo=nombre_path)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    logger.warning("[GRE_CLIENT] POST %s", url)
    return requests.post(url, json=body, headers=headers,
                         timeout=settings.sunat_timeout)


def enviar_gre(emisor, nombre_archivo: str, zip_bytes: bytes) -> str:
    """Envía una GRE firmada (ZIP) a SUNAT y devuelve el numTicket.

    Args:
        emisor: instancia Emisor (con credenciales GRE).
        nombre_archivo: nombre del ZIP, p.ej. '20615446565-09-T060-1.zip'.
        zip_bytes: contenido del ZIP (XML GRE firmado, comprimido).

    Returns:
        num_ticket (str).
    """
    hash_zip = hashlib.sha256(zip_bytes).hexdigest()
    arc_gre_zip = base64.b64encode(zip_bytes).decode("ascii")

    body = {
        "archivo": {
            "nomArchivo": nombre_archivo,
            "arcGreZip": arc_gre_zip,
            "hashZip": hash_zip,
        }
    }

    token = get_gre_token(emisor)
    resp = _post_envio(token, nombre_archivo, body)

    # Si el token expiró/invalidó: renovar una vez y reintentar.
    if resp.status_code == 401:
        logger.warning("[GRE_CLIENT] 401 en envío; renovando token y reintentando")
        token = get_gre_token(emisor, force_new=True)
        resp = _post_envio(token, nombre_archivo, body)

    if resp.status_code not in (200, 201):
        detalle = resp.text[:800]
        logger.error("[GRE_CLIENT] Envío HTTP %d: %s", resp.status_code, detalle)
        raise Exception(
            f"SUNAT GRE envío HTTP {resp.status_code} ({nombre_archivo}): {detalle}"
        )

    payload = resp.json()
    num_ticket = payload.get("numTicket")
    if not num_ticket:
        raise Exception(
            f"Respuesta de envío GRE sin numTicket ({nombre_archivo}): {payload}"
        )

    logger.info("[GRE_CLIENT] GRE %s enviada, numTicket=%s", nombre_archivo, num_ticket)
    return num_ticket


def _get_ticket(token: str, num_ticket: str) -> requests.Response:
    url = SUNAT_GRE_TICKET_URL.format(numTicket=num_ticket)
    headers = {"Authorization": f"Bearer {token}"}
    logger.warning("[GRE_CLIENT] GET %s", url)
    return requests.get(url, headers=headers, timeout=settings.sunat_timeout)


def consultar_ticket(emisor, num_ticket: str) -> dict:
    """Consulta el estado de un ticket de GRE.

    Returns:
        {
          "estado": "aceptado" | "en_proceso" | "rechazado",
          "cod_respuesta": str | None,   # 0=aceptado, 98=en proceso, 99=rechazado/error
          "cdr_zip_bytes": bytes | None, # CDR decodificado de base64 si está presente
          "errores": list | str | None,
        }
    """
    token = get_gre_token(emisor)
    resp = _get_ticket(token, num_ticket)

    if resp.status_code == 401:
        logger.warning("[GRE_CLIENT] 401 en consulta; renovando token y reintentando")
        token = get_gre_token(emisor, force_new=True)
        resp = _get_ticket(token, num_ticket)

    if resp.status_code != 200:
        detalle = resp.text[:800]
        logger.error("[GRE_CLIENT] Consulta HTTP %d: %s", resp.status_code, detalle)
        raise Exception(
            f"SUNAT GRE consulta HTTP {resp.status_code} (ticket {num_ticket}): {detalle}"
        )

    payload = resp.json()
    cod = payload.get("codRespuesta")

    estado_map = {"0": "aceptado", "98": "en_proceso", "99": "rechazado"}
    estado = estado_map.get(str(cod) if cod is not None else "", "desconocido")

    cdr_zip_bytes = None
    arc_cdr = payload.get("arcCdr")
    if arc_cdr:
        try:
            cdr_zip_bytes = base64.b64decode(arc_cdr)
        except Exception as e:
            logger.error("[GRE_CLIENT] No se pudo decodificar arcCdr: %s", e)

    errores = payload.get("error") or payload.get("errores")

    logger.info("[GRE_CLIENT] Ticket %s: codRespuesta=%s estado=%s",
                num_ticket, cod, estado)

    return {
        "estado": estado,
        "cod_respuesta": str(cod) if cod is not None else None,
        "cdr_zip_bytes": cdr_zip_bytes,
        "errores": errores,
    }
