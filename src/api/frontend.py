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

# Configurar templates
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirigir a login"""
    return RedirectResponse(url="/login", status_code=302)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login"""
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )

@router.post("/login")
async def login_submit(
    request: Request,
    ruc: str = Form(...),
    password: str = Form(...),
    remember: bool = Form(False)
):
    """Procesar login"""
    # TODO: Validar credenciales contra BD
    
    # Por ahora, login dummy
    if len(ruc) == 11 and password:
        # Crear sesión (simplificado)
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="session", value=ruc, httponly=True)
        return response
    else:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "RUC o contraseña incorrectos"
            }
        )

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard principal"""
    # TODO: Verificar sesión
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user_ruc": session
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

@router.get("/comprobantes/emitir", response_class=HTMLResponse)
async def emitir_comprobante_form(request: Request):

    """Formulario para emitir comprobante"""
    # Verificar sesión
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/emitir.html",
        {
            "request": request,
            "user_ruc": session
        }
    )

@router.get("/clientes", response_class=HTMLResponse)
async def clientes_page(request: Request):
    """Página de gestión de clientes"""
    # Verificar sesión
    session = request.cookies.get("session")
    if not session:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/clientes.html",
        {
            "request": request,
            "user_ruc": session
        }
    )