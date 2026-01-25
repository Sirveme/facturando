from fastapi import HTTPException, Header, Depends
from typing import Optional

def verificar_token(authorization: Optional[str] = Header(None)) -> str:
    """Verifica token básico"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization requerido")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Formato inválido")
    
    token = authorization.replace("Bearer ", "")
    
    if ":" not in token:
        raise HTTPException(status_code=401, detail="Token debe ser ruc:clave")
    
    emisor_ruc = token.split(":")[0]
    return emisor_ruc


def verificar_emisor_ruc(emisor_ruc: str, token_ruc: str = Depends(verificar_token)) -> str:
    """
    Verifica que el RUC del token coincida con el RUC solicitado.
    """
    if token_ruc != emisor_ruc:
        raise HTTPException(
            status_code=403,
            detail="No tiene permisos para acceder a este emisor"
        )
    
    return emisor_ruc