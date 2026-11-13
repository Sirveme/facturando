"""
padron_lookup.py — Consulta de RUC contra el padrón, con PSP como fuente PRIMARIA
y apis.net.pe como RESPALDO.

Motivación (Duilio, nov-2026): apis.net.pe cobra por consulta y no trae la dirección
de personas naturales (RUC 10…). La API propia de PSP se usa primero; apis.net.pe
queda solo como respaldo.

CONTRATO PSP — calcado de C:\\metraes\\app\\services\\psp_service.py (cliente real en
producción), NO inferido:
  GET {PSP_BASE}/ruc/{ruc}        (RUC en el PATH)
  Headers: Authorization: Bearer {PSP_API_KEY}, Accept: application/json, User-Agent navegador
  PSP_BASE = env PSP_API_BASE | "https://club.perusistemas.pro/api/v1"
  404 → no encontrado ; 200 → JSON ; otro → None (respaldo)
  JSON: { encontrado, razon_social, domicilio, estado:{codigo,nombre}, condicion:{codigo,nombre} }
Cloudflare banea firmas de cliente HTTP "de bot" (error 1010/403) → User-Agent de navegador.
Clave: variable de entorno PSP_API_KEY (del entorno vivo por llamada; no snapshot congelado).

Diseño: NO-FATAL de punta a punta. Si PSP falla cae a apis.net.pe; si ambos fallan
devuelve {encontrado: False}. Nunca levanta.

Devuelve el MISMO dict normalizado que ruc_lookup.consultar_ruc, más 'fuente'
('psp' | 'apis' | '').
"""
import os
import logging
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

_PSP_BASE = (os.getenv("PSP_API_BASE", "https://club.perusistemas.pro/api/v1") or "").rstrip("/")
_TIMEOUT = 8  # segundos (no-fatal)

# User-Agent de navegador: Cloudflare banea clientes HTTP "de bot" (error 1010).
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _psp_key() -> Optional[str]:
    """PSP_API_KEY del entorno vivo (por llamada; no snapshot congelado)."""
    k = (os.environ.get("PSP_API_KEY", "") or "").strip()
    return k or None


def _cod_nombre(v) -> tuple:
    """Normaliza un campo estado/condicion que PSP manda como {codigo,nombre}.
    Tolera que venga como string plano. Devuelve (codigo_upper, nombre)."""
    if isinstance(v, dict):
        return (str(v.get("codigo") or "").strip().upper(), str(v.get("nombre") or "").strip())
    s = str(v or "").strip()
    return (s.upper(), s)


def _normalizar_psp(ruc: str, data) -> Optional[Dict]:
    """Normaliza la respuesta de PSP (contrato Metraes) al dict estándar."""
    if not isinstance(data, dict):
        return None
    if data.get("encontrado") is False:
        return None  # 404 lógico → que decida el respaldo

    razon = str(data.get("razon_social") or "").strip()
    if not razon:
        return None

    direccion = str(data.get("domicilio") or "").strip()
    if direccion == "-":
        direccion = ""
    estado_cod, _ = _cod_nombre(data.get("estado"))
    cond_cod, _ = _cod_nombre(data.get("condicion"))

    return {
        "encontrado": True,
        "ruc": ruc,
        "razon_social": razon,
        "direccion": direccion,
        # PSP (contrato Metraes) no expone ubigeo/dep/prov/dist; se dejan vacíos.
        "ubigeo": str(data.get("ubigeo") or "").strip(),
        "departamento": str(data.get("departamento") or "").strip(),
        "provincia": str(data.get("provincia") or "").strip(),
        "distrito": str(data.get("distrito") or "").strip(),
        "estado": estado_cod,
        "condicion": cond_cod,
        "habilitado": (estado_cod in ("", "ACTIVO")) and (cond_cod in ("", "HABIDO")),
        "mensaje": "",
        "fuente": "psp",
    }


def _consultar_psp(ruc: str) -> Optional[Dict]:
    """GET {PSP_BASE}/ruc/{ruc} no-fatal. Devuelve dict normalizado o None."""
    key = _psp_key()
    if not key:
        return None
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": _BROWSER_UA,
    }
    try:
        resp = requests.get(f"{_PSP_BASE}/ruc/{ruc}", headers=headers, timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None  # no encontrado → respaldo
        if resp.status_code != 200:
            logger.warning("[PADRON][PSP] ruc=%s -> HTTP %s", ruc, resp.status_code)
            return None
        try:
            data = resp.json()
        except Exception:
            logger.warning("[PADRON][PSP] ruc=%s -> respuesta no-JSON", ruc)
            return None
        return _normalizar_psp(ruc, data)
    except requests.exceptions.RequestException as e:
        logger.warning("[PADRON][PSP] ruc=%s -> %s", ruc, e)
    except Exception as e:  # no-fatal ante cualquier cosa
        logger.warning("[PADRON][PSP] ruc=%s -> %s", ruc, e)
    return None


def consultar_ruc_padron(ruc: str) -> Dict:
    """Consulta un RUC: PSP primero, apis.net.pe de respaldo. NO-FATAL.

    Devuelve el mismo dict normalizado que ruc_lookup.consultar_ruc, con 'fuente'.
    """
    ruc = (ruc or "").strip()
    if len(ruc) != 11 or not ruc.isdigit():
        return {"encontrado": False, "ruc": ruc, "mensaje": "RUC debe tener 11 dígitos",
                "fuente": ""}

    # 1) PSP (primario)
    try:
        res = _consultar_psp(ruc)
        if res and res.get("encontrado"):
            return res
    except Exception as e:
        logger.warning("[PADRON] PSP falló para %s: %s", ruc, e)

    # 2) apis.net.pe (respaldo, cobra por consulta)
    try:
        from src.services.ruc_lookup import consultar_ruc
        res = consultar_ruc(ruc)
        if isinstance(res, dict):
            res.setdefault("fuente", "apis" if res.get("encontrado") else "")
            return res
    except Exception as e:
        logger.warning("[PADRON] respaldo apis.net.pe falló para %s: %s", ruc, e)

    return {"encontrado": False, "ruc": ruc, "mensaje": "No se encontró información",
            "fuente": ""}
