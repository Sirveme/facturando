"""
src/services/pagook_client.py — Cliente de la API de PagoOK v1 (consulta de pagos).

Contrato: docs/consulta-pagos-v1.md (repo PagoOK). Dos operaciones:
  - consultar_pago  → POST /pagos/consultar        → {nivel: alta|media|sin_coincidencia, ...}
  - marcar_usado    → POST /pagos/{id}/marcar-usado → 200 | 409 | 404

Autenticación: header `X-API-Key` = os.environ['PAGOOK_API_KEY'], leído POR LLAMADA
(mismo patrón que ruc_lookup: evita el snapshot congelado en Railway).
Base URL: os.environ['PAGOOK_BASE_URL'] o https://pagook.pro/api/v1.

NO-FATAL (regla de oro para dinero): ante CUALQUIER fallo (red, timeout, 4xx/5xx,
JSON inválido), `consultar_pago` devuelve `nivel='error'` → el motor NUNCA activa
solo; y `marcar_usado` devuelve `ok=False`. Marcar-usado SIEMPRE antes de activar.
"""
import os
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_DEFAULT_BASE = "https://pagook.pro/api/v1"


def _base() -> str:
    return (os.environ.get("PAGOOK_BASE_URL") or _DEFAULT_BASE).rstrip("/")


def _headers() -> dict:
    return {
        "X-API-Key": (os.environ.get("PAGOOK_API_KEY") or "").strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def consultar_pago(monto, fecha_hora_declarada, *, nombre_pagador_declarado=None,
                   codigo_operacion=None, canal=None, ventana_minutos=None) -> dict:
    """POST /pagos/consultar. Devuelve el dict del contrato (con `nivel`).

    `monto` se envía como string decimal ("30.00"). `fecha_hora_declarada` ISO 8601
    (sin zona = hora de Lima). Opcionales solo se incluyen si vienen con valor.
    Ante error → {'nivel':'error', ...} (nunca 'alta' por accidente).
    """
    body = {"monto": str(monto), "fecha_hora_declarada": fecha_hora_declarada}
    if ventana_minutos is not None:
        body["ventana_minutos"] = ventana_minutos
    if canal:
        body["canal"] = canal
    if nombre_pagador_declarado:
        body["nombre_pagador_declarado"] = nombre_pagador_declarado
    if codigo_operacion:
        body["codigo_operacion"] = codigo_operacion

    try:
        r = httpx.post(f"{_base()}/pagos/consultar", headers=_headers(), json=body, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            data.setdefault("nivel", "error")
            return data
        logger.warning("[PAGOOK] consultar HTTP %s: %s", r.status_code, (r.text or "")[:200])
        return {"nivel": "error", "motivo": f"http_{r.status_code}",
                "mensaje": f"PagoOK respondió HTTP {r.status_code}", "pago": None, "candidatos": []}
    except Exception as e:  # red/timeout/JSON → no-fatal
        logger.warning("[PAGOOK] consultar error: %s", e)
        return {"nivel": "error", "motivo": "red",
                "mensaje": f"No se pudo consultar PagoOK: {e}", "pago": None, "candidatos": []}


def marcar_usado(pago_id, referencia_externa, sistema="Facturalo suscripciones") -> dict:
    """POST /pagos/{id}/marcar-usado. Devuelve {status, ok, body}.

    status 200 → marcado (idempotente con misma credencial+referencia); ok=True.
    status 409 → el pago ya se usó para otra referencia / otro sistema; ok=False.
    status 404 → el pago no existe o no es de la empresa; ok=False.
    Error de red → {status:0, ok:False}.
    """
    body = {"referencia_externa": referencia_externa}
    if sistema:
        body["sistema"] = sistema
    try:
        r = httpx.post(f"{_base()}/pagos/{pago_id}/marcar-usado",
                       headers=_headers(), json=body, timeout=_TIMEOUT)
        try:
            data = r.json()
        except Exception:
            data = {}
        return {"status": r.status_code, "ok": r.status_code == 200, "body": data}
    except Exception as e:
        logger.warning("[PAGOOK] marcar_usado error: %s", e)
        return {"status": 0, "ok": False, "body": {"error": str(e)}}
