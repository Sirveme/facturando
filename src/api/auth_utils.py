from fastapi import Request, HTTPException
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from src.models.models import Emisor
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")

async def obtener_emisor_actual(request: Request, db: Session) -> Emisor:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        emisor_id = payload.get("emisor_id")
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesión expirada")
    
    emisor = db.query(Emisor).filter(Emisor.id == emisor_id).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    return emisor