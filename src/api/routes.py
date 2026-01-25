from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from sqlalchemy import or_


from datetime import datetime, date, timedelta
import io

import pandas as pd
from uuid import uuid4
from decimal import Decimal

from pydantic import BaseModel

from src.api.dependencies import get_db
from src.models.models import Comprobante, LineaDetalle, Emisor, Certificado, LogEnvio, RespuestaSunat, Cliente, Producto
from src.services.sunat_service import SunatService

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

@router.post('/certificado/upload', response_model=StandardResponse)
async def upload_certificado(emisor_ruc: str = Form(...), password: str = Form(...), archivo: UploadFile = File(...), sol_usuario: str | None = Form(None), sol_password: str | None = Form(None), db: Session = Depends(get_db)):
    # Buscar emisor
    emisor = db.query(Emisor).filter_by(ruc=emisor_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail='Emisor no encontrado')
    # read uploaded PFX
    content = await archivo.read()
    # deactivate existing active certificates
    db.query(Certificado).filter_by(emisor_id=emisor.id, activo=True).update({'activo': False})
    # attempt to extract serial and expiration
    try:
        from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
        pk, cert, add = load_key_and_certificates(content, password.encode() if password else None)
        serial = str(cert.serial_number) if cert else None
        fecha_venc = cert.not_valid_after_utc.date() if cert else None
    except Exception:
        serial = None
        fecha_venc = None
    # encrypt and store
    from cryptography.fernet import Fernet
    f = Fernet(settings.encryption_key.encode())
    pfx_enc = f.encrypt(content)
    pwd_enc = f.encrypt(password.encode() if password else b'')
    cert_obj = Certificado(emisor_id=emisor.id, pfx_encriptado=pfx_enc, password_encriptado=pwd_enc, serial_number=serial, fecha_vencimiento=fecha_venc, activo=True)
    db.add(cert_obj)
    # update emisor SOL credentials if provided
    if sol_usuario is not None:
        emisor.sol_usuario = sol_usuario
    if sol_password is not None:
        emisor.sol_password = sol_password
    db.commit()
    db.refresh(cert_obj)
    return {"exito": True, "datos": {"id": cert_obj.id}, "mensaje": "Certificado cargado"}

@router.post('/comprobantes/emitir', response_model=StandardResponse)
def emitir_comprobante_endpoint(
    payload: ComprobanteCreate,
    db: Session = Depends(get_db)
):
    """Emite un comprobante electrónico"""
    
    # Buscar emisor
    emisor = db.query(Emisor).filter_by(ruc=payload.emisor_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail='Emisor no encontrado')

    # Parse fecha dd/mm/YYYY -> date
    if '/' in payload.fecha_emision:
        d, m, y = payload.fecha_emision.split('/')
        fecha_obj = datetime(int(y), int(m), int(d)).date()
    else:
        fecha_obj = datetime.fromisoformat(payload.fecha_emision).date()

    # Calcular totales
    monto_base = Decimal('0.00')
    for it in payload.items:
        monto_base += (Decimal(it.cantidad) * Decimal(it.precio_unitario))

    # Calcular IGV (18%)
    monto_igv = monto_base * Decimal('0.18')
    monto_total = monto_base + monto_igv

    # Crear comprobante
    comp = Comprobante(
        emisor_id=emisor.id,
        tipo_documento=payload.tipo_documento,
        serie=payload.serie,
        numero=payload.numero or 1,
        numero_formato=f"{payload.serie}-{(payload.numero or 1)}",
        fecha_emision=fecha_obj,
        moneda=payload.moneda or 'PEN',
        monto_base=monto_base,
        monto_igv=monto_igv,
        monto_total=monto_total,
        estado='encolado'
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)

    # Insert lineas
    orden = 1
    for it in payload.items:
        monto_linea = Decimal(it.cantidad) * Decimal(it.precio_unitario)
        linea = LineaDetalle(
            comprobante_id=comp.id,
            orden=orden,
            cantidad=it.cantidad,
            unidad=it.unidad,
            descripcion=it.descripcion,
            precio_unitario=it.precio_unitario,
            monto_linea=monto_linea
        )
        db.add(linea)
        orden += 1
    db.commit()

    # Encolar en Celery
    try:
        from src.tasks.tasks import emitir_comprobante_task
        emitir_comprobante_task.delay(str(comp.id), settings.test_mode)
    except Exception as e:
        # If Celery not available, log but don't fail
        print(f"Warning: Could not enqueue task: {e}")

    return {
        "exito": True, 
        "datos": {"id": str(comp.id)}, 
        "mensaje": "Encolado"
    }


@router.get('/comprobantes/{comprobante_id}', response_model=StandardResponse)
def get_comprobante(comprobante_id: str, db: Session = Depends(get_db)):
    comp = db.query(Comprobante).filter_by(id=comprobante_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail='Comprobante no encontrado')
    datos = {
        'id': comp.id,
        'estado': comp.estado,
        'fecha_emision': comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else None,
        'monto_total': str(comp.monto_total),
        'error_mensaje': comp.respuesta.descripcion if comp.respuesta is not None else None
    }
    return {"exito": True, "datos": datos, "mensaje": None}


from fastapi.responses import Response

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
    from src.tasks.tasks import reenviar_comprobante_task
    from src.api.auth import verificar_emisor
    
    # Verificar que el comprobante existe
    comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comprobante:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    
    # Verificar autorización
    await verificar_emisor(comprobante.emisor_ruc)
    
    # Validar que no esté aceptado
    if comprobante.estado == "aceptado":
        raise HTTPException(
            status_code=400,
            detail="El comprobante ya fue aceptado, no se puede reenviar"
        )
    
    # Encolar tarea
    task = reenviar_comprobante_task.delay(comprobante_id)
    
    return {
        "exito": True,
        "datos": {
            "comprobante_id": str(comprobante_id),
            "task_id": task.id
        },
        "mensaje": "Comprobante encolado para reenvío"
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