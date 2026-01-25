from __future__ import annotations
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from decimal import Decimal
from datetime import date

class LineaItem(BaseModel):
    orden: int
    descripcion: str
    cantidad: Decimal
    unidad: Optional[str]
    precio_unitario: Decimal

    @validator('cantidad', 'precio_unitario')
    def positive_decimal(cls, v):
        if v is None:
            return v
        if v < 0:
            raise ValueError('Debe ser positivo')
        return v

class ComprobanteCreate(BaseModel):
    emisor_ruc: str
    tipo_documento: str
    serie: str
    numero: Optional[int]
    fecha_emision: str  # dd/mm/YYYY input
    moneda: Optional[str] = 'PEN'
    items: List[LineaItem]

    @validator('fecha_emision')
    def valid_fecha(cls, v):
        # validate dd/mm/YYYY
        try:
            if '/' in v:
                d_parts = v.split('/')
                if len(d_parts) != 3:
                    raise ValueError()
                # simple check
                day, month, year = d_parts
                _ = date(int(year), int(month), int(day))
            else:
                _ = date.fromisoformat(v)
        except Exception:
            raise ValueError('fecha_emision debe tener formato dd/mm/YYYY')
        return v

class ComprobanteResponse(BaseModel):
    id: str
    estado: str
    mensaje: Optional[str]

class EmisorCreate(BaseModel):
    ruc: str
    razon_social: str
    nombre_comercial: Optional[str]

class CertificadoUpload(BaseModel):
    emisor_ruc: str
    archivo_base64: str
    password: str

class StandardResponse(BaseModel):
    exito: bool
    datos: Optional[dict]
    mensaje: Optional[str]
