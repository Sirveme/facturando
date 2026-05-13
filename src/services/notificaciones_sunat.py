"""
Clasificación de errores SUNAT + notificaciones vía webhook a QueVendi.

- clasificar_error_sunat(codigo, mensaje) → 'temporal' | 'permanente' | 'desconocido'
- notificar_*(comp, emisor, ...): POST fire-and-forget al webhook QueVendi.

Variables de entorno:
- QUEVENDI_WEBHOOK_URL      (default: https://quevendi.pro/api/v1/webhooks/facturalo-alerta)
- FACTURALO_WEBHOOK_SECRET  (compartido con QueVendi)
"""
import os
import re
import logging
import httpx

logger = logging.getLogger(__name__)

QUEVENDI_WEBHOOK_URL = os.getenv(
    "QUEVENDI_WEBHOOK_URL",
    "https://quevendi.pro/api/v1/webhooks/facturalo-alerta",
)
FACTURALO_WEBHOOK_SECRET = os.getenv("FACTURALO_WEBHOOK_SECRET", "")
WEBHOOK_TIMEOUT_SECS = 10

# Códigos SUNAT que indican problema transitorio del servicio.
ERRORES_TEMPORALES_SUNAT = {
    '0109': 'Servicio de autenticación no disponible',
    '0111': 'Servicio temporalmente no disponible',
    '0113': 'Sistema en mantenimiento',
    '0151': 'Timeout / servicio no disponible',
    '0200': 'Error en el batch — servidor SUNAT',
    '98':   'Comprobante en proceso (ticket pendiente)',
}

# Códigos que requieren intervención manual: nunca se reintentan automáticamente.
ERRORES_PERMANENTES_SUNAT = {
    '0152': 'Usuario SOL no tiene permisos',
    '1033': 'XML inválido',
    '1034': 'Comprobante duplicado',
    '2800': 'RUC no habilitado para emisión electrónica',
    '3127': 'Serie no autorizada para este emisor',
}

# Palabras clave en el mensaje que sugieren transitorio (fallback sin código).
_KEYWORDS_TEMPORAL = (
    'no disponible',
    'no esta disponible',
    'no está disponible',
    'mantenimiento',
    'timeout',
    'tiempo de espera',
    'connection',
    'conexion',
    'conexión',
    'ioexception',
    'socket',
    '503',
    '504',
)


def _extraer_codigo(codigo_o_fault: str) -> str:
    """Normaliza un código SUNAT. Acepta '0109', 'soap-env:Client.0109', etc."""
    if not codigo_o_fault:
        return ''
    s = str(codigo_o_fault).strip()
    m = re.search(r'(\d{2,4})\s*$', s)
    return m.group(1) if m else s


def clasificar_error_sunat(codigo: str, mensaje: str = '') -> str:
    """Retorna 'temporal' | 'permanente' | 'desconocido'."""
    cod = _extraer_codigo(codigo)
    if cod and cod in ERRORES_TEMPORALES_SUNAT:
        return 'temporal'
    if cod and cod in ERRORES_PERMANENTES_SUNAT:
        return 'permanente'

    msg_lc = (mensaje or '').lower()
    if any(kw in msg_lc for kw in _KEYWORDS_TEMPORAL):
        return 'temporal'

    # Códigos 1xxx/2xxx/3xxx desconocidos: tratarlos como permanentes
    # para no reintentar errores de datos del cliente.
    if cod.isdigit() and cod[:1] in ('1', '2', '3'):
        return 'permanente'

    return 'desconocido'


def _post_webhook(payload: dict) -> None:
    """POST fire-and-forget al webhook QueVendi. Nunca propaga excepciones."""
    if not FACTURALO_WEBHOOK_SECRET:
        logger.warning("[notif] FACTURALO_WEBHOOK_SECRET no configurado — webhook omitido")
        return
    try:
        httpx.post(
            QUEVENDI_WEBHOOK_URL,
            json=payload,
            headers={"X-Webhook-Secret": FACTURALO_WEBHOOK_SECRET},
            timeout=WEBHOOK_TIMEOUT_SECS,
        )
    except Exception as e:
        logger.warning("[notif] webhook error: %s", e)


def _base_payload(comp, emisor) -> dict:
    return {
        "emisor_ruc": getattr(emisor, 'ruc', '') if emisor else '',
        "negocio": getattr(emisor, 'razon_social', 'Negocio') if emisor else 'Negocio',
        "serie": comp.serie,
        "numero": comp.numero,
        "monto": float(comp.monto_total or 0),
        "comprobante_id": str(comp.id),
    }


def notificar_reintento_temporal(comp, emisor, codigo, intento, max_intentos, minutos):
    """Avisa a Duilio que SUNAT está caído y se reintentará."""
    payload = _base_payload(comp, emisor) | {
        "tipo": "reintento_temporal",
        "error_codigo": codigo,
        "intento": intento,
        "max_intentos": max_intentos,
        "proxima_vez_minutos": minutos,
        "solo_duilio": True,
    }
    _post_webhook(payload)


def notificar_resuelto(comp, emisor):
    """Avisa que el comprobante fue aceptado tras reintentos."""
    payload = _base_payload(comp, emisor) | {
        "tipo": "resuelto_automatico",
        "intentos_totales": comp.intentos_envio or 0,
        "notificar_negocio": True,
    }
    _post_webhook(payload)


def notificar_fallo_definitivo(comp, emisor, tipo_error, codigo):
    """Avisa de un fallo que requiere atención manual."""
    payload = _base_payload(comp, emisor) | {
        "tipo": "fallo_definitivo",
        "tipo_error": tipo_error,
        "error_codigo": codigo,
        "intentos_totales": comp.intentos_envio or 0,
        "notificar_negocio": True,
        "requiere_atencion_manual": True,
    }
    _post_webhook(payload)
