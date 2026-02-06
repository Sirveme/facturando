"""
Autenticación API v1
"""
from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy.orm import Session
import hashlib
from datetime import date

from src.api.dependencies import get_db
from src.models.models import Emisor


class APIAuthError(HTTPException):
    """Error de autenticación API"""
    def __init__(self, codigo: str, mensaje: str, status_code: int = 401):
        super().__init__(
            status_code=status_code,
            detail={
                "exito": False,
                "error": mensaje,
                "codigo": codigo
            }
        )


async def verificar_api_key(
    request: Request,
    x_api_key: str = Header(..., description="API Key del cliente"),
    x_api_secret: str = Header(..., description="API Secret del cliente"),
    db: Session = Depends(get_db)
) -> Emisor:
    """
    Verifica las credenciales de API y retorna el emisor.
    """
    if not x_api_key or not x_api_secret:
        raise APIAuthError("AUTH_REQUIRED", "Credenciales API requeridas")
    
    # Buscar emisor por API Key
    emisor = db.query(Emisor).filter(Emisor.api_key == x_api_key).first()
    
    if not emisor:
        raise APIAuthError("INVALID_API_KEY", "API Key inválida")
    
    # Verificar API Secret (comparar hash)
    secret_hash = hashlib.sha256(x_api_secret.encode()).hexdigest()
    if emisor.api_secret != secret_hash:
        raise APIAuthError("INVALID_API_SECRET", "API Secret inválido")
    
    # Verificar que API esté activa
    if not emisor.api_activa:
        raise APIAuthError("API_DISABLED", "API no activada para esta cuenta", 403)
    
    # Verificar que el emisor esté activo
    if not emisor.activo:
        raise APIAuthError("ACCOUNT_SUSPENDED", "Cuenta suspendida", 403)
    
    # Reset contador mensual si es nuevo mes
    hoy = date.today()
    if emisor.fecha_reset_contador and emisor.fecha_reset_contador.month != hoy.month:
        emisor.docs_mes_usados = 0
        emisor.fecha_reset_contador = hoy
        db.commit()
    
    # Verificar límite de documentos
    if emisor.docs_mes_usados >= emisor.docs_mes_limite:
        raise APIAuthError(
            "LIMIT_EXCEEDED",
            f"Límite mensual alcanzado ({emisor.docs_mes_limite} docs). Contacte soporte.",
            429
        )
    
    # Guardar emisor en request para logging
    request.state.emisor = emisor
    
    return emisor


def generar_api_credentials() -> tuple:
    """Genera nuevas credenciales API (key, secret)"""
    import secrets
    
    api_key = f"fpl_{secrets.token_hex(24)}"  # fpl = facturalo pro live
    api_secret = secrets.token_hex(32)
    api_secret_hash = hashlib.sha256(api_secret.encode()).hexdigest()
    
    return api_key, api_secret, api_secret_hash