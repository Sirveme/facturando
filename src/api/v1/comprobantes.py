"""
API v1 - Endpoints de Comprobantes
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import timezone, timedelta, datetime
from decimal import Decimal
import hashlib
import json
import time

from src.api.dependencies import get_db
from src.models.models import Emisor, Comprobante, LineaDetalle, Cliente, ApiLog
from src.api.v1.auth import verificar_api_key
from src.api.v1.schemas import (
    ComprobanteRequest, ComprobanteResponse, ErrorResponse,
    AnularRequest, ComprobanteData, ArchivosData
)
from src.api.v1.pdf_generator import generar_pdf_comprobante

PERU_TZ = timedelta(hours=-5)

router = APIRouter(prefix="/comprobantes", tags=["Comprobantes"])


def log_api_call(db: Session, emisor_id: str, request: Request, 
                 endpoint: str, response_code: int, response_body: dict, 
                 duracion_ms: int):
    """Registra llamada a la API"""
    try:
        log = ApiLog(
            emisor_id=emisor_id,
            endpoint=endpoint,
            metodo=request.method,
            request_body=None,  # No guardar por seguridad
            response_code=response_code,
            response_body=json.dumps(response_body)[:1000],  # Limitar tamaño
            ip_origen=request.client.host if request.client else None,
            duracion_ms=duracion_ms
        )
        db.add(log)
        db.commit()
    except:
        pass  # No fallar por log


@router.post(
    "",
    response_model=ComprobanteResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Emitir comprobante electrónico",
    description="""
Emite un comprobante electrónico (Factura, Boleta, NC, ND) y lo envía a SUNAT.

**Tipos de comprobante:**
- `01`: Factura (requiere cliente con RUC)
- `03`: Boleta de Venta
- `07`: Nota de Crédito
- `08`: Nota de Débito

**Tipos de documento cliente:**
- `0`: Sin documento (solo Boleta < S/700)
- `1`: DNI
- `4`: Carnet de Extranjería
- `6`: RUC
- `7`: Pasaporte

**Tipos de afectación IGV:**
- `10`: Gravado - Operación Onerosa
- `20`: Exonerado - Operación Onerosa
- `30`: Inafecto - Operación Onerosa
"""
)
async def emitir_comprobante(
    data: ComprobanteRequest,
    request: Request,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Emite un comprobante electrónico"""
    inicio = time.time()

    # DEBUG - AGREGAR ESTO
    print(f"🔍 DEBUG RECIBIDO:")
    print(f"   fecha_emision: {data.fecha_emision}")
    print(f"   hora_emision: {getattr(data, 'hora_emision', 'NO EXISTE')}")
    print(f"🔍 NC DEBUG: ref_tipo={data.documento_ref_tipo}, ref_serie={data.documento_ref_serie}, ref_numero={data.documento_ref_numero}, motivo={data.motivo_nota}")
    print(f"🔍 ALL FIELDS: {data.model_dump()}")
    # FIN DEBUG
    
    try:
        # === VALIDACIONES ===
        
        # Factura requiere RUC
        if data.tipo_comprobante == "01" and data.cliente.tipo_documento != "6":
            raise HTTPException(400, detail={
                "exito": False,
                "error": "Factura requiere cliente con RUC (tipo_documento: 6)",
                "codigo": "FACTURA_REQUIERE_RUC"
            })
        
        # Validar RUC
        if data.cliente.tipo_documento == "6" and len(data.cliente.numero_documento) != 11:
            raise HTTPException(400, detail={
                "exito": False,
                "error": "RUC debe tener 11 dígitos",
                "codigo": "RUC_INVALIDO"
            })
        
        # Validar DNI
        if data.cliente.tipo_documento == "1" and len(data.cliente.numero_documento) != 8:
            raise HTTPException(400, detail={
                "exito": False,
                "error": "DNI debe tener 8 dígitos",
                "codigo": "DNI_INVALIDO"
            })
        
        # NC/ND requiere referencia
        if data.tipo_comprobante in ["07", "08"]:
            if not all([data.documento_ref_tipo, data.documento_ref_serie, data.documento_ref_numero]):
                raise HTTPException(400, detail={
                    "exito": False,
                    "error": "Nota de Crédito/Débito requiere documento de referencia",
                    "codigo": "REFERENCIA_REQUERIDA"
                })
        
        # === DETERMINAR SERIE ===
        if data.serie:
            serie = data.serie.upper()
        else:
            if data.tipo_comprobante == "01":
                serie = "F001"
            elif data.tipo_comprobante == "03":
                serie = "B001"
            elif data.tipo_comprobante == "07":
                es_factura = data.documento_ref_serie and data.documento_ref_serie[0].upper() == "F"
                serie = "FC01" if es_factura else "BC01"
            elif data.tipo_comprobante == "08":
                es_factura = data.documento_ref_serie and data.documento_ref_serie[0].upper() == "F"
                serie = "FD01" if es_factura else "BD01"
            else:
                serie = "B001"
        
        # === OBTENER CORRELATIVO ===
        db.expire_all()
        
        ultimo = db.query(Comprobante).filter(
            Comprobante.emisor_id == emisor.id,
            Comprobante.serie == serie
        ).order_by(Comprobante.numero.desc()).first()
        
        numero = (ultimo.numero + 1) if ultimo else 1
        
        # === CALCULAR TOTALES ===
        subtotal = 0
        igv_total = 0
        items_data = []
        
        for item in data.items:
            base = round(item.cantidad * item.precio_unitario - (item.descuento or 0), 2)
            
            if item.tipo_afectacion_igv == "10":  # Gravado
                igv = round(base * 0.18, 2)
            else:
                igv = 0
            
            total_item = round(base + igv, 2)
            
            items_data.append({
                "descripcion": item.descripcion,
                "cantidad": item.cantidad,
                "unidad_medida": item.unidad_medida,
                "precio_unitario": item.precio_unitario,
                "valor_unitario": item.precio_unitario,
                "descuento": item.descuento or 0,
                "subtotal": base,
                "igv": igv,
                "total": total_item,
                "tipo_afectacion_igv": item.tipo_afectacion_igv
            })
            
            subtotal += base
            igv_total += igv
        
        total = round(subtotal + igv_total, 2)
        
        # === CLIENTE ===
        cliente = db.query(Cliente).filter(
            Cliente.emisor_id == emisor.id,
            Cliente.numero_documento == data.cliente.numero_documento
        ).first()
        
        if not cliente:
            cliente = Cliente(
                id=str(uuid4()),
                emisor_id=emisor.id,
                tipo_documento=data.cliente.tipo_documento,
                numero_documento=data.cliente.numero_documento,
                razon_social=data.cliente.razon_social,
                direccion=data.cliente.direccion,
                email=data.cliente.email
            )
            db.add(cliente)
        else:
            if data.cliente.email:
                cliente.email = data.cliente.email
        
        # === CREAR COMPROBANTE ===
        comprobante_id = str(uuid4())

        # Hora actual de Perú
        peru_now = datetime.now(tz=timezone(timedelta(hours=-5))).replace(tzinfo=None)

        if data.fecha_emision:
            try:
                # Si viene con hora (formato: 2026-02-09T14:30:00)
                if 'T' in data.fecha_emision:
                    fecha_emision = datetime.fromisoformat(data.fecha_emision.replace('Z', ''))
                else:
                    # Solo fecha, usar hora actual de Perú
                    fecha_date = datetime.strptime(data.fecha_emision, "%Y-%m-%d")
                    fecha_emision = fecha_date.replace(hour=peru_now.hour, minute=peru_now.minute, second=peru_now.second)
            except:
                fecha_emision = peru_now
        else:
            # Sin fecha, usar fecha y hora actual de Perú
            fecha_emision = peru_now

        print(f"📅 Fecha emisión: {fecha_emision}")  # Debug

        numero_formato = f"{serie}-{numero:08d}"
        
        comprobante = Comprobante(
            id=comprobante_id,
            emisor_id=emisor.id,
            cliente_id=cliente.id,
            tipo_documento=data.tipo_comprobante,
            tipo_operacion="0101",
            serie=serie,
            numero=numero,
            numero_formato=numero_formato,
            fecha_emision=fecha_emision,
            moneda="PEN",
            forma_pago=data.forma_pago or "Contado",
            monto_base=subtotal,
            monto_igv=igv_total,
            monto_total=total,
            op_gravada=subtotal if igv_total > 0 else Decimal('0.00'),
            op_exonerada=subtotal if igv_total == 0 else Decimal('0.00'),
            op_inafecta=Decimal('0.00'),
            estado="encolado",
            cliente_tipo_documento=data.cliente.tipo_documento,
            cliente_numero_documento=data.cliente.numero_documento,
            cliente_razon_social=data.cliente.razon_social,
            cliente_direccion=data.cliente.direccion or "",
            observaciones=data.codigo_matricula or data.observaciones,
            referencia_externa=data.referencia_externa
        )
        
        # Referencia para NC/ND
        if data.tipo_comprobante in ["07", "08"]:
            comprobante.doc_referencia_tipo = data.documento_ref_tipo
            comprobante.doc_referencia_numero = f"{data.documento_ref_serie}-{data.documento_ref_numero:08d}" if data.documento_ref_serie and data.documento_ref_numero else None
            comprobante.motivo_nota = data.motivo_nota
        
        db.add(comprobante)
        
        # === CREAR ITEMS ===
        for i, item_data in enumerate(items_data, 1):
            item = LineaDetalle(
                id=str(uuid4()),
                comprobante_id=comprobante_id,
                orden=i,
                codigo=f"ITEM{i:03d}",
                descripcion=item_data["descripcion"],
                cantidad=item_data["cantidad"],
                unidad=item_data["unidad_medida"],
                precio_unitario=item_data["precio_unitario"],
                valor_unitario=item_data["valor_unitario"],
                descuento=item_data["descuento"],
                subtotal=item_data["subtotal"],
                igv=item_data["igv"],
                monto_linea=item_data["total"],
                tipo_afectacion_igv=item_data["tipo_afectacion_igv"]
            )
            db.add(item)
        
        # === INCREMENTAR CONTADOR ===
        emisor.docs_mes_usados = (emisor.docs_mes_usados or 0) + 1
        
        # === ÚNICO COMMIT ===
        db.commit()
        
        # === ENVIAR A SUNAT VÍA CELERY ===
        from src.tasks.celery_app import celery_app
        celery_app.send_task('enviar_comprobante_sunat', args=[comprobante_id])
        
        # === RESPONSE ===
        response = {
            "exito": True,
            "comprobante": {
                "id": comprobante_id,
                "tipo": data.tipo_comprobante,
                "serie": serie,
                "numero": numero,
                "numero_formato": numero_formato,
                "fecha_emision": fecha_emision.strftime("%Y-%m-%d"),
                "cliente_documento": data.cliente.numero_documento,
                "cliente_nombre": data.cliente.razon_social,
                "subtotal": subtotal,
                "igv": igv_total,
                "total": total,
                "estado": "encolado",
                "hash_cpe": None,
                "codigo_sunat": None,
                "mensaje_sunat": "Comprobante encolado para envío a SUNAT"
            },
            "archivos": {
                "pdf_url": f"https://facturalo.pro/api/v1/comprobantes/{comprobante_id}/pdf",
                "xml_url": f"https://facturalo.pro/api/v1/comprobantes/{comprobante_id}/xml",
                "cdr_url": f"https://facturalo.pro/api/v1/comprobantes/{comprobante_id}/cdr"
            },
            "mensaje": "Comprobante encolado. Consulte estado con GET /api/v1/comprobantes/{id}"
        }
        
        # Log
        duracion = int((time.time() - inicio) * 1000)
        log_api_call(db, emisor.id, request, "/comprobantes", 200, response, duracion)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        duracion = int((time.time() - inicio) * 1000)
        error_response = {
            "exito": False,
            "error": "Error interno del servidor",
            "codigo": "INTERNAL_ERROR",
            "detalle": str(e)
        }
        log_api_call(db, emisor.id, request, "/comprobantes", 500, error_response, duracion)
        raise HTTPException(500, detail=error_response)


@router.get(
    "/{comprobante_id}",
    summary="Consultar comprobante",
    description="Obtiene los datos de un comprobante emitido por su ID"
)
async def consultar_comprobante(
    comprobante_id: str,
    request: Request,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Consulta un comprobante por ID"""
    comprobante = db.query(Comprobante).filter(
        Comprobante.id == comprobante_id,
        Comprobante.emisor_id == emisor.id
    ).first()
    
    if not comprobante:
        raise HTTPException(404, detail={
            "exito": False,
            "error": "Comprobante no encontrado",
            "codigo": "NOT_FOUND"
        })
    
    cliente = db.query(Cliente).filter(Cliente.id == comprobante.cliente_id).first()
    
    items = db.query(LineaDetalle).filter(
        LineaDetalle.comprobante_id == comprobante_id
    ).order_by(LineaDetalle.item_orden).all()
    
    return {
        "exito": True,
        "comprobante": {
            "id": comprobante.id,
            "tipo": comprobante.tipo_documento,
            "serie": comprobante.serie,
            "numero": comprobante.numero,
            "numero_formato": f"{comprobante.serie}-{comprobante.numero:08d}",
            "fecha_emision": comprobante.fecha_emision.strftime("%Y-%m-%d") if comprobante.fecha_emision else None,
            "cliente": {
                "tipo_documento": cliente.tipo_documento if cliente else None,
                "numero_documento": cliente.numero_documento if cliente else None,
                "razon_social": cliente.razon_social if cliente else None,
                "email": cliente.email if cliente else None
            },
            "items": [
                {
                    "descripcion": item.descripcion,
                    "cantidad": float(item.cantidad),
                    "unidad_medida": item.unidad_medida,
                    "precio_unitario": float(item.precio_unitario),
                    "subtotal": float(item.subtotal),
                    "igv": float(item.igv),
                    "total": float(item.total)
                }
                for item in items
            ],
            "subtotal": float(comprobante.op_gravada or 0) + float(comprobante.op_exonerada or 0),
            "igv": float(comprobante.igv or 0),
            "total": float(comprobante.total),
            "estado": comprobante.estado,
            "hash_cpe": comprobante.hash_cpe,
            "codigo_sunat": comprobante.codigo_sunat,
            "mensaje_sunat": comprobante.mensaje_sunat,
            "referencia_externa": comprobante.referencia_externa
        }
    }


"""
REEMPLAZA la función obtener_pdf en src/api/v1/comprobantes.py

También agrega este import al inicio del archivo:
from fastapi.responses import Response
from src.api.v1.pdf_generator import generar_pdf_comprobante
"""

"""
REEMPLAZA la función obtener_pdf en src/api/v1/comprobantes.py

Imports adicionales al inicio del archivo:
from fastapi.responses import Response
from src.api.v1.pdf_generator import generar_pdf_comprobante
"""

@router.get(
    "/{comprobante_id}/pdf",
    summary="Descargar PDF",
    description="Genera y descarga el PDF del comprobante"
)
async def obtener_pdf(
    comprobante_id: str,
    formato: str = "A4",
    codigo_matricula: str = None,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Genera y retorna el PDF del comprobante"""
    comprobante = db.query(Comprobante).filter(
        Comprobante.id == comprobante_id,
        Comprobante.emisor_id == emisor.id
    ).first()

    if not comprobante:
        raise HTTPException(404, detail={"exito": False, "error": "No encontrado", "codigo": "NOT_FOUND"})

    cliente = db.query(Cliente).filter(Cliente.id == comprobante.cliente_id).first()

    items = db.query(LineaDetalle).filter(
        LineaDetalle.comprobante_id == comprobante_id
    ).order_by(LineaDetalle.orden).all()

    fmt = formato.upper()
    if fmt not in ["A4", "A5", "TICKET"]:
        fmt = "A4"

    # Obtener matrícula de observaciones
    codigo_matricula = comprobante.observaciones if comprobante.observaciones and comprobante.observaciones.startswith("10-") else None

    # URL de consulta desde el emisor
    url_consulta = getattr(emisor, 'web', None)
    if url_consulta and not url_consulta.startswith("http"):
        url_consulta = url_consulta + "/consulta/habilidad"

    try:
        pdf_bytes = generar_pdf_comprobante(
            comprobante, emisor, cliente, items,
            formato=fmt,
            codigo_matricula=codigo_matricula,
            url_consulta=url_consulta,
        )
    except Exception as e:
        print(f"Error generando PDF: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, detail={"exito": False, "error": f"Error al generar PDF: {str(e)}"})

    # Cache en DB
    try:
        comprobante.pdf = pdf_bytes
        db.commit()
    except:
        pass

    num_doc_cliente = comprobante.cliente_numero_documento or ""
    filename = f"{comprobante.serie}-{comprobante.numero:08d}--{num_doc_cliente}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"'
        }
    )


@router.get(
    "/{comprobante_id}/xml",
    summary="Descargar XML",
    description="Obtiene la URL del XML firmado"
)
async def obtener_xml(
    comprobante_id: str,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Obtiene URL del XML"""
    comprobante = db.query(Comprobante).filter(
        Comprobante.id == comprobante_id,
        Comprobante.emisor_id == emisor.id
    ).first()
    
    if not comprobante:
        raise HTTPException(404, detail={"exito": False, "error": "No encontrado", "codigo": "NOT_FOUND"})
    
    return {
        "exito": True,
        "comprobante_id": comprobante_id,
        "numero": f"{comprobante.serie}-{comprobante.numero:08d}",
        "xml_url": f"/storage/xml/{comprobante_id}.xml"
    }


@router.post(
    "/anular",
    summary="Anular comprobante",
    description="Genera comunicación de baja para el comprobante"
)
async def anular_comprobante(
    data: AnularRequest,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Anula un comprobante"""
    comprobante = db.query(Comprobante).filter(
        Comprobante.id == data.comprobante_id,
        Comprobante.emisor_id == emisor.id
    ).first()
    
    if not comprobante:
        raise HTTPException(404, detail={"exito": False, "error": "No encontrado", "codigo": "NOT_FOUND"})
    
    if comprobante.estado == "anulado":
        raise HTTPException(400, detail={"exito": False, "error": "Ya está anulado", "codigo": "ALREADY_VOIDED"})
    
    # TODO: Generar comunicación de baja real
    comprobante.estado = "anulado"
    comprobante.observaciones = f"ANULADO: {data.motivo}"
    db.commit()
    
    return {
        "exito": True,
        "comprobante_id": data.comprobante_id,
        "estado": "anulado",
        "mensaje": "Comprobante anulado correctamente"
    }


@router.get(
    "/buscar/referencia/{referencia_externa}",
    summary="Buscar por referencia externa",
    description="Busca un comprobante por su referencia en el sistema origen"
)
async def buscar_por_referencia(
    referencia_externa: str,
    emisor: Emisor = Depends(verificar_api_key),
    db: Session = Depends(get_db)
):
    """Busca comprobante por referencia externa"""
    comprobante = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.referencia_externa == referencia_externa
    ).first()
    
    if not comprobante:
        raise HTTPException(404, detail={
            "exito": False,
            "error": f"No se encontró comprobante con referencia: {referencia_externa}",
            "codigo": "NOT_FOUND"
        })
    
    return {
        "exito": True,
        "comprobante": {
            "id": comprobante.id,
            "numero_formato": f"{comprobante.serie}-{comprobante.numero:08d}",
            "estado": comprobante.estado,
            "total": float(comprobante.total),
            "referencia_externa": comprobante.referencia_externa
        }
    }