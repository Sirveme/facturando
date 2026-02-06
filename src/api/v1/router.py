"""
Router principal API v1
"""
from fastapi import APIRouter
from datetime import datetime

from src.api.v1.comprobantes import router as comprobantes_router
from src.api.v1.consultas import router as consultas_router

router = APIRouter(prefix="/api/v1")

# Incluir sub-routers
router.include_router(comprobantes_router)
router.include_router(consultas_router)


@router.get(
    "/estado",
    summary="Estado del servicio",
    description="Verifica que el servicio esté operativo",
    tags=["Sistema"]
)
async def estado_servicio():
    """Verifica estado del servicio"""
    return {
        "exito": True,
        "servicio": "facturalo.pro API",
        "version": "1.0.0",
        "estado": "operativo",
        "timestamp": datetime.now().isoformat(),
        "documentacion": "/docs"
    }


@router.get(
    "/",
    summary="Información de la API",
    tags=["Sistema"]
)
async def info_api():
    """Información general de la API"""
    return {
        "nombre": "facturalo.pro API v1",
        "version": "1.0.0",
        "descripcion": "API REST para facturación electrónica SUNAT Perú",
        "endpoints": {
            "emitir": "POST /api/v1/comprobantes",
            "consultar": "GET /api/v1/comprobantes/{id}",
            "pdf": "GET /api/v1/comprobantes/{id}/pdf",
            "xml": "GET /api/v1/comprobantes/{id}/xml",
            "anular": "POST /api/v1/comprobantes/anular",
            "consulta_ruc": "GET /api/v1/consulta/ruc/{ruc}",
            "consulta_dni": "GET /api/v1/consulta/dni/{dni}",
            "estado": "GET /api/v1/estado"
        },
        "autenticacion": {
            "tipo": "API Key",
            "headers": ["X-API-Key", "X-API-Secret"]
        },
        "documentacion": "/docs",
        "soporte": "soporte@facturalo.pro"
    }