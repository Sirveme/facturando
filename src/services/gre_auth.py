"""
Cliente OAuth2 para la API REST de GRE (Guía de Remisión Electrónica) de SUNAT.

SUNAT usa para GRE (tipo 09) un canal REST distinto al SOAP. La autenticación
es OAuth2 (grant_type=password). Este módulo obtiene y cachea el access_token
por emisor en memoria.

Convención: usa `requests` (igual que sunat_client.py) y descifra credenciales
con Fernet/encryption_key (igual que sol_password).
"""

import time
import logging

import requests
from cryptography.fernet import Fernet

from src.core.config import settings

logger = logging.getLogger(__name__)

# Endpoint OAuth2 de seguridad SUNAT
SUNAT_OAUTH_URL = (
    "https://api-seguridad.sunat.gob.pe/v1/clientessol/"
    "{client_id}/oauth2/token"
)
SUNAT_GRE_SCOPE = "https://api-cpe.sunat.gob.pe"

# Margen para renovar antes de que expire (segundos)
_RENEW_MARGIN = 120

# Caché en memoria por emisor: { emisor_id: {"token": str, "expires_at": float} }
_token_cache: dict[str, dict] = {}


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _decrypt(value: str | None) -> str | None:
    """Descifra un valor cifrado con Fernet. Tolera valores en texto plano
    (mismo criterio que el manejo de sol_password en el proyecto)."""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        # Si no estaba cifrado (texto plano histórico), devolver tal cual.
        return value


def _request_token(emisor) -> dict:
    """Solicita un token nuevo a SUNAT. Devuelve el JSON de respuesta."""
    client_id = emisor.gre_client_id
    client_secret = _decrypt(emisor.gre_client_secret_encrypted)
    clave_sol = _decrypt(emisor.sol_password)

    if not client_id or not client_secret:
        raise ValueError(
            f"Emisor {emisor.ruc} sin credenciales GRE configuradas "
            "(gre_client_id / gre_client_secret_encrypted)."
        )
    # gre_sol_usuario tiene prioridad; si es NULL se usa sol_usuario.
    sol_user = getattr(emisor, "gre_sol_usuario", None) or emisor.sol_usuario
    if not sol_user or not clave_sol:
        raise ValueError(
            f"Emisor {emisor.ruc} sin usuario/clave SOL para autenticación GRE."
        )

    username = f"{emisor.ruc}{sol_user}"
    url = SUNAT_OAUTH_URL.format(client_id=client_id)

    data = {
        "grant_type": "password",
        "scope": SUNAT_GRE_SCOPE,
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": clave_sol,
    }

    logger.info("[GRE_AUTH] Solicitando token OAuth2 para RUC %s (user=%s)",
                emisor.ruc, username)

    resp = requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=settings.sunat_timeout,
    )

    if resp.status_code != 200:
        # Detalle del body SUNAT, sin loguear client_secret ni password.
        detalle = resp.text[:500]
        logger.error("[GRE_AUTH] Token HTTP %d: %s", resp.status_code, detalle)
        raise Exception(
            f"SUNAT OAuth2 HTTP {resp.status_code} para RUC {emisor.ruc}: {detalle}"
        )

    payload = resp.json()
    if "access_token" not in payload:
        raise Exception(
            f"Respuesta OAuth2 sin access_token para RUC {emisor.ruc}: {payload}"
        )

    logger.info("[GRE_AUTH] Token obtenido para RUC %s (expires_in=%s)",
                emisor.ruc, payload.get("expires_in"))
    return payload


def get_gre_token(emisor, force_new: bool = False) -> str:
    """Devuelve un access_token GRE válido para el emisor.

    Cachea el token en memoria por emisor y lo renueva si faltan menos de
    120 segundos para expirar (o si force_new=True).

    Args:
        emisor: instancia del modelo Emisor.
        force_new: fuerza renovación (p.ej. tras un 401).

    Returns:
        access_token (str).
    """
    now = time.time()
    cached = _token_cache.get(emisor.id)

    if (
        not force_new
        and cached
        and cached["expires_at"] - now > _RENEW_MARGIN
    ):
        logger.debug("[GRE_AUTH] Reusando token cacheado para RUC %s", emisor.ruc)
        return cached["token"]

    payload = _request_token(emisor)
    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))

    _token_cache[emisor.id] = {
        "token": token,
        "expires_at": now + expires_in,
    }
    return token


def invalidar_token(emisor) -> None:
    """Elimina el token cacheado de un emisor (p.ej. tras un 401)."""
    _token_cache.pop(emisor.id, None)
