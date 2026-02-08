from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from datetime import datetime, timedelta

from src.models.models import Comprobante, Emisor, LineaDetalle
from src.api.dependencies import get_db

# Configurar templates
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@router.get("/desarrolladores", response_class=HTMLResponse)
async def desarrolladores(request: Request):
    return templates.TemplateResponse("desarrolladores.html", {"request": request})

@router.get("/contadores", response_class=HTMLResponse)
async def contadores(request: Request):
    return templates.TemplateResponse("contadores.html", {"request": request})

@router.get("/instituciones", response_class=HTMLResponse)
async def instituciones(request: Request):
    return templates.TemplateResponse("instituciones.html", {"request": request})

@router.get("/empresas", response_class=HTMLResponse)
async def empresas(request: Request):
    return templates.TemplateResponse("empresas.html", {"request": request})

@router.get("/sector-publico", response_class=HTMLResponse)
async def sector_publico(request: Request):
    return templates.TemplateResponse("sector-publico.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login"""
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard principal con estadísticas"""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func
    
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    # Zona horaria Perú
    peru_tz = timezone(timedelta(hours=-5))
    hoy = datetime.now(peru_tz).date()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    
    # Query base
    base_query = db.query(Comprobante).filter(Comprobante.emisor_id == emisor.id)
    
    # === ESTADÍSTICAS DE MONTOS ===
    
    # Total hoy
    total_hoy = db.query(func.coalesce(func.sum(Comprobante.monto_total), 0)).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision == hoy,
        Comprobante.estado == 'aceptado'
    ).scalar() or 0
    
    # Total semana
    total_semana = db.query(func.coalesce(func.sum(Comprobante.monto_total), 0)).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision >= inicio_semana,
        Comprobante.estado == 'aceptado'
    ).scalar() or 0
    
    # Total mes
    total_mes = db.query(func.coalesce(func.sum(Comprobante.monto_total), 0)).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.fecha_emision >= inicio_mes,
        Comprobante.estado == 'aceptado'
    ).scalar() or 0
    
    # === CONTADORES POR ESTADO ===
    
    count_aceptados = base_query.filter(Comprobante.estado == 'aceptado').count()
    count_rechazados = base_query.filter(Comprobante.estado == 'rechazado').count()
    count_pendientes = base_query.filter(Comprobante.estado.in_(['pendiente', 'enviando', 'encolado'])).count()
    count_total = base_query.count()
    
    # === CONTADORES POR TIPO ===
    
    count_facturas = base_query.filter(Comprobante.tipo_documento == '01').count()
    count_boletas = base_query.filter(Comprobante.tipo_documento == '03').count()
    count_nc = base_query.filter(Comprobante.tipo_documento == '07').count()
    count_nd = base_query.filter(Comprobante.tipo_documento == '08').count()
    
    # === COMPROBANTES HOY ===
    
    comprobantes_hoy = base_query.filter(
        Comprobante.fecha_emision == hoy
    ).count()
    
    # === ÚLTIMOS 5 COMPROBANTES ===
    
    ultimos_comprobantes = base_query.order_by(
        Comprobante.creado_en.desc()
    ).limit(5).all()
    
    # === CERTIFICADO ===
    
    certificado = None
    certificado_dias_restantes = None
    if emisor.certificados:
        cert = next((c for c in emisor.certificados if c.activo), None)
        if cert and cert.fecha_vencimiento:
            certificado = cert
            certificado_dias_restantes = (cert.fecha_vencimiento - hoy).days
    
    return templates.TemplateResponse(
        "dashboard/dashboard.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": session,
            # Montos
            "total_hoy": float(total_hoy),
            "total_semana": float(total_semana),
            "total_mes": float(total_mes),
            # Contadores estado
            "count_aceptados": count_aceptados,
            "count_rechazados": count_rechazados,
            "count_pendientes": count_pendientes,
            "count_total": count_total,
            # Contadores tipo
            "count_facturas": count_facturas,
            "count_boletas": count_boletas,
            "count_nc": count_nc,
            "count_nd": count_nd,
            # Otros
            "comprobantes_hoy": comprobantes_hoy,
            "ultimos_comprobantes": ultimos_comprobantes,
            # Certificado
            "certificado": certificado,
            "certificado_dias_restantes": certificado_dias_restantes,
            # Fecha
            "fecha_hoy": hoy.strftime("%d/%m/%Y"),
        }
    )

@router.get("/logout")
async def logout():

    """Cerrar sesión"""
    response = RedirectResponse(url="/login")
    response.delete_cookie(key="session")
    return response

@router.get("/comprobantes", response_class=HTMLResponse)
async def comprobantes_lista(
    request: Request,
    estado: str = None,
    fecha_desde: str = None,
    fecha_hasta: str = None,
    buscar: str = None,
    page: int = 1,
    db: Session = Depends(get_db)
):
    """Lista de comprobantes con filtros"""
    # Verificar sesión
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    # Buscar emisor
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    # Query base
    query = db.query(Comprobante).filter(Comprobante.emisor_id == emisor.id)
    
    # Aplicar filtros
    if estado:
        query = query.filter(Comprobante.estado == estado)
    
    if fecha_desde:
        fecha_desde_obj = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
        query = query.filter(Comprobante.fecha_emision >= fecha_desde_obj)
    
    if fecha_hasta:
        fecha_hasta_obj = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
        query = query.filter(Comprobante.fecha_emision <= fecha_hasta_obj)
    
    if buscar:
        query = query.filter(
            (Comprobante.serie.ilike(f"%{buscar}%")) |
            (Comprobante.numero_formato.ilike(f"%{buscar}%"))
        )
    
    # Paginación
    per_page = 20
    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    
    comprobantes = query.order_by(
        Comprobante.fecha_emision.desc(),
        Comprobante.numero.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()
    
    # Calcular estadísticas
    base_query = db.query(Comprobante).filter(Comprobante.emisor_id == emisor.id)
    
    total_hoy = base_query.filter(
        Comprobante.fecha_emision == datetime.now().date()
    ).count()
    
    total_encolados = base_query.filter(
        Comprobante.estado == 'encolado'
    ).count()
    
    total_rechazados = base_query.filter(
        Comprobante.estado == 'rechazado'
    ).count()
    
    # Calcular rango de visualización
    inicio = ((page - 1) * per_page) + 1
    fin = min(page * per_page, total)  # Calcular aquí
    
    return templates.TemplateResponse(
        "dashboard/comprobantes.html",
        {
            "request": request,
            "user_ruc": session,
            "emisor": emisor,
            "comprobantes": comprobantes,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "estado": estado,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "buscar": buscar,
            "total_hoy": total_hoy,
            "total_encolados": total_encolados,
            "total_rechazados": total_rechazados,
            "inicio": inicio,      # AGREGAR
            "fin": fin             # AGREGAR
        }
    )


@router.get("/clientes", response_class=HTMLResponse)
async def clientes_page(request: Request, db: Session = Depends(get_db)):
    """Página de clientes"""
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    # Obtener clientes del emisor (si tienes tabla de clientes)
    # clientes = db.query(Cliente).filter(Cliente.emisor_id == emisor.id).all()
    
    return templates.TemplateResponse(
        "dashboard/clientes.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": session,
            # "clientes": clientes
        }
    )


@router.get("/comprobantes/emitir", response_class=HTMLResponse)
async def emitir_comprobante_page(request: Request, db: Session = Depends(get_db)):
    """Página para emitir nuevo comprobante"""
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/emitir.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": session
        }
    )


@router.get("/configuracion", response_class=HTMLResponse)
async def configuracion_page(request: Request, db: Session = Depends(get_db)):
    """Página de configuración del emisor"""
    from datetime import datetime, timedelta, timezone
    
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    # Zona horaria Perú
    peru_tz = timezone(timedelta(hours=-5))
    hoy = datetime.now(peru_tz).date()
    
    # Obtener certificado activo
    certificado = None
    certificado_dias_restantes = None
    if emisor.certificados:
        certificado = next((c for c in emisor.certificados if c.activo), None)
        if certificado and certificado.fecha_vencimiento:
            certificado_dias_restantes = (certificado.fecha_vencimiento - hoy).days
    
    return templates.TemplateResponse(
        "dashboard/configuracion.html",
        {
            "request": request,
            "emisor": emisor,
            "certificado": certificado,
            "certificado_dias_restantes": certificado_dias_restantes,
            "user_ruc": session,
            "today": hoy
        }
    )


@router.get("/comprobantes/nota-credito", response_class=HTMLResponse)
async def nota_credito_page(request: Request, db: Session = Depends(get_db)):
    """Página para emitir Nota de Crédito"""
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    # Obtener comprobantes que pueden tener NC (Facturas y Boletas aceptadas)
    comprobantes_disponibles = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.tipo_documento.in_(['01', '03']),  # Solo Facturas y Boletas
        Comprobante.estado == 'aceptado'
    ).order_by(Comprobante.fecha_emision.desc()).limit(50).all()

    print(f"DEBUG NC: Emisor {emisor.id}, Comprobantes encontrados: {len(comprobantes_disponibles)}")
    
    return templates.TemplateResponse(
        "dashboard/nota_credito.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": session,
            "comprobantes_disponibles": comprobantes_disponibles
        }
    )


@router.get("/productos", response_class=HTMLResponse)
async def productos_page(request: Request, db: Session = Depends(get_db)):
    """Página de productos/catálogo"""
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    emisor = db.query(Emisor).filter(Emisor.ruc == session).first()
    if not emisor:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/productos.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": session
        }
    )