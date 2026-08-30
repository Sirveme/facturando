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
# NOTA: 1033 ("registrado previamente") NO va aquí — significa que SUNAT YA lo tiene
# aceptado; se maneja como 'ya_aceptado' en clasificar_error_a2 (A2), no como rechazo.
ERRORES_PERMANENTES_SUNAT = {
    '0152': 'Usuario SOL no tiene permisos',
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
    'timed out',
    'tiempo de espera',
    'read timed out',
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


# =====================================================================
# A2 — Clasificación enriquecida + decisión de reintento (funciones PURAS,
# sin efectos secundarios ni BD, para poder testear cada rama).
# =====================================================================

CATEGORIAS_A2 = ('ya_aceptado', 'transitorio', 'perfil', 'contenido', 'desconocido')


def clasificar_error_a2(codigo, mensaje=''):
    """Clasifica un error/fault de SUNAT en una de CATEGORIAS_A2.

    - ya_aceptado : 1033 / "registrado previamente" → SUNAT ya lo tiene aceptado.
    - transitorio : timeout / 5xx / servicio no disponible / códigos de servicio (0109..).
    - perfil      : SOAP Fault de perfil/política (faultcode 'Client.01xx', 'Rejected by policy').
    - contenido   : 1xxx/2xxx/3xxx de datos (RUC, monto, estructura) → rechazo real.
    - desconocido : no clasificable → conservador (no reintentar).
    """
    raw = str(codigo or '').strip()
    cod = _extraer_codigo(raw)
    msg_lc = (mensaje or '').lower()

    # 1) Ya registrado/aceptado previamente
    if cod == '1033' or 'registrado previamente' in msg_lc or 'ya fue registrad' in msg_lc \
            or 'ya existe' in msg_lc or 'ya cuenta con' in msg_lc:
        return 'ya_aceptado'

    # 3) SOAP Fault de perfil/política: llega como faultcode "Client.xxxx" (A3).
    #    Se desambigua del código de servicio numérico (ej. 0111 real de servicio caído).
    if raw.lower().startswith('client.') or 'client.' in raw.lower():
        if cod.startswith('01') or 'perfil' in msg_lc or 'policy' in msg_lc \
                or 'permiso' in msg_lc or 'rejected by policy' in msg_lc:
            return 'perfil'
        return 'contenido'  # otros Client.xxxx → rechazo real

    # 2) Transitorio: códigos de servicio + keywords de red/servicio/5xx/timeout
    if cod in ERRORES_TEMPORALES_SUNAT:
        return 'transitorio'
    if any(kw in msg_lc for kw in _KEYWORDS_TEMPORAL):
        return 'transitorio'

    # 4) Contenido (RUC/monto/estructura): 1xxx/2xxx/3xxx → rechazo real, no reintentar
    if cod.isdigit() and cod[:1] in ('1', '2', '3'):
        return 'contenido'

    # 5) Conservador
    return 'desconocido'


def decidir_reintento(categoria, intentos, tiene_aceptados_previos=False, max_reintentos=3):
    """Decide la acción a partir de la categoría. PURA. `intentos` = intentos YA realizados.

    MODO CONSERVADOR (deploy actual, getStatusCdr PAUSADO): sin la red anti-duplicado, solo se
    reintenta lo claramente transitorio. Los faults ambiguos (perfil) NO se reintentan solos.
    `tiene_aceptados_previos` queda reservado para cuando se reactive la verificación por getStatusCdr.

    Retorna:
      'marcar_aceptado'   → 1033 'ya registrado' → marcar aceptado, NO reenviar (CDR real pendiente)
      'reintentar'        → reencolar con backoff (solo transitorios claros)
      'rechazar'          → rechazo real / agotados los reintentos
      'rechazar_perfil'   → fault de perfil/política → no auto-retry (verificar permisos SOL, manual)
      'rechazar_revision' → desconocido (marcar para revisión manual)
    """
    if categoria == 'ya_aceptado':
        return 'marcar_aceptado'
    if categoria == 'transitorio':
        return 'reintentar' if intentos < max_reintentos else 'rechazar'
    if categoria == 'perfil':
        return 'rechazar_perfil'   # sin getStatusCdr no se verifica → no reintentar solo
    if categoria == 'contenido':
        return 'rechazar'
    return 'rechazar_revision'  # desconocido


def gate_reenvio(estado_cdr, intentos):
    """GARANTÍA ANTI-DUPLICADO (pura). Decide si es seguro reenviar un comprobante.

    `estado_cdr`: resultado de getStatusCdr ('aceptado'|'rechazado'|'no_existe'|'incierto'|None).
    `intentos`  : intentos YA realizados.

    Regla de oro: a partir del 2º intento SOLO se reenvía si SUNAT confirma 'no_existe'.
    Cualquier duda ('incierto') NO reenvía (prefiere no duplicar).
    """
    if intentos < 1:
        return 'proceder'            # 1er intento: nunca se envió, no hay riesgo de duplicar
    if estado_cdr == 'aceptado':
        return 'detenido_aceptado'   # YA está en SUNAT → jamás reenviar
    if estado_cdr == 'rechazado':
        return 'detenido_rechazado'  # YA lo procesó (rechazo) → no reenviar
    if estado_cdr == 'no_existe':
        return 'proceder'            # confirmado que NO lo tiene → seguro reenviar
    return 'incierto'                # incierto → NO reenviar


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
