"""
API de Clientes
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.requests import Request as FastAPIRequest
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import uuid4
from datetime import datetime
import csv
import io

from src.api.dependencies import get_db
from src.models.models import Emisor, Cliente

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


@router.get("")
def listar_clientes(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    q: str = None,
    page: int = 1,
    limit: int = 50
):
    """Lista clientes del emisor"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    query = db.query(Cliente).filter(Cliente.emisor_id == emisor.id)
    
    if q:
        query = query.filter(
            or_(
                Cliente.numero_documento.ilike(f"%{q}%"),
                Cliente.razon_social.ilike(f"%{q}%")
            )
        )
    
    total = query.count()
    offset = (page - 1) * limit
    clientes = query.order_by(Cliente.razon_social).offset(offset).limit(limit).all()
    
    return {
        "exito": True,
        "datos": [
            {
                "id": c.id,
                "tipo_documento": c.tipo_documento,
                "numero_documento": c.numero_documento,
                "razon_social": c.razon_social,
                "direccion": c.direccion,
                "email": c.email,
                "telefono": c.telefono
            }
            for c in clientes
        ],
        "total": total,
        "page": page,
        "limit": limit
    }


@router.get("/buscar")
def buscar_clientes(
    request: FastAPIRequest,
    q: str,
    db: Session = Depends(get_db)
):
    """Búsqueda rápida para formulario de emisión"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    clientes = db.query(Cliente).filter(
        Cliente.emisor_id == emisor.id,
        or_(
            Cliente.numero_documento.ilike(f"%{q}%"),
            Cliente.razon_social.ilike(f"%{q}%")
        )
    ).order_by(Cliente.razon_social).limit(10).all()
    
    return {
        "exito": True,
        "datos": [
            {
                "id": c.id,
                "tipo_documento": c.tipo_documento,
                "numero_documento": c.numero_documento,
                "razon_social": c.razon_social,
                "direccion": c.direccion
            }
            for c in clientes
        ]
    }


@router.get("/{cliente_id}")
def obtener_cliente(
    cliente_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Obtiene un cliente por ID"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.emisor_id == emisor.id
    ).first()
    
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    return {
        "exito": True,
        "datos": {
            "id": cliente.id,
            "tipo_documento": cliente.tipo_documento,
            "numero_documento": cliente.numero_documento,
            "razon_social": cliente.razon_social,
            "direccion": cliente.direccion,
            "ubigeo": cliente.ubigeo,
            "email": cliente.email,
            "telefono": cliente.telefono
        }
    }


@router.post("")
async def crear_cliente(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Crea un nuevo cliente"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    data = await request.json()
    
    if not data.get("numero_documento"):
        raise HTTPException(status_code=400, detail="El número de documento es requerido")
    
    if not data.get("razon_social"):
        raise HTTPException(status_code=400, detail="La razón social es requerida")
    
    # Verificar si ya existe
    existe = db.query(Cliente).filter(
        Cliente.emisor_id == emisor.id,
        Cliente.numero_documento == data["numero_documento"]
    ).first()
    
    if existe:
        raise HTTPException(status_code=400, detail=f"Ya existe un cliente con documento {data['numero_documento']}")
    
    cliente = Cliente(
        id=str(uuid4()),
        emisor_id=emisor.id,
        tipo_documento=data.get("tipo_documento", "6"),
        numero_documento=data["numero_documento"],
        razon_social=data["razon_social"],
        direccion=data.get("direccion"),
        ubigeo=data.get("ubigeo"),
        email=data.get("email"),
        telefono=data.get("telefono")
    )
    
    db.add(cliente)
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Cliente creado correctamente",
        "cliente_id": cliente.id
    }


@router.put("/{cliente_id}")
async def actualizar_cliente(
    cliente_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Actualiza un cliente"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.emisor_id == emisor.id
    ).first()
    
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    data = await request.json()
    
    campos = ["tipo_documento", "numero_documento", "razon_social", "direccion", "ubigeo", "email", "telefono"]
    for campo in campos:
        if campo in data:
            setattr(cliente, campo, data[campo])
    
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Cliente actualizado correctamente"
    }


@router.delete("/{cliente_id}")
def eliminar_cliente(
    cliente_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Elimina un cliente"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.emisor_id == emisor.id
    ).first()
    
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    db.delete(cliente)
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Cliente eliminado correctamente"
    }


@router.post("/importar")
async def importar_clientes(
    request: FastAPIRequest,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Importa clientes desde CSV/Excel"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    contenido = await archivo.read()
    filename = archivo.filename.lower()
    
    importados = 0
    actualizados = 0
    errores = []
    
    try:
        if filename.endswith('.csv'):
            texto = contenido.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(texto))
            filas = list(reader)
        elif filename.endswith(('.xlsx', '.xls')):
            import pandas as pd
            df = pd.read_excel(io.BytesIO(contenido))
            filas = df.to_dict('records')
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado")
        
        for i, fila in enumerate(filas, start=2):
            try:
                fila_norm = {k.lower().strip().replace(' ', '_'): v for k, v in fila.items() if k}
                
                numero_doc = str(fila_norm.get('ruc', fila_norm.get('dni', fila_norm.get('numero_documento', fila_norm.get('documento', ''))))).strip()
                razon_social = str(fila_norm.get('razon_social', fila_norm.get('nombre', fila_norm.get('cliente', '')))).strip()
                
                if not numero_doc or not razon_social:
                    errores.append(f"Fila {i}: Documento o razón social vacío")
                    continue
                
                # Determinar tipo documento
                tipo_doc = "6" if len(numero_doc) == 11 else "1"
                
                # Buscar existente
                existente = db.query(Cliente).filter(
                    Cliente.emisor_id == emisor.id,
                    Cliente.numero_documento == numero_doc
                ).first()
                
                direccion = str(fila_norm.get('direccion', '')).strip() or None
                email = str(fila_norm.get('email', fila_norm.get('correo', ''))).strip() or None
                telefono = str(fila_norm.get('telefono', fila_norm.get('celular', ''))).strip() or None
                
                if existente:
                    existente.razon_social = razon_social
                    if direccion:
                        existente.direccion = direccion
                    if email:
                        existente.email = email
                    if telefono:
                        existente.telefono = telefono
                    actualizados += 1
                else:
                    nuevo = Cliente(
                        id=str(uuid4()),
                        emisor_id=emisor.id,
                        tipo_documento=tipo_doc,
                        numero_documento=numero_doc,
                        razon_social=razon_social,
                        direccion=direccion,
                        email=email,
                        telefono=telefono
                    )
                    db.add(nuevo)
                    importados += 1
                    
            except Exception as e:
                errores.append(f"Fila {i}: {str(e)}")
                continue
        
        db.commit()
        
        return {
            "exito": True,
            "mensaje": "Importación completada",
            "importados": importados,
            "actualizados": actualizados,
            "errores": errores[:20]
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")


@router.get("/plantilla/descargar")
def descargar_plantilla():
    """Descarga plantilla CSV"""
    from fastapi.responses import StreamingResponse
    
    plantilla = """ruc,razon_social,direccion,email,telefono
20123456789,EMPRESA EJEMPLO SAC,Av. Principal 123,contacto@empresa.com,01-1234567
10123456789,PERSONA NATURAL,Jr. Secundario 456,persona@email.com,987654321
"""
    
    return StreamingResponse(
        io.StringIO(plantilla),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla_clientes.csv"}
    )