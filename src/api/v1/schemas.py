"""
Schemas Pydantic para API v1
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date


class ClienteRequest(BaseModel):
    """Datos del cliente/receptor"""
    tipo_documento: str = Field(..., description="1=DNI, 6=RUC, 4=CE, 7=Pasaporte, 0=Sin doc")
    numero_documento: str = Field(..., description="Número de documento")
    razon_social: str = Field(..., description="Nombre o razón social")
    direccion: Optional[str] = Field(None, description="Dirección fiscal")
    email: Optional[str] = Field(None, description="Email para envío")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tipo_documento": "1",
                "numero_documento": "12345678",
                "razon_social": "JUAN PÉREZ GARCÍA",
                "direccion": "Av. Principal 123",
                "email": "juan@email.com"
            }
        }


class ItemRequest(BaseModel):
    """Ítem del comprobante"""
    descripcion: str = Field(..., description="Descripción del producto/servicio")
    cantidad: float = Field(1, description="Cantidad", gt=0)
    unidad_medida: str = Field("ZZ", description="Código SUNAT: NIU, ZZ, KGM, etc.")
    precio_unitario: float = Field(..., description="Precio unitario SIN IGV", gt=0)
    tipo_afectacion_igv: str = Field("10", description="10=Gravado, 20=Exonerado, 30=Inafecto")
    descuento: Optional[float] = Field(0, description="Descuento en soles", ge=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "descripcion": "Cuota ordinaria Febrero 2026",
                "cantidad": 1,
                "unidad_medida": "ZZ",
                "precio_unitario": 50.00,
                "tipo_afectacion_igv": "10"
            }
        }


class ComprobanteRequest(BaseModel):
    """Request para emitir comprobante"""
    tipo_comprobante: str = Field(..., description="01=Factura, 03=Boleta, 07=NC, 08=ND")
    serie: Optional[str] = Field(None, description="Serie (auto si no se especifica)")
    codigo_matricula: Optional[str] = Field(None, description="Código matrícula del colegiado")
    cliente: ClienteRequest
    items: List[ItemRequest] = Field(..., min_length=1)
    observaciones: Optional[str] = Field(None, max_length=500)
    fecha_emision: Optional[str] = Field(None, description="YYYY-MM-DD, hoy si vacío")
    hora_emision: Optional[str] = None
    enviar_email: bool = Field(False, description="Enviar por email al cliente")
    referencia_externa: Optional[str] = Field(None, description="ID en sistema origen", max_length=100)
    
    # Para NC/ND
    documento_ref_tipo: Optional[str] = Field(None, description="Tipo doc referencia")
    documento_ref_serie: Optional[str] = Field(None, description="Serie doc referencia")
    documento_ref_numero: Optional[int] = Field(None, description="Número doc referencia")
    motivo_nota: Optional[str] = Field(None, description="Motivo NC/ND: 01-07")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tipo_comprobante": "03",
                "cliente": {
                    "tipo_documento": "1",
                    "numero_documento": "12345678",
                    "razon_social": "JUAN PÉREZ GARCÍA"
                },
                "items": [
                    {
                        "descripcion": "Cuota ordinaria Febrero 2026",
                        "cantidad": 1,
                        "precio_unitario": 50.00,
                        "tipo_afectacion_igv": "10"
                    }
                ],
                "enviar_email": True,
                "referencia_externa": "PAGO-2026-00123"
            }
        }


class ComprobanteData(BaseModel):
    """Datos del comprobante emitido"""
    id: str
    tipo: str
    serie: str
    numero: int
    numero_formato: str
    fecha_emision: str
    cliente_documento: str
    cliente_nombre: str
    subtotal: float
    igv: float
    total: float
    estado: str
    hash_cpe: Optional[str]
    codigo_sunat: Optional[str]
    mensaje_sunat: Optional[str]


class ArchivosData(BaseModel):
    """URLs de archivos del comprobante"""
    pdf_url: str
    xml_url: str
    cdr_url: Optional[str]


class ComprobanteResponse(BaseModel):
    """Response de emisión exitosa"""
    exito: bool = True
    comprobante: ComprobanteData
    archivos: ArchivosData
    mensaje: Optional[str]


class ErrorResponse(BaseModel):
    """Response de error"""
    exito: bool = False
    error: str
    codigo: str
    detalle: Optional[str] = None


class AnularRequest(BaseModel):
    """Request para anular comprobante"""
    comprobante_id: str = Field(..., description="ID del comprobante")
    motivo: str = Field(..., description="Motivo de anulación", max_length=200)


class ConsultaRUCResponse(BaseModel):
    """Response de consulta RUC"""
    exito: bool
    ruc: str
    razon_social: Optional[str]
    direccion: Optional[str]
    estado: Optional[str]
    condicion: Optional[str]


class ConsultaDNIResponse(BaseModel):
    """Response de consulta DNI"""
    exito: bool
    dni: str
    nombres: Optional[str]
    apellido_paterno: Optional[str]
    apellido_materno: Optional[str]
    nombre_completo: Optional[str]


class EstadoResponse(BaseModel):
    """Response de estado del servicio"""
    exito: bool
    servicio: str
    estado: str
    version: str
    timestamp: str