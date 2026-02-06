"""
API v1 - Endpoints de Consultas
"""
from fastapi import APIRouter, Depends, HTTPException
import httpx

from src.models.models import Emisor
from src.api.v1.auth import verificar_api_key
from src.api.v1.schemas import ConsultaRUCResponse, ConsultaDNIResponse

router = APIRouter(prefix="/consulta", tags=["Consultas"])


@router.get(
    "/ruc/{ruc}",
    response_model=ConsultaRUCResponse,
    summary="Consultar RUC",
    description="Consulta datos de un RUC en SUNAT"
)
async def consultar_ruc(
    ruc: str,
    emisor: Emisor = Depends(verificar_api_key)
):
    """Consulta RUC en SUNAT"""
    if len(ruc) != 11 or not ruc.isdigit():
        raise HTTPException(400, detail={
            "exito": False,
            "error": "RUC debe tener 11 dígitos numéricos",
            "codigo": "RUC_INVALIDO"
        })
    
    # TODO: Integrar con API real de SUNAT o servicio de consulta
    # Por ahora usamos servicio externo o datos de ejemplo
    
    try:
        # Intentar consulta a API externa (ejemplo con apis.net.pe)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.apis.net.pe/v1/ruc?numero={ruc}",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "exito": True,
                    "ruc": ruc,
                    "razon_social": data.get("nombre", data.get("razonSocial")),
                    "direccion": data.get("direccion"),
                    "estado": data.get("estado"),
                    "condicion": data.get("condicion")
                }
    except:
        pass
    
    # Fallback: datos de ejemplo
    return {
        "exito": True,
        "ruc": ruc,
        "razon_social": None,
        "direccion": None,
        "estado": None,
        "condicion": None
    }


@router.get(
    "/dni/{dni}",
    response_model=ConsultaDNIResponse,
    summary="Consultar DNI",
    description="Consulta datos de un DNI en RENIEC"
)
async def consultar_dni(
    dni: str,
    emisor: Emisor = Depends(verificar_api_key)
):
    """Consulta DNI en RENIEC"""
    if len(dni) != 8 or not dni.isdigit():
        raise HTTPException(400, detail={
            "exito": False,
            "error": "DNI debe tener 8 dígitos numéricos",
            "codigo": "DNI_INVALIDO"
        })
    
    # TODO: Integrar con API real de RENIEC
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.apis.net.pe/v1/dni?numero={dni}",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "exito": True,
                    "dni": dni,
                    "nombres": data.get("nombres"),
                    "apellido_paterno": data.get("apellidoPaterno"),
                    "apellido_materno": data.get("apellidoMaterno"),
                    "nombre_completo": data.get("nombreCompleto")
                }
    except:
        pass
    
    return {
        "exito": True,
        "dni": dni,
        "nombres": None,
        "apellido_paterno": None,
        "apellido_materno": None,
        "nombre_completo": None
    }