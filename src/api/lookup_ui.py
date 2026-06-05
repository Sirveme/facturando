"""
Lookup RUC/DNI real para el dashboard (apis.net.pe vía services/ruc_lookup).

Autentica con la sesión del dashboard (obtener_emisor_actual), igual que
/api/productos/buscar — NO el patrón cookies.get("session"). No-fatal: el
servicio devuelve {"encontrado": False, ...} ante cualquier fallo de red/API.

Rutas:
  GET /api/ruc/{numero}
  GET /api/dni/{numero}
"""
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.services.ruc_lookup import consultar_ruc, consultar_dni

router = APIRouter(prefix="/api", tags=["lookup"])


@router.get("/ruc/{numero}")
async def api_ruc(numero: str, request: Request, db: Session = Depends(get_db)):
    """Consulta RUC en SUNAT. Devuelve {exito, datos} para el front."""
    await obtener_emisor_actual(request, db)
    res = consultar_ruc(numero)
    if res.get("encontrado"):
        return {"exito": True, "datos": res}
    return {"exito": False, "mensaje": res.get("mensaje") or "RUC no encontrado", "datos": res}


@router.get("/dni/{numero}")
async def api_dni(numero: str, request: Request, db: Session = Depends(get_db)):
    """Consulta DNI en RENIEC. Devuelve {exito, datos} para el front."""
    await obtener_emisor_actual(request, db)
    res = consultar_dni(numero)
    if res.get("encontrado"):
        return {"exito": True, "datos": res}
    return {"exito": False, "mensaje": res.get("mensaje") or "DNI no encontrado", "datos": res}
