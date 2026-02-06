"""
API de Administración - facturalo.pro
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.models.models import Emisor
from src.api.v1.auth import generar_api_credentials

router = APIRouter(prefix="/admin", tags=["Administración"])


@router.post("/emisor/{emisor_id}/activar-api")
async def activar_api_emisor(
    emisor_id: str,
    plan: str = "institucional",
    docs_limite: int = 500,
    db: Session = Depends(get_db)
):
    """Activa API para un emisor y genera credenciales"""
    emisor = db.query(Emisor).filter(Emisor.id == emisor_id).first()
    if not emisor:
        raise HTTPException(404, detail="Emisor no encontrado")
    
    # Generar credenciales
    api_key, api_secret, api_secret_hash = generar_api_credentials()
    
    # Guardar
    emisor.api_key = api_key
    emisor.api_secret = api_secret_hash
    emisor.api_activa = True
    emisor.plan = plan
    emisor.docs_mes_limite = docs_limite
    emisor.docs_mes_usados = 0
    
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "API activada correctamente",
        "credenciales": {
            "api_key": api_key,
            "api_secret": api_secret,
            "plan": plan,
            "docs_mes_limite": docs_limite
        },
        "advertencia": "Guarde el api_secret, no se puede recuperar después"
    }


@router.get("/emisor/{emisor_id}/api-stats")
async def stats_api_emisor(
    emisor_id: str,
    db: Session = Depends(get_db)
):
    """Estadísticas de uso de API"""
    emisor = db.query(Emisor).filter(Emisor.id == emisor_id).first()
    if not emisor:
        raise HTTPException(404, detail="Emisor no encontrado")
    
    return {
        "emisor_id": emisor_id,
        "api_activa": emisor.api_activa,
        "plan": emisor.plan,
        "docs_mes_limite": emisor.docs_mes_limite,
        "docs_mes_usados": emisor.docs_mes_usados,
        "docs_disponibles": (emisor.docs_mes_limite or 0) - (emisor.docs_mes_usados or 0)
    }