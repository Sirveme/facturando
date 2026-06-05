"""
Lookup RUC/DNI real contra apis.net.pe (SUNAT/RENIEC).

Portado del patrón usado en los proyectos hermanos (QueVendi/CCPL): apis.net.pe
con token Bearer. MISMA variable de entorno que el origen: APIS_NET_PE_TOKEN
(ya presente en facturalo) — facilita configurarla en Railway.

Endpoints (v2, devuelven dirección + ubigeo desagregado y estado/condición):
  RUC:  GET https://api.apis.net.pe/v2/sunat/ruc?numero={ruc}
  DNI:  GET https://api.apis.net.pe/v2/reniec/dni?numero={dni}

Diseño: timeout 8s y NO-FATAL — ante cualquier fallo devuelve
{"encontrado": False, "mensaje": ...} sin levantar excepción.
"""
import logging
from typing import Dict, Optional

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.apis.net.pe"
_TIMEOUT = 8  # segundos (no-fatal)


def _token() -> Optional[str]:
    tok = getattr(settings, "APIS_NET_PE_TOKEN", "") or ""
    return tok.strip() or None


def _get(path: str, numero: str) -> Optional[dict]:
    """GET no-fatal a apis.net.pe. Devuelve el JSON o None ante cualquier fallo."""
    token = _token()
    if not token:
        logger.warning("[RUC_LOOKUP] APIS_NET_PE_TOKEN no configurado")
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Referer": "https://facturalo.pro",
    }
    try:
        resp = requests.get(f"{_API_URL}{path}", headers=headers,
                            params={"numero": numero}, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("[RUC_LOOKUP] %s numero=%s -> HTTP %s", path, numero, resp.status_code)
    except requests.exceptions.RequestException as e:
        logger.warning("[RUC_LOOKUP] %s numero=%s -> %s", path, numero, e)
    except Exception as e:  # no-fatal ante JSON inválido u otros
        logger.warning("[RUC_LOOKUP] %s numero=%s -> %s", path, numero, e)
    return None


def consultar_ruc(ruc: str) -> Dict:
    """Consulta un RUC en SUNAT.

    Returns dict normalizado:
      {encontrado, ruc, razon_social, direccion, ubigeo, departamento,
       provincia, distrito, estado, condicion, habilitado, mensaje}
    `habilitado` = ACTIVO + HABIDO (para advertir baja/no habido en el front).
    """
    ruc = (ruc or "").strip()
    if len(ruc) != 11 or not ruc.isdigit():
        return {"encontrado": False, "ruc": ruc, "mensaje": "RUC debe tener 11 dígitos"}

    data = _get("/v2/sunat/ruc", ruc)
    if not data:
        return {"encontrado": False, "ruc": ruc, "mensaje": "No se encontró información"}

    razon_social = (data.get("razonSocial") or data.get("nombre") or "").strip()
    direccion = (data.get("direccion") or "").strip()
    if direccion == "-":
        direccion = ""
    estado = (data.get("estado") or "").strip().upper()
    condicion = (data.get("condicion") or "").strip().upper()

    return {
        "encontrado": bool(razon_social),
        "ruc": ruc,
        "razon_social": razon_social,
        "direccion": direccion,
        "ubigeo": (data.get("ubigeo") or "").strip(),
        "departamento": (data.get("departamento") or data.get("dpto") or "").strip(),
        "provincia": (data.get("provincia") or "").strip(),
        "distrito": (data.get("distrito") or "").strip(),
        "estado": estado,
        "condicion": condicion,
        "habilitado": (estado in ("", "ACTIVO")) and (condicion in ("", "HABIDO")),
        "mensaje": "" if razon_social else "No se encontró información",
    }


def consultar_dni(dni: str) -> Dict:
    """Consulta un DNI en RENIEC.

    Returns dict normalizado:
      {encontrado, dni, nombre_completo, nombres, apellido_paterno,
       apellido_materno, mensaje}
    """
    dni = (dni or "").strip()
    if len(dni) != 8 or not dni.isdigit():
        return {"encontrado": False, "dni": dni, "mensaje": "DNI debe tener 8 dígitos"}

    data = _get("/v2/reniec/dni", dni)
    if not data:
        return {"encontrado": False, "dni": dni, "mensaje": "No se encontró información"}

    nombres = (data.get("nombres") or "").strip()
    ap_pat = (data.get("apellidoPaterno") or "").strip()
    ap_mat = (data.get("apellidoMaterno") or "").strip()
    nombre_completo = (data.get("nombreCompleto")
                       or f"{ap_pat} {ap_mat} {nombres}").strip()

    return {
        "encontrado": bool(nombre_completo),
        "dni": dni,
        "nombre_completo": nombre_completo,
        "nombres": nombres,
        "apellido_paterno": ap_pat,
        "apellido_materno": ap_mat,
        "mensaje": "" if nombre_completo else "No se encontró información",
    }
