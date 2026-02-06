from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.core.config import settings
from src.models.models import Base, Emisor, Comprobante
from src.schemas.schemas import ComprobanteCreate, StandardResponse
from datetime import datetime
import decimal

DATABASE_URL = settings.database_url
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

app = FastAPI(title='facturalo.pro API')

# Create tables if not exist (for MVP convenience)
Base.metadata.create_all(bind=engine)

"""
@app.post('/api/comprobantes/emitir', response_model=StandardResponse)
def emitir_comprobante(payload: ComprobanteCreate):
    session = SessionLocal()
    try:
        emisor = session.query(Emisor).filter_by(ruc=payload.emisor_ruc).first()
        if not emisor:
            raise HTTPException(status_code=404, detail='Emisor no encontrado')
        comp = Comprobante(
            emisor_id=emisor.id,
            tipo_documento=payload.tipo_documento,
            serie=payload.serie,
            numero=payload.numero or 1,
            fecha_emision=datetime.utcnow().date(),
            moneda=payload.moneda,
            monto_base=decimal.Decimal('0.00'),
            monto_igv=decimal.Decimal('0.00'),
            monto_total=decimal.Decimal('0.00'),
            estado='encolado'
        )
        session.add(comp)
        session.commit()
        session.refresh(comp)
        return JSONResponse({'exito': True, 'datos': {'id': comp.id}, 'mensaje': 'Comprobante encolado'})
    finally:
        session.close()

"""

@app.get('/api/comprobantes/{comprobante_id}', response_model=StandardResponse)
def get_comprobante(comprobante_id: str):
    session = SessionLocal()
    try:
        comp = session.query(Comprobante).filter_by(id=comprobante_id).first()
        if not comp:
            return JSONResponse({'exito': False, 'error': {'codigo': 'NOT_FOUND', 'mensaje': 'Comprobante no encontrado'}}, status_code=404)
        datos = {
            'id': comp.id,
            'estado': comp.estado,
            'fecha_emision': comp.fecha_emision.isoformat() if comp.fecha_emision else None
        }
        return {'exito': True, 'datos': datos, 'mensaje': None}
    finally:
        session.close()
