"""
API de Productos y Catálogo
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.requests import Request as FastAPIRequest
from sqlalchemy.orm import Session
from sqlalchemy import or_, distinct
from uuid import uuid4
from datetime import datetime
import csv
import io

from src.api.dependencies import get_db
from src.models.models import Emisor, Producto

router = APIRouter(prefix="/api/productos", tags=["productos"])


# =============================================
# LISTAR PRODUCTOS
# =============================================

@router.get("")
def listar_productos(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    q: str = None,
    categoria: str = None,
    activo: bool = None,
    favoritos: bool = None,
    page: int = 1,
    limit: int = 50
):
    """Lista productos del emisor con filtros y paginación"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    query = db.query(Producto).filter(Producto.emisor_id == emisor.id)
    
    # Filtros
    if q:
        query = query.filter(
            or_(
                Producto.codigo_interno.ilike(f"%{q}%"),
                Producto.codigo_barras.ilike(f"%{q}%"),
                Producto.descripcion.ilike(f"%{q}%")
            )
        )
    
    if categoria:
        query = query.filter(Producto.categoria == categoria)
    
    if activo is not None:
        query = query.filter(Producto.activo == activo)
    else:
        query = query.filter(Producto.activo == True)  # Por defecto solo activos
    
    if favoritos:
        query = query.filter(Producto.es_favorito == True)
    
    # Contar total
    total = query.count()
    
    # Paginación
    offset = (page - 1) * limit
    productos = query.order_by(
        Producto.es_favorito.desc(),
        Producto.veces_usado.desc(),
        Producto.descripcion
    ).offset(offset).limit(limit).all()
    
    return {
        "exito": True,
        "datos": [
            {
                "id": p.id,
                "codigo_interno": p.codigo_interno,
                "codigo_barras": p.codigo_barras,
                "descripcion": p.descripcion,
                "descripcion_corta": p.descripcion_corta,
                "categoria": p.categoria,
                "subcategoria": p.subcategoria,
                "marca": p.marca,
                "unidad_medida": p.unidad_medida,
                "precio_venta": float(p.precio_venta or 0),
                "precio_compra": float(p.precio_compra or 0),
                "stock_actual": float(p.stock_actual or 0),
                "stock_minimo": float(p.stock_minimo or 0),
                "maneja_stock": p.maneja_stock,
                "afecto_igv": p.afecto_igv,
                "tipo_afectacion_igv": p.tipo_afectacion_igv,
                "activo": p.activo,
                "es_favorito": p.es_favorito,
                "veces_usado": p.veces_usado
            }
            for p in productos
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


# =============================================
# BÚSQUEDA RÁPIDA (para emisión)
# =============================================

@router.get("/buscar")
def buscar_productos(
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
    
    productos = db.query(Producto).filter(
        Producto.emisor_id == emisor.id,
        Producto.activo == True,
        or_(
            Producto.codigo_interno.ilike(f"%{q}%"),
            Producto.codigo_barras.ilike(f"%{q}%"),
            Producto.descripcion.ilike(f"%{q}%")
        )
    ).order_by(
        Producto.es_favorito.desc(),
        Producto.veces_usado.desc(),
        Producto.descripcion
    ).limit(10).all()
    
    return {
        "exito": True,
        "datos": [
            {
                "id": p.id,
                "codigo": p.codigo_interno,
                "descripcion": p.descripcion,
                "precio_unitario": float(p.precio_venta or 0),
                "stock": float(p.stock_actual or 0),
                "unidad_medida": p.unidad_medida,
                "tipo_afectacion_igv": p.tipo_afectacion_igv,
                "afecto_igv": p.afecto_igv
            }
            for p in productos
        ]
    }


# =============================================
# OBTENER PRODUCTO
# =============================================

@router.get("/{producto_id}")
def obtener_producto(
    producto_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Obtiene un producto por ID"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.emisor_id == emisor.id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    return {
        "exito": True,
        "datos": {
            "id": producto.id,
            "codigo_interno": producto.codigo_interno,
            "codigo_sunat": producto.codigo_sunat,
            "codigo_barras": producto.codigo_barras,
            "descripcion": producto.descripcion,
            "descripcion_corta": producto.descripcion_corta,
            "categoria": producto.categoria,
            "subcategoria": producto.subcategoria,
            "marca": producto.marca,
            "modelo": producto.modelo,
            "unidad_medida": producto.unidad_medida,
            "precio_venta": float(producto.precio_venta or 0),
            "precio_compra": float(producto.precio_compra or 0),
            "moneda": producto.moneda,
            "afecto_igv": producto.afecto_igv,
            "tipo_afectacion_igv": producto.tipo_afectacion_igv,
            "maneja_stock": producto.maneja_stock,
            "stock_actual": float(producto.stock_actual or 0),
            "stock_minimo": float(producto.stock_minimo or 0),
            "activo": producto.activo,
            "es_favorito": producto.es_favorito,
            "veces_usado": producto.veces_usado
        }
    }


# =============================================
# CREAR PRODUCTO
# =============================================

@router.post("")
async def crear_producto(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Crea un nuevo producto"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    data = await request.json()
    
    # Validaciones
    if not data.get("descripcion"):
        raise HTTPException(status_code=400, detail="La descripción es requerida")
    
    if not data.get("codigo_interno"):
        raise HTTPException(status_code=400, detail="El código interno es requerido")
    
    if not data.get("precio_venta") and data.get("precio_venta") != 0:
        raise HTTPException(status_code=400, detail="El precio de venta es requerido")
    
    # Validar código único
    existe = db.query(Producto).filter(
        Producto.emisor_id == emisor.id,
        Producto.codigo_interno == data["codigo_interno"]
    ).first()
    if existe:
        raise HTTPException(status_code=400, detail=f"Ya existe un producto con código {data['codigo_interno']}")
    
    # Determinar tipo IGV
    afecto_igv = data.get("afecto_igv", True)
    if afecto_igv:
        tipo_igv = "10"  # Gravado
    else:
        tipo_igv = data.get("tipo_afectacion_igv", "20")  # Exonerado por defecto
    
    producto = Producto(
        id=str(uuid4()),
        emisor_id=emisor.id,
        codigo_interno=data["codigo_interno"],
        codigo_sunat=data.get("codigo_sunat"),
        codigo_barras=data.get("codigo_barras"),
        descripcion=data["descripcion"],
        descripcion_corta=data.get("descripcion_corta"),
        categoria=data.get("categoria"),
        subcategoria=data.get("subcategoria"),
        marca=data.get("marca"),
        modelo=data.get("modelo"),
        unidad_medida=data.get("unidad_medida", "NIU"),
        precio_venta=float(data["precio_venta"]),
        precio_compra=float(data.get("precio_compra", 0)),
        moneda=data.get("moneda", "PEN"),
        afecto_igv=afecto_igv,
        tipo_afectacion_igv=tipo_igv,
        maneja_stock=data.get("maneja_stock", False),
        stock_actual=float(data.get("stock_actual", 0)),
        stock_minimo=float(data.get("stock_minimo", 0)),
        activo=True,
        es_favorito=data.get("es_favorito", False),
        veces_usado=0
    )
    
    db.add(producto)
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Producto creado correctamente",
        "producto_id": producto.id
    }


# =============================================
# ACTUALIZAR PRODUCTO
# =============================================

@router.put("/{producto_id}")
async def actualizar_producto(
    producto_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Actualiza un producto"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.emisor_id == emisor.id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    data = await request.json()
    
    # Validar código único si cambió
    if data.get("codigo_interno") and data["codigo_interno"] != producto.codigo_interno:
        existe = db.query(Producto).filter(
            Producto.emisor_id == emisor.id,
            Producto.codigo_interno == data["codigo_interno"],
            Producto.id != producto_id
        ).first()
        if existe:
            raise HTTPException(status_code=400, detail=f"Ya existe un producto con código {data['codigo_interno']}")
    
    # Actualizar campos de texto
    campos_texto = [
        "codigo_interno", "codigo_sunat", "codigo_barras", "descripcion",
        "descripcion_corta", "categoria", "subcategoria", "marca", "modelo",
        "unidad_medida", "moneda", "tipo_afectacion_igv"
    ]
    
    for campo in campos_texto:
        if campo in data:
            setattr(producto, campo, data[campo])
    
    # Campos booleanos
    if "afecto_igv" in data:
        producto.afecto_igv = data["afecto_igv"]
    if "maneja_stock" in data:
        producto.maneja_stock = data["maneja_stock"]
    if "activo" in data:
        producto.activo = data["activo"]
    if "es_favorito" in data:
        producto.es_favorito = data["es_favorito"]
    
    # Campos numéricos
    if "precio_venta" in data:
        producto.precio_venta = float(data["precio_venta"])
    if "precio_compra" in data:
        producto.precio_compra = float(data["precio_compra"])
    if "stock_actual" in data:
        producto.stock_actual = float(data["stock_actual"])
    if "stock_minimo" in data:
        producto.stock_minimo = float(data["stock_minimo"])
    
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Producto actualizado correctamente"
    }


# =============================================
# ELIMINAR PRODUCTO (soft delete)
# =============================================

@router.delete("/{producto_id}")
def eliminar_producto(
    producto_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Elimina (desactiva) un producto"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.emisor_id == emisor.id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    producto.activo = False
    db.commit()
    
    return {
        "exito": True,
        "mensaje": "Producto eliminado correctamente"
    }


# =============================================
# TOGGLE FAVORITO
# =============================================

@router.post("/{producto_id}/favorito")
def toggle_favorito(
    producto_id: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Marca/desmarca producto como favorito"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.emisor_id == emisor.id
    ).first()
    
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    producto.es_favorito = not producto.es_favorito
    db.commit()
    
    return {
        "exito": True,
        "es_favorito": producto.es_favorito,
        "mensaje": "Agregado a favoritos" if producto.es_favorito else "Quitado de favoritos"
    }


# =============================================
# IMPORTACIÓN MASIVA
# =============================================

@router.post("/importar")
async def importar_productos(
    request: FastAPIRequest,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Importa productos desde CSV/Excel"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    contenido = await archivo.read()
    filename = archivo.filename.lower()
    
    productos_importados = 0
    productos_actualizados = 0
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
            raise HTTPException(status_code=400, detail="Formato no soportado. Use CSV o Excel (.xlsx)")
        
        for i, fila in enumerate(filas, start=2):
            try:
                # Normalizar nombres de columnas
                fila_norm = {k.lower().strip().replace(' ', '_'): v for k, v in fila.items() if k}
                
                codigo = str(fila_norm.get('codigo', fila_norm.get('codigo_interno', fila_norm.get('sku', '')))).strip()
                descripcion = str(fila_norm.get('descripcion', fila_norm.get('nombre', fila_norm.get('producto', '')))).strip()
                
                if not descripcion:
                    errores.append(f"Fila {i}: Descripción vacía")
                    continue
                
                if not codigo:
                    errores.append(f"Fila {i}: Código vacío")
                    continue
                
                # Buscar existente por código
                producto_existente = db.query(Producto).filter(
                    Producto.emisor_id == emisor.id,
                    Producto.codigo_interno == codigo
                ).first()
                
                # Obtener valores
                precio_venta = float(fila_norm.get('precio', fila_norm.get('precio_venta', fila_norm.get('pv', 0))) or 0)
                precio_compra = float(fila_norm.get('costo', fila_norm.get('precio_compra', fila_norm.get('pc', 0))) or 0)
                stock = float(fila_norm.get('stock', fila_norm.get('stock_actual', fila_norm.get('cantidad', 0))) or 0)
                unidad = str(fila_norm.get('unidad', fila_norm.get('unidad_medida', fila_norm.get('um', 'NIU')))).strip().upper() or 'NIU'
                categoria = str(fila_norm.get('categoria', '')).strip() or None
                marca = str(fila_norm.get('marca', '')).strip() or None
                
                if producto_existente:
                    # Actualizar
                    producto_existente.descripcion = descripcion
                    producto_existente.precio_venta = precio_venta
                    producto_existente.precio_compra = precio_compra
                    producto_existente.stock_actual = stock
                    producto_existente.unidad_medida = unidad
                    if categoria:
                        producto_existente.categoria = categoria
                    if marca:
                        producto_existente.marca = marca
                    productos_actualizados += 1
                else:
                    # Crear nuevo
                    nuevo = Producto(
                        id=str(uuid4()),
                        emisor_id=emisor.id,
                        codigo_interno=codigo,
                        descripcion=descripcion,
                        unidad_medida=unidad,
                        precio_venta=precio_venta,
                        precio_compra=precio_compra,
                        stock_actual=stock,
                        categoria=categoria,
                        marca=marca,
                        tipo_afectacion_igv='10',
                        afecto_igv=True,
                        maneja_stock=stock > 0,
                        activo=True
                    )
                    db.add(nuevo)
                    productos_importados += 1
                    
            except Exception as e:
                errores.append(f"Fila {i}: {str(e)}")
                continue
        
        db.commit()
        
        return {
            "exito": True,
            "mensaje": "Importación completada",
            "importados": productos_importados,
            "actualizados": productos_actualizados,
            "total_procesados": productos_importados + productos_actualizados,
            "errores": errores[:20]
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error procesando archivo: {str(e)}")


# =============================================
# DESCARGAR PLANTILLA
# =============================================

@router.get("/plantilla/descargar")
def descargar_plantilla():
    """Descarga plantilla CSV para importación"""
    from fastapi.responses import StreamingResponse
    
    plantilla = """codigo,descripcion,precio_venta,precio_compra,stock,unidad_medida,categoria,marca
PROD001,Producto de ejemplo 1,100.00,80.00,50,NIU,General,MarcaX
PROD002,Servicio de consultoría,250.00,0,0,ZZ,Servicios,
PROD003,Producto exonerado IGV,45.50,30.00,100,NIU,General,MarcaY
"""
    
    return StreamingResponse(
        io.StringIO(plantilla),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla_productos.csv"}
    )


# =============================================
# CATEGORÍAS ÚNICAS
# =============================================

@router.get("/categorias/lista")
def listar_categorias(
    request: FastAPIRequest,
    db: Session = Depends(get_db)
):
    """Lista categorías únicas de los productos"""
    session_ruc = request.cookies.get("session")
    if not session_ruc:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session_ruc).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    categorias = db.query(distinct(Producto.categoria)).filter(
        Producto.emisor_id == emisor.id,
        Producto.categoria.isnot(None),
        Producto.categoria != ''
    ).order_by(Producto.categoria).all()
    
    return {
        "exito": True,
        "datos": [c[0] for c in categorias if c[0]]
    }