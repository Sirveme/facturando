from fastapi import APIRouter, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from src.models.models import Comprobante, Emisor, LineaDetalle, PagoVoucher
from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.api.referencias_ui import COMP_ACEPTADOS  # ("aceptado", "aceptado_con_observaciones")

# Configurar templates
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# Cache-busting centralizado: APP_VERSION disponible como global en TODAS las
# plantillas (instancia única). En cada deploy basta bumpear settings.APP_VERSION
# o la variable de entorno APP_VERSION para invalidar el caché de CSS/JS propios.
import os as _os
from src.core.config import settings as _settings
templates.env.globals["APP_VERSION"] = _os.getenv("APP_VERSION") or getattr(_settings, "APP_VERSION", "1")

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


# ─────────────────────────────────────────────────────────────────────────
# PAGAR (Fase 1) — página pública simple: elegir plan + datos de pago +
# subir voucher. El pago NO es restrictivo: la cuenta se activa igual.
# NO toca facturación (routers/flujo de emisión intactos).
#
# HOOK (fase futura — NO implementado aquí): motor de pagos con cascada
# pagoOK (3s) → email banco (10s) → voucher (3s). Cuando exista, este POST
# encolaría la validación; por ahora solo persiste el voucher.
# ─────────────────────────────────────────────────────────────────────────

# Precios oficiales (soles) — fuente única para validar el monto declarado.
_PLANES_PRECIOS = {
    "emprendedor": {"mensual": 29, "anual": 290},
    "negocio":     {"mensual": 55, "anual": 550},
}


@router.get("/pagar", response_class=HTMLResponse)
async def pagar_page(request: Request):
    """Página pública de pago (Fase 1)."""
    return templates.TemplateResponse("pagar.html", {"request": request})


@router.post("/pagar/voucher")
async def pagar_voucher(
    request: Request,
    plan: str = Form(""),
    periodicidad: str = Form(""),
    monto: str = Form(""),
    titular: str = Form(""),
    ruc: str = Form(""),
    telefono: str = Form(""),
    metodo: str = Form(""),
    voucher: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Recibe el comprobante de pago (imagen) y lo guarda como BLOB.

    Responde con la confirmación de ACTIVACIÓN INMEDIATA. No depende de
    autenticación: el titular se indica manualmente en el formulario.
    """
    # Normalizar/validar entradas suaves (nunca bloquean la activación por
    # datos secundarios; solo se validan la imagen y su tamaño).
    plan = (plan or "").strip().lower()
    periodicidad = (periodicidad or "").strip().lower()
    if plan not in _PLANES_PRECIOS:
        plan = None
    if periodicidad not in ("mensual", "anual"):
        periodicidad = None

    # Monto: preferimos el precio oficial si plan+periodicidad son válidos;
    # el 'monto' del form es informativo (lo calcula el JS).
    monto_val = None
    if plan and periodicidad:
        monto_val = Decimal(str(_PLANES_PRECIOS[plan][periodicidad]))
    else:
        try:
            monto_val = Decimal((monto or "").replace("S/", "").replace(",", "").strip())
        except (InvalidOperation, ValueError):
            monto_val = None

    # Validar imagen (mismo criterio que el logo del emisor)
    allowed = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if voucher.content_type not in allowed:
        raise HTTPException(400, detail="Sube una imagen PNG, JPG o WebP del voucher.")
    data = await voucher.read()
    if not data:
        raise HTTPException(400, detail="El archivo del voucher está vacío.")
    if len(data) > 5_000_000:  # 5 MB, holgado para fotos de celular
        raise HTTPException(400, detail="La imagen no debe superar 5 MB.")

    registro = PagoVoucher(
        plan=plan,
        periodicidad=periodicidad,
        monto=monto_val,
        titular=(titular or "").strip()[:160] or None,
        ruc=(ruc or "").strip()[:15] or None,
        telefono=(telefono or "").strip()[:30] or None,
        metodo=(metodo or "").strip().lower()[:20] or None,
        imagen=data,
        imagen_content_type=voucher.content_type,
        imagen_filename=(voucher.filename or "")[:200] or None,
        estado="pendiente",
    )
    db.add(registro)
    db.commit()

    return JSONResponse({
        "exito": True,
        "mensaje": "Validaremos tu pago, pero TU CUENTA YA ESTÁ ACTIVA.",
        "id": registro.id,
    })

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


@router.get("/importadores", response_class=HTMLResponse)
async def importadores(request: Request):
    # Landing comercial por nicho (importadores/comercio). Página nueva aislada,
    # hereda el sistema visual maestro src/static/css/landings/_brand.css.
    return templates.TemplateResponse("landings/importadores.html", {"request": request})


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
    
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
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
            "user_ruc": emisor.ruc,
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
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
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
            "user_ruc": emisor.ruc,
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
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
        return RedirectResponse(url="/login")
    
    # Obtener clientes del emisor (si tienes tabla de clientes)
    # clientes = db.query(Cliente).filter(Cliente.emisor_id == emisor.id).all()
    
    return templates.TemplateResponse(
        "dashboard/clientes.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": emisor.ruc,
            # "clientes": clientes
        }
    )


@router.get("/comprobantes/emitir", response_class=HTMLResponse)
async def emitir_comprobante_page(request: Request, db: Session = Depends(get_db)):
    """Página para emitir nuevo comprobante"""
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
        return RedirectResponse(url="/login")

    # Series REALES del emisor por tipo de comprobante (desde BD, no hardcodeadas).
    # Fuente: series ya emitidas en `comprobante` + las declaradas en config_json.
    series_por_tipo: dict[str, set] = {}
    for tipo, serie in (
        db.query(Comprobante.tipo_documento, Comprobante.serie)
        .filter(Comprobante.emisor_id == emisor.id)
        .distinct()
        .all()
    ):
        if tipo and serie:
            series_por_tipo.setdefault(tipo, set()).add(serie)

    cfg_series = (emisor.config_json or {}).get("series") or {}
    for tipo, info in cfg_series.items():
        entradas = info if isinstance(info, list) else [info]
        for item in entradas:
            s = item.get("serie") if isinstance(item, dict) else item
            if s:
                series_por_tipo.setdefault(tipo, set()).add(s)

    # Fallback solo cuando el emisor aún no tiene ninguna serie real para ese tipo
    # (emisor nuevo): así puede emitir su primer comprobante. No se inyecta sobre
    # tipos que ya tienen series reales -> sin "F001 fantasma".
    defaults = {
        '01': ['F001'], '03': ['B001'], '12': ['T001'],
        '07': ['FC01', 'BC01'], '08': ['FD01', 'BD01'],
    }
    series_emisor = {
        tipo: (sorted(series_por_tipo.get(tipo, set())) or defs)
        for tipo, defs in defaults.items()
    }

    # Detracción (SPOT): config para mostrar el checkbox en el form de factura.
    # None si el emisor no la tiene activa -> el checkbox no se renderiza.
    _det = (emisor.config_json or {}).get('detraccion') or {}
    detraccion_cfg = ({
        'porcentaje': float(_det.get('porcentaje', 0) or 0),
        'umbral': float(_det.get('umbral', 700) or 700),
    } if _det.get('activa') else None)

    return templates.TemplateResponse(
        "dashboard/emitir.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": emisor.ruc,
            "series_emisor": series_emisor,
            "detraccion_cfg": detraccion_cfg,
        }
    )


@router.get("/configuracion", response_class=HTMLResponse)
async def configuracion_page(request: Request, db: Session = Depends(get_db)):
    """Página de configuración del emisor"""
    from datetime import datetime, timedelta, timezone
    
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
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
            "user_ruc": emisor.ruc,
            "today": hoy
        }
    )


@router.get("/comprobantes/nota-credito", response_class=HTMLResponse)
async def nota_credito_page(request: Request, db: Session = Depends(get_db)):
    """Página para emitir Nota de Crédito"""
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
        return RedirectResponse(url="/login")
    
    # Obtener comprobantes que pueden tener NC (Facturas y Boletas aceptadas)
    comprobantes_disponibles = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.tipo_documento.in_(['01', '03']),  # Solo Facturas y Boletas
        Comprobante.estado.in_(COMP_ACEPTADOS)  # aceptado + aceptado_con_observaciones
    ).order_by(Comprobante.fecha_emision.desc()).limit(50).all()

    print(f"DEBUG NC: Emisor {emisor.id}, Comprobantes encontrados: {len(comprobantes_disponibles)}")
    
    return templates.TemplateResponse(
        "dashboard/nota_credito.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": emisor.ruc,
            "comprobantes_disponibles": comprobantes_disponibles
        }
    )


@router.get("/productos", response_class=HTMLResponse)
async def productos_page(request: Request, db: Session = Depends(get_db)):
    """Página de productos/catálogo"""
    try:
        emisor = await obtener_emisor_actual(request, db)
    except:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse(
        "dashboard/productos.html",
        {
            "request": request,
            "emisor": emisor,
            "user_ruc": emisor.ruc
        }
    )