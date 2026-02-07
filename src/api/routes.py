from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from fastapi import Request as FastAPIRequest
from fastapi import Cookie

from sqlalchemy import or_

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509
import base64

from datetime import datetime, date, timedelta, timezone
import io

import pandas as pd
from uuid import uuid4
from decimal import Decimal

from pydantic import BaseModel

from src.api.dependencies import get_db
from src.models.models import Comprobante, LineaDetalle, Emisor, Certificado, LogEnvio, RespuestaSunat, Cliente, Producto
from src.services.sunat_service import SunatService
from src.api.auth_utils import obtener_emisor_actual

# Importar tarea Celery
try:
    from src.tasks.envio_sunat import enviar_comprobante_task
    CELERY_DISPONIBLE = True
except ImportError:
    print("⚠️  Celery no disponible, usando procesamiento síncrono")
    CELERY_DISPONIBLE = False
    enviar_comprobante_task = None

from src.schemas.schemas import ComprobanteCreate, StandardResponse
from src.tasks.tasks import emitir_comprobante_task, reenviar_comprobante_task

from src.core.config import settings
from typing import Optional

from zipfile import ZipFile
from io import BytesIO
from fastapi.responses import Response

class ReenviarRechazadosRequest(BaseModel):
    emisor_ruc: str

router = APIRouter()

@router.get('/comprobantes/{comprobante_id}', response_model=StandardResponse)
def get_comprobante(comprobante_id: str, db: Session = Depends(get_db)):
    comp = db.query(Comprobante).filter_by(id=comprobante_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail='Comprobante no encontrado')
    
    # Obtener mensaje de error si fue rechazado
    error_msg = None
    if comp.respuesta:
        error_msg = comp.respuesta.descripcion
    
    datos = {
        'id': comp.id,
        'estado': comp.estado,
        'fecha_emision': comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else None,
        'monto_total': str(comp.monto_total),
        'error_mensaje': error_msg
    }
    return {"exito": True, "datos": datos, "mensaje": None}


# Agregar este endpoint si no existe
@router.get("/comprobantes/{comprobante_id}/xml")
def descargar_xml(comprobante_id: str, db: Session = Depends(get_db)):
    """Descarga el XML del comprobante"""
    
    # Buscar comprobante
    comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    # Verificar que tenga XML
    if not comprobante.xml:
        raise HTTPException(status_code=404, detail="XML no disponible")
    
    # Buscar emisor para el nombre del archivo
    emisor = db.query(Emisor).filter(Emisor.id == comprobante.emisor_id).first()
    
    # Construir nombre de archivo
    filename = f"{emisor.ruc}-{comprobante.tipo_documento}-{comprobante.serie}-{comprobante.numero}.xml"
    
    return Response(
        content=comprobante.xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/comprobantes/{comprobante_id}/cdr")
async def descargar_cdr(comprobante_id: str, db: Session = Depends(get_db)):
    """Descarga el CDR (Constancia de Recepción) de SUNAT"""
    from fastapi.responses import Response
    
    # Buscar comprobante
    comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    # Buscar respuesta SUNAT
    respuesta = db.query(RespuestaSunat).filter(
        RespuestaSunat.comprobante_id == comprobante_id
    ).first()
    
    if not respuesta or not respuesta.cdr_xml:
        raise HTTPException(status_code=404, detail="CDR no disponible")
    
    # Construir nombre de archivo
    filename = f"R-{comprobante.emisor_ruc}-{comprobante.tipo_comprobante}-{comprobante.serie}-{comprobante.numero}.xml"
    
    return Response(
        content=respuesta.cdr_xml.encode('utf-8') if isinstance(respuesta.cdr_xml, str) else respuesta.cdr_xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/comprobantes/{comprobante_id}/pdf")
def descargar_pdf(comprobante_id: str, db: Session = Depends(get_db)):
    """Descarga el PDF del comprobante"""
    from fastapi.responses import Response
    from src.services.pdf_generator import generar_pdf_comprobante
    
    # Buscar comprobante
    comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    # Buscar emisor
    emisor = db.query(Emisor).filter(Emisor.id == comprobante.emisor_id).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    # Buscar items del comprobante
    items = db.query(LineaDetalle).filter(
        LineaDetalle.comprobante_id == comprobante_id
    ).all()
    
    # TODO: Extraer datos de cliente del XML
    cliente_ruc = "00000000"
    cliente_nombre = "Cliente"
    cliente_direccion = "Lima, Perú"
    
    # Preparar datos para PDF
    comprobante_data = {
        "emisor_ruc": emisor.ruc,
        "emisor_razon_social": emisor.razon_social,
        "emisor_direccion": emisor.direccion or "Sin dirección",
        "emisor_logo": getattr(emisor, 'logo_url', None) or "",
        "emisor_telefono": getattr(emisor, 'telefono', None) or "",
        "emisor_email": getattr(emisor, 'email', None) or "",
        "emisor_web": getattr(emisor, 'web', None) or "",
        "emisor_lema": getattr(emisor, 'lema', None) or "",
        "emisor_establecimiento_anexo": getattr(emisor, 'establecimiento_anexo', None) or "",
        "es_agente_retencion": getattr(emisor, 'es_agente_retencion', False),
        "es_agente_percepcion": getattr(emisor, 'es_agente_percepcion', False),
        "color_primario": getattr(emisor, 'color_primario', None) or "#2c3e50",
        "color_secundario": getattr(emisor, 'color_secundario', None) or "#e74c3c",
        "tipo_comprobante": comprobante.tipo_documento,
        "serie": comprobante.serie,
        "numero": comprobante.numero,
        "fecha_emision": comprobante.fecha_emision,
        "cliente_ruc": cliente_ruc,
        "cliente_razon_social": cliente_nombre,
        "cliente_direccion": cliente_direccion,
        "items": [
            {
                "orden": item.orden,
                "descripcion": item.descripcion,
                "cantidad": float(item.cantidad),
                "unidad": item.unidad or "NIU",
                "precio_unitario": float(item.precio_unitario),
                "tipo_afectacion": getattr(item, 'tipo_afectacion_igv', None) or "10",
                "es_bonificacion": getattr(item, 'es_bonificacion', False)
            }
            for item in items
        ],
        "subtotal": comprobante.monto_base,
        "igv": comprobante.monto_igv,
        "total": comprobante.monto_total,
        "moneda": comprobante.moneda or "PEN",
        "observaciones": getattr(comprobante, 'observaciones', None) or "",
        "hash_cpe": "",
        "estado": comprobante.estado
    }
    
    try:
        # Generar PDF
        pdf_bytes = generar_pdf_comprobante(comprobante_data)
        
        # Construir nombre de archivo
        filename = f"{emisor.ruc}-{comprobante.tipo_documento}-{comprobante.serie}-{comprobante.numero}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {str(e)}")

@router.get("/comprobantes/buscar")
def buscar_comprobantes(
    emisor_ruc: str,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    serie: Optional[str] = None,
    estado: Optional[str] = None,
    tipo_comprobante: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Busca comprobantes con filtros"""
    
    # Validar limit
    if limit > 100:
        limit = 100
    
    # Query base
    query = db.query(Comprobante).filter(Comprobante.emisor_ruc == emisor_ruc)
    
    # Aplicar filtros
    if fecha_desde:
        query = query.filter(Comprobante.fecha_emision >= fecha_desde)
    if fecha_hasta:
        query = query.filter(Comprobante.fecha_emision <= fecha_hasta)
    if serie:
        query = query.filter(Comprobante.serie == serie)
    if estado:
        query = query.filter(Comprobante.estado == estado)
    if tipo_comprobante:
        query = query.filter(Comprobante.tipo_comprobante == tipo_comprobante)
    
    # Total
    total = query.count()
    
    # Paginación y orden
    comprobantes = query.order_by(
        Comprobante.fecha_emision.desc(),
        Comprobante.numero.desc()
    ).limit(limit).offset(offset).all()
    
    # Formatear respuesta
    items = [
        {
            "id": str(c.id),
            "serie": c.serie,
            "numero": c.numero,
            "fecha_emision": c.fecha_emision.strftime("%d/%m/%Y"),
            "monto_total": str(c.monto_total),
            "estado": c.estado,
            "tipo_comprobante": c.tipo_comprobante,
            "cliente_razon_social": c.cliente_razon_social
        }
        for c in comprobantes
    ]
    
    return {
        "exito": True,
        "datos": {
            "total": total,
            "items": items,
            "limit": limit,
            "offset": offset
        },
        "mensaje": None
    }


@router.post("/comprobantes/{comprobante_id}/reenviar")
async def reenviar_comprobante(
    comprobante_id: str,
    db: Session = Depends(get_db)
):
    """Reenvía un comprobante rechazado o con error"""
    
    # Verificar que el comprobante existe
    comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    # Validar que no esté aceptado
    if comprobante.estado == "aceptado":
        raise HTTPException(
            status_code=400,
            detail="El comprobante ya fue aceptado, no se puede reenviar"
        )
    
    # Actualizar estado
    comprobante.estado = "enviando"
    db.commit()
    
    # Encolar tarea (usar la misma que emitir)
    try:
        if CELERY_DISPONIBLE:
            from src.tasks.celery_app import celery_app
            celery_app.send_task('enviar_comprobante_sunat', args=[comprobante_id])
            return {
                "exito": True,
                "mensaje": "Comprobante encolado para reenvío"
            }
        else:
            # Envío síncrono
            from src.services.sunat_service import SunatService
            sunat = SunatService(db)
            resultado = sunat.enviar_comprobante(comprobante_id)
            return {
                "exito": resultado.get('exito', False),
                "mensaje": resultado.get('mensaje', 'Procesado')
            }
    except Exception as e:
        return {
            "exito": False,
            "mensaje": f"Error: {str(e)}"
        }


@router.post("/comprobantes/reenviar-rechazados")
async def reenviar_todos_rechazados(
    request: ReenviarRechazadosRequest,
    db: Session = Depends(get_db)
):
    """Reenviar todos los comprobantes rechazados de hoy"""
    
    emisor = db.query(Emisor).filter(Emisor.ruc == request.emisor_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    

    limite_reintento = datetime.now() - timedelta(minutes=1)
    
    rechazados = (
        db.query(Comprobante)
        .filter(
            Comprobante.emisor_id == emisor.id,
            Comprobante.estado == "rechazado",
            Comprobante.fecha_emision == date.today(),
            or_(
                Comprobante.ultimo_intento_envio.is_(None),
                Comprobante.ultimo_intento_envio < limite_reintento,
            ),
        )
        .all()
    )
    
    if not rechazados:
        # Verificar si hay algunos procesando
        procesando = db.query(Comprobante).filter(
            Comprobante.emisor_id == emisor.id,
            Comprobante.estado == 'enviando'
        ).count()
        
        if procesando > 0:
            return {
                "exito": True,
                "total": 0,
                "mensaje": f"Ya hay {procesando} comprobantes procesándose. Espera a que terminen.",
                "procesando": procesando
            }
        else:
            return {
                "exito": True,
                "total": 0,
                "mensaje": "No hay comprobantes rechazados para reenviar"
            }
    
    reenviados = 0
    ahora = datetime.now()
    
    # Marcar todos como procesando PRIMERO
    for comp in rechazados:
        comp.estado = 'enviando'
        comp.procesando_desde = ahora
        comp.ultimo_intento_envio = ahora
        comp.intentos_envio = (comp.intentos_envio or 0) + 1
    
    db.commit()
    
    # Luego encolar tareas
    if CELERY_DISPONIBLE and enviar_comprobante_task:
        for comp in rechazados:
            try:
                tarea_id = str(uuid4())
                enviar_comprobante_task.apply_async(
                    args=[comp.id],
                    task_id=tarea_id
                )
                reenviados += 1
            except Exception as e:
                print(f"Error encolando {comp.id}: {e}")
                comp.estado = 'error'
                comp.descripcion_respuesta = f"Error al encolar: {str(e)}"
                comp.procesando_desde = None
    else:
        # Procesamiento síncrono
        from src.services.sunat_service import SunatService
        sunat_service = SunatService(db)
        
        for comp in rechazados:
            try:
                resultado = sunat_service.enviar_comprobante(comp.id)
                if resultado.get('exito'):
                    reenviados += 1
            except Exception as e:
                print(f"Error procesando {comp.id}: {e}")
                comp.estado = 'error'
                comp.descripcion_respuesta = str(e)
            finally:
                comp.procesando_desde = None
    
    db.commit()
    
    modo = "asíncrono" if CELERY_DISPONIBLE else "síncrono"
    tiempo_estimado = len(rechazados) * 5 if CELERY_DISPONIBLE else len(rechazados) * 5
    
    return {
        "exito": True,
        "total": reenviados,
        "mensaje": f"{reenviados} comprobantes en cola para reenvío ({modo})",
        "tiempo_estimado_segundos": tiempo_estimado
    }


@router.get("/clientes/template")
def descargar_template_clientes():
    """Descargar template Excel para importar clientes"""
    
    # Crear DataFrame con columnas
    df = pd.DataFrame(columns=[
        'tipo_documento',
        'numero_documento', 
        'razon_social',
        'direccion',
        'email',
        'telefono'
    ])
    
    # Agregar filas de ejemplo
    df.loc[0] = ['6', '20123456789', 'COMERCIAL IQUITOS SAC', 'Av. Abelardo Quiñones 1234, Iquitos', 'contacto@comercial.com', '065-234567']
    df.loc[1] = ['1', '12345678', 'JUAN PEREZ GARCIA', 'Jr. Próspero 456, Iquitos', 'juan@email.com', '987654321']
    
    # Convertir a Excel en memoria
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Clientes')
    
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=template_clientes.xlsx'}
    )


@router.post("/clientes/importar")
async def importar_clientes_excel(
    archivo: UploadFile = File(...),
    emisor_ruc: str = Form(...),
    db: Session = Depends(get_db)
):
    """Importar clientes desde archivo Excel o CSV"""
    
    # Buscar emisor
    emisor = db.query(Emisor).filter(Emisor.ruc == emisor_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    try:
        # Leer archivo según extensión
        if archivo.filename.endswith('.csv'):
            df = pd.read_csv(archivo.file)
        elif archivo.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(archivo.file)
        else:
            return {
                "exito": False,
                "error": "Formato no soportado. Use Excel (.xlsx) o CSV (.csv)"
            }
        
        # Validar columnas requeridas
        required_cols = ['numero_documento', 'razon_social']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            return {
                "exito": False,
                "error": f"Faltan columnas requeridas: {', '.join(missing_cols)}"
            }
        
        importados = 0
        actualizados = 0
        errores = []
        
        for idx, row in df.iterrows():
            try:
                # Validar número de documento
                numero_doc = str(row['numero_documento']).strip()
                if not numero_doc or numero_doc == 'nan':
                    errores.append(f"Fila {idx+2}: Número de documento vacío")
                    continue
                
                # Verificar si ya existe
                cliente_existe = db.query(Cliente).filter(
                    Cliente.emisor_id == emisor.id,
                    Cliente.numero_documento == numero_doc
                ).first()
                
                if cliente_existe:
                    # Actualizar cliente existente
                    cliente_existe.razon_social = str(row['razon_social'])
                    cliente_existe.direccion = str(row.get('direccion', ''))
                    cliente_existe.email = str(row.get('email', ''))
                    cliente_existe.telefono = str(row.get('telefono', ''))
                    actualizados += 1
                else:
                    # Crear nuevo cliente
                    cliente = Cliente(
                        emisor_id=emisor.id,
                        tipo_documento=str(row.get('tipo_documento', '6')),
                        numero_documento=numero_doc,
                        razon_social=str(row['razon_social']),
                        direccion=str(row.get('direccion', '')),
                        email=str(row.get('email', '')),
                        telefono=str(row.get('telefono', ''))
                    )
                    db.add(cliente)
                    importados += 1
                
            except Exception as e:
                errores.append(f"Fila {idx+2}: {str(e)}")
        
        db.commit()
        
        return {
            "exito": True,
            "importados": importados,
            "actualizados": actualizados,
            "errores": errores[:10],  # Máximo 10 errores
            "total_errores": len(errores)
        }
        
    except Exception as e:
        return {
            "exito": False,
            "error": f"Error procesando archivo: {str(e)}"
        }
    

@router.get("/comprobantes/progreso-reenvio/{emisor_ruc}")
def obtener_progreso_reenvio(
    emisor_ruc: str,
    db: Session = Depends(get_db)
):
    """
    Obtener progreso de reenvíos en tiempo real
    Retorna cuántos están procesando, cuántos terminaron, etc.
    """
    
    emisor = db.query(Emisor).filter(Emisor.ruc == emisor_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    # Buscar comprobantes de hoy
    hoy = date.today()
    
    # Estados
    total_rechazados = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision == hoy,
        Comprobante.estado == 'rechazado'
    ).count()
    
    procesando = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision == hoy,
        Comprobante.estado == 'enviando'
    ).count()
    
    aceptados_hoy = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision == hoy,
        Comprobante.estado == 'aceptado',
        Comprobante.ultimo_intento_envio.isnot(None),
        Comprobante.ultimo_intento_envio >= datetime.now() - timedelta(minutes=5)
    ).count()
    
    # Detectar atorados (más de 30 segundos procesando)
    atorados = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.estado == 'enviando',
        Comprobante.procesando_desde.isnot(None),
        Comprobante.procesando_desde < datetime.now() - timedelta(seconds=30)
    ).all()
    
    # Marcar atorados como error
    for comp in atorados:
        comp.estado = 'error'
        comp.descripcion_respuesta = 'Timeout: Procesamiento demoró más de 30 segundos'
        comp.procesando_desde = None
    
    if atorados:
        db.commit()
    
    return {
        "procesando": procesando,
        "rechazados": total_rechazados,
        "recien_aceptados": aceptados_hoy,
        "atorados": len(atorados),
        "total_original": procesando + total_rechazados + aceptados_hoy,
        "progreso_porcentaje": int((aceptados_hoy / (procesando + total_rechazados + aceptados_hoy)) * 100) if (procesando + total_rechazados + aceptados_hoy) > 0 else 0
    }

class ItemEmitir(BaseModel):
    descripcion: str
    cantidad: float
    precio_unitario: float
    unidad_medida: str = "NIU"
    orden: Optional[int] = None
    unidad: Optional[str] = None

class EmitirComprobanteRequest(BaseModel):
    tipo_documento: str
    serie: str
    cliente_tipo_doc: str = "6"
    cliente_numero_doc: str
    cliente_razon_social: str
    items: list[ItemEmitir]
    cliente_direccion: str = ""
    moneda: str = "PEN"
    observaciones: str = ""
    # Opcionales - se generan en backend
    emisor_ruc: Optional[str] = None
    numero: Optional[int] = None
    fecha_emision: Optional[str] = None

@router.post("/comprobantes/emitir")
async def emitir_comprobante(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Emitir nuevo comprobante electrónico"""
    from uuid import uuid4
    
    # Recibir JSON directamente (sin Pydantic)
    data = await request.json()

    # DEBUG: Ver qué datos llegan
    print(f"DEBUG EMITIR - Data recibida: {data}")
    print(f"DEBUG EMITIR - Items: {data.get('items', [])}")
    
    # Extraer campos
    tipo_documento = data.get('tipo_documento', '01')
    serie = data.get('serie', 'F001')
    cliente_tipo_doc = data.get('cliente_tipo_doc', '6')
    cliente_numero_doc = data.get('cliente_numero_doc', '')
    cliente_razon_social = data.get('cliente_razon_social', '')
    cliente_direccion = data.get('cliente_direccion', '')
    items = data.get('items', [])
    moneda = data.get('moneda', 'PEN')
    observaciones = data.get('observaciones', '')
    
    # Validar campos requeridos
    if not cliente_numero_doc:
        raise HTTPException(status_code=400, detail="Número de documento del cliente es requerido")
    if not cliente_razon_social:
        raise HTTPException(status_code=400, detail="Razón social del cliente es requerida")
    if not items:
        raise HTTPException(status_code=400, detail="Debe incluir al menos un item")
    
    emisor = await obtener_emisor_actual(request, db)

    if not emisor:
        raise HTTPException(status_code=404, detail="No hay emisor configurado")
    
    # Obtener siguiente número (máximo actual + 1)
    from sqlalchemy import func
    
    max_numero = db.query(func.max(Comprobante.numero)).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.serie == serie,
        Comprobante.tipo_documento == tipo_documento
    ).scalar()
    
    siguiente_numero = (max_numero + 1) if max_numero else 1

    # Verificar que no exista (prevenir duplicados por concurrencia)
    existe = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.serie == serie,
        Comprobante.tipo_documento == tipo_documento,
        Comprobante.numero == siguiente_numero
    ).first()

    if existe:
        # Si existe, buscar el siguiente disponible
        max_real = db.query(func.max(Comprobante.numero)).filter(
            Comprobante.emisor_id == emisor.id,
            Comprobante.serie == serie,
            Comprobante.tipo_documento == tipo_documento
        ).scalar()
        siguiente_numero = (max_real + 1) if max_real else 1
        print(f"WARNING: Número duplicado detectado, usando {siguiente_numero}")
    
    # Log para debug
    print(f"DEBUG: Serie={serie}, Tipo={tipo_documento}, MaxActual={max_numero}, Siguiente={siguiente_numero}")
    
    # Calcular totales
    # Calcular totales según tipo de afectación
    subtotal_gravado = 0
    subtotal_exonerado = 0
    subtotal_inafecto = 0
    
    for item in items:
        cantidad = float(item.get('cantidad', 0))
        precio = float(item.get('precio_unitario', 0))
        tipo_igv = item.get('tipo_afectacion_igv', '10')
        monto = cantidad * precio

        print(f"DEBUG ITEM: cant={cantidad}, precio={precio}, tipo={tipo_igv}, monto={monto}")
        
        if tipo_igv == '10':  # Gravado
            subtotal_gravado += monto
        elif tipo_igv == '20':  # Exonerado
            subtotal_exonerado += monto
        else:  # Inafecto
            subtotal_inafecto += monto
    
    subtotal = subtotal_gravado  # Base imponible solo gravado
    igv = round(subtotal_gravado * 0.18, 2)
    total = round(subtotal_gravado + igv + subtotal_exonerado + subtotal_inafecto, 2)
    
    igv = round(subtotal * 0.18, 2)
    total = round(subtotal + igv, 2)
    
    peru_tz = timezone(timedelta(hours=-5))
    fecha_peru = datetime.now(peru_tz).date()

    # Crear comprobante
    comprobante = Comprobante(
        id=str(uuid4()),
        emisor_id=emisor.id,
        tipo_documento=tipo_documento,
        serie=serie,
        numero=siguiente_numero,
        numero_formato=f"{serie}-{str(siguiente_numero).zfill(8)}",
        fecha_emision=fecha_peru,
        cliente_tipo_documento=cliente_tipo_doc,
        cliente_numero_documento=cliente_numero_doc,
        cliente_razon_social=cliente_razon_social,
        cliente_direccion=cliente_direccion,
        cliente_departamento=data.get('cliente_departamento', ''),
        cliente_provincia=data.get('cliente_provincia', ''),
        cliente_distrito=data.get('cliente_distrito', ''),
        cliente_ubigeo=data.get('cliente_ubigeo', ''),
        moneda=moneda,
        monto_base=subtotal,
        monto_igv=igv,
        monto_total=total,
        estado='pendiente',
        observaciones=observaciones
    )
    
    db.add(comprobante)
    
    # Crear líneas de detalle
    for i, item in enumerate(items, 1):
        cantidad = float(item.get('cantidad', 1))
        precio = float(item.get('precio_unitario', 0))
        monto_linea = round(cantidad * precio, 2)
        
        linea = LineaDetalle(
            id=str(uuid4()),
            comprobante_id=comprobante.id,
            orden=i,
            descripcion=item.get('descripcion', ''),
            cantidad=cantidad,
            unidad=item.get('unidad_medida', 'NIU'),
            precio_unitario=precio,
            monto_linea=monto_linea,
            tipo_afectacion_igv=item.get('tipo_afectacion_igv', '10'),  # ← Del formulario
            es_bonificacion=False
        )
        db.add(linea)
    
    db.commit()
    
    # Encolar envío a SUNAT automáticamente
    # Encolar envío a SUNAT automáticamente
    try:
        if CELERY_DISPONIBLE:
            from src.tasks.celery_app import celery_app
            celery_app.send_task('enviar_comprobante_sunat', args=[comprobante.id])
            comprobante.estado = 'enviando'
            db.commit()
            print(f"DEBUG: Tarea enviar_comprobante_sunat encolada para {comprobante.id}")
        else:
            # Envío síncrono si no hay Celery
            from src.services.sunat_service import SunatService
            sunat_service = SunatService(db)
            resultado = sunat_service.enviar_comprobante(comprobante.id)
            if resultado.get('exito'):
                comprobante.estado = 'aceptado'
            else:
                comprobante.estado = 'rechazado'
            db.commit()
            print(f"DEBUG: Envío síncrono resultado: {resultado}")
    except Exception as e:
        print(f"ERROR al encolar envío SUNAT: {e}")
        # No fallar la emisión si falla el envío
    
    return {
        "exito": True,
        "mensaje": f"Comprobante {serie}-{str(siguiente_numero).zfill(8)} creado y enviado a SUNAT",
        "comprobante_id": comprobante.id,
        "serie": serie,
        "numero": siguiente_numero
    }


from src.services.consulta_ruc import consultar_ruc, consultar_dni

@router.get("/consulta/ruc/{numero}")
def api_consultar_ruc(numero: str):
    """Consulta RUC en SUNAT"""
    resultado = consultar_ruc(numero)
    if resultado and resultado.get('encontrado'):
        return {"exito": True, "datos": resultado}
    return {"exito": False, "mensaje": "RUC no encontrado"}


@router.get("/consulta/dni/{numero}")
def api_consultar_dni(numero: str):
    """Consulta DNI en RENIEC"""
    resultado = consultar_dni(numero)
    if resultado and resultado.get('encontrado'):
        return {"exito": True, "datos": resultado}
    return {"exito": False, "mensaje": "DNI no encontrado"}



@router.post("/configuracion/certificado")
async def subir_certificado(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Sube y valida un certificado digital"""
    from uuid import uuid4
    import io
    
    # Obtener datos del form
    form = await request.form()
    archivo = form.get("archivo")
    password = form.get("password")
    
    if not archivo or not password:
        raise HTTPException(status_code=400, detail="Archivo y contraseña son requeridos")
    
    # Obtener emisor de la sesión
    emisor = await obtener_emisor_actual(request, db)
    
    # Leer archivo
    contenido = await archivo.read()
    
    # Validar certificado
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        
        # Intentar cargar el .pfx con la contraseña
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            contenido,
            password.encode(),
            default_backend()
        )
        
        if not certificate:
            raise HTTPException(status_code=400, detail="El archivo no contiene un certificado válido")
        
        # Extraer información
        fecha_vencimiento = certificate.not_valid_after_utc.date()
        serial_number = str(certificate.serial_number)
        
        # Verificar que no esté vencido
        from datetime import date
        if fecha_vencimiento < date.today():
            raise HTTPException(
                status_code=400, 
                detail=f"El certificado está vencido (venció el {fecha_vencimiento.strftime('%d/%m/%Y')})"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer certificado: Contraseña incorrecta o archivo inválido")
    
    # Encriptar contenido y contraseña
    from src.core.config import settings
    
    # Crear clave Fernet desde encryption_key
    key = settings.encryption_key.encode()
    # Asegurar que sea base64 válido de 32 bytes
    if len(key) < 32:
        key = base64.urlsafe_b64encode(key.ljust(32)[:32])
    fernet = Fernet(key)
    
    pfx_encriptado = fernet.encrypt(contenido)
    password_encriptado = fernet.encrypt(password.encode())
    
    # Desactivar certificados anteriores
    db.query(Certificado).filter(
        Certificado.emisor_id == emisor.id
    ).update({"activo": False})
    
    # Crear nuevo certificado
    nuevo_cert = Certificado(
        id=str(uuid4()),
        emisor_id=emisor.id,
        pfx_encriptado=pfx_encriptado,
        password_encriptado=password_encriptado,
        serial_number=serial_number,
        fecha_vencimiento=fecha_vencimiento,
        activo=True
    )
    
    db.add(nuevo_cert)
    db.commit()

    # Auto-activar producción si tiene certificado Y credenciales SOL
    if emisor.usuario_sol:
        emisor.modo_test = False
        db.commit()
    
    return {
        "exito": True,
        "mensaje": f"Certificado cargado correctamente. Válido hasta {fecha_vencimiento.strftime('%d/%m/%Y')}",
        "datos": {
            "fecha_vencimiento": fecha_vencimiento.isoformat(),
            "serial_number": serial_number[:20] + "..."
        }
    }


@router.post("/configuracion/credenciales-sol")
async def guardar_credenciales_sol(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Guarda las credenciales SOL"""
    data = await request.json()
    
    emisor = await obtener_emisor_actual(request, db)
    
    # Actualizar credenciales
    emisor.usuario_sol = data.get('usuario_sol')
    
    if data.get('clave_sol'):
        # Encriptar clave SOL
        from src.core.config import settings
        key = settings.encryption_key.encode()
        if len(key) < 32:
            key = base64.urlsafe_b64encode(key.ljust(32)[:32])
        fernet = Fernet(key)
        emisor.clave_sol = fernet.encrypt(data['clave_sol'].encode()).decode()
    
    db.commit()

    # Auto-activar producción si tiene certificado Y credenciales SOL
    certificado_activo = db.query(Certificado).filter(
        Certificado.emisor_id == emisor.id,
        Certificado.activo == True
    ).first()

    if certificado_activo and emisor.usuario_sol:
        emisor.modo_test = False
        db.commit()
    
    return {
        "exito": True,
        "mensaje": "Credenciales guardadas correctamente"
    }


@router.get("/comprobantes/{comprobante_id}/detalle")
def get_comprobante_detalle(comprobante_id: str, db: Session = Depends(get_db)):
    """Obtiene el detalle completo de un comprobante"""
    comp = db.query(Comprobante).filter_by(id=comprobante_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail='Comprobante no encontrado')
    
    # Obtener emisor
    emisor = db.query(Emisor).filter_by(id=comp.emisor_id).first()
    
    # Obtener items
    items = db.query(LineaDetalle).filter_by(comprobante_id=comprobante_id).order_by(LineaDetalle.orden).all()
    
    # Tipo de documento nombre
    tipos_doc = {
        '01': 'FACTURA ELECTRÓNICA',
        '03': 'BOLETA DE VENTA ELECTRÓNICA',
        '07': 'NOTA DE CRÉDITO',
        '08': 'NOTA DE DÉBITO'
    }
    
    # Respuesta SUNAT
    respuesta_sunat = None
    if comp.respuesta:
        respuesta_sunat = comp.respuesta.descripcion
    
    datos = {
        'id': comp.id,
        'tipo_documento': comp.tipo_documento,
        'tipo_documento_nombre': tipos_doc.get(comp.tipo_documento, 'COMPROBANTE'),
        'serie': comp.serie,
        'numero': comp.numero,
        'numero_formato': comp.numero_formato or f"{comp.serie}-{str(comp.numero).zfill(8)}",
        'fecha_emision': comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else '',
        'moneda': comp.moneda or 'PEN',
        'estado': comp.estado,
        'monto_base': float(comp.monto_base or 0),
        'monto_igv': float(comp.monto_igv or 0),
        'monto_total': float(comp.monto_total or 0),
        'cliente_tipo_documento': comp.cliente_tipo_documento,
        'cliente_numero_documento': comp.cliente_numero_documento,
        'cliente_razon_social': comp.cliente_razon_social,
        'cliente_direccion': comp.cliente_direccion,
        'observaciones': comp.observaciones,
        'emisor_ruc': emisor.ruc if emisor else '',
        'emisor_razon_social': emisor.razon_social if emisor else '',
        'emisor_direccion': emisor.direccion if emisor else '',
        'respuesta_sunat': respuesta_sunat,
        'items': [
            {
                'orden': item.orden,
                'descripcion': item.descripcion,
                'cantidad': float(item.cantidad),
                'unidad': item.unidad,
                'precio_unitario': float(item.precio_unitario),
                'monto_linea': float(item.monto_linea or 0)
            }
            for item in items
        ]
    }
    
    return {"exito": True, "datos": datos}


@router.post("/configuracion/formato")
async def guardar_formato(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Guarda los formatos de impresión por tipo de documento"""
    data = await request.json()
    
    emisor = await obtener_emisor_actual(request, db)
    
    formatos_validos = ['A4', 'A5', 'TICKET']
    
    # Actualizar cada formato si viene en el request
    if 'formato_factura' in data and data['formato_factura'] in formatos_validos:
        emisor.formato_factura = data['formato_factura']
    
    if 'formato_boleta' in data and data['formato_boleta'] in formatos_validos:
        emisor.formato_boleta = data['formato_boleta']
    
    if 'formato_ticket' in data and data['formato_ticket'] in formatos_validos:
        emisor.formato_ticket = data['formato_ticket']
    
    if 'formato_nc_nd' in data and data['formato_nc_nd'] in formatos_validos:
        emisor.formato_nc_nd = data['formato_nc_nd']
    
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Formatos guardados correctamente"
    }

@router.post("/comprobantes/nota-credito")
async def emitir_nota_credito(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Emite una Nota de Crédito"""
    from uuid import uuid4
    from datetime import datetime, timedelta, timezone
    
    data = await request.json()
    
    emisor = await obtener_emisor_actual(request, db)
    
    # Validar comprobante de referencia
    comprobante_ref_id = data.get('comprobante_ref_id')
    if not comprobante_ref_id:
        raise HTTPException(status_code=400, detail="Debe seleccionar un comprobante de referencia")
    
    comprobante_ref = db.query(Comprobante).filter(Comprobante.id == comprobante_ref_id).first()
    if not comprobante_ref:
        raise HTTPException(status_code=404, detail="Comprobante de referencia no encontrado")
    
    # Validar que sea Factura o Boleta
    if comprobante_ref.tipo_documento not in ['01', '03']:
        raise HTTPException(status_code=400, detail="Solo se puede emitir NC para Facturas o Boletas")
    
    # Determinar serie NC
    serie = data.get('serie', 'FC01')
    tipo_documento = '07'  # Nota de Crédito
    
    # Obtener siguiente número
    from sqlalchemy import func
    max_numero = db.query(func.max(Comprobante.numero)).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.serie == serie,
        Comprobante.tipo_documento == tipo_documento
    ).scalar()
    siguiente_numero = (max_numero + 1) if max_numero else 1
    
    # Validar items
    items = data.get('items', [])
    if not items:
        raise HTTPException(status_code=400, detail="Debe incluir al menos un item")
    
    # Calcular totales
    subtotal_gravado = 0
    for item in items:
        cantidad = float(item.get('cantidad', 0))
        precio = float(item.get('precio_unitario', 0))
        subtotal_gravado += cantidad * precio
    
    igv = round(subtotal_gravado * 0.18, 2)
    total = round(subtotal_gravado + igv, 2)
    
    # Zona horaria Perú
    peru_tz = timezone(timedelta(hours=-5))
    fecha_peru = datetime.now(peru_tz).date()
    
    # Crear NC
    nc = Comprobante(
        id=str(uuid4()),
        emisor_id=emisor.id,
        tipo_documento=tipo_documento,
        serie=serie,
        numero=siguiente_numero,
        numero_formato=f"{serie}-{str(siguiente_numero).zfill(8)}",
        fecha_emision=fecha_peru,
        cliente_tipo_documento=comprobante_ref.cliente_tipo_documento,
        cliente_numero_documento=comprobante_ref.cliente_numero_documento,
        cliente_razon_social=comprobante_ref.cliente_razon_social,
        cliente_direccion=comprobante_ref.cliente_direccion,
        moneda=comprobante_ref.moneda or 'PEN',
        monto_base=subtotal_gravado,
        monto_igv=igv,
        monto_total=total,
        estado='pendiente',
        observaciones=data.get('observaciones', ''),
        # Campos de referencia NC
        doc_referencia_tipo=comprobante_ref.tipo_documento,
        doc_referencia_numero=comprobante_ref.numero_formato,
        motivo_nota=data.get('motivo', '01')
    )
    
    db.add(nc)
    
    # Crear líneas de detalle
    for i, item in enumerate(items, 1):
        cantidad = float(item.get('cantidad', 1))
        precio = float(item.get('precio_unitario', 0))
        monto_linea = round(cantidad * precio, 2)
        
        linea = LineaDetalle(
            id=str(uuid4()),
            comprobante_id=nc.id,
            orden=i,
            descripcion=item.get('descripcion', ''),
            cantidad=cantidad,
            unidad=item.get('unidad_medida', 'NIU'),
            precio_unitario=precio,
            monto_linea=monto_linea,
            tipo_afectacion_igv=item.get('tipo_afectacion_igv', '10'),
            es_bonificacion=False
        )
        db.add(linea)
    
    db.commit()
    
    # Encolar envío a SUNAT
    try:
        if CELERY_DISPONIBLE:
            from src.tasks.celery_app import celery_app
            celery_app.send_task('enviar_comprobante_sunat', args=[nc.id])
            nc.estado = 'enviando'
            db.commit()
    except Exception as e:
        print(f"ERROR al encolar NC: {e}")
    
    return {
        "exito": True,
        "mensaje": f"Nota de Crédito {serie}-{str(siguiente_numero).zfill(8)} emitida",
        "comprobante_id": nc.id
    }