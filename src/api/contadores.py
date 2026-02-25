"""
facturalo.pro - Panel del Contador
==================================
Router: /contadores/*
  /contadores/login     → Login del contador
  /contadores/          → Dashboard principal
  /contadores/clientes  → Lista de clientes
  /contadores/estudio   → Gestión del estudio

Archivo: src/api/contadores.py
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.api.dependencies import get_db
from src.api.frontend import templates
from src.models.contador import Contador, ContadorCliente, ContadorTrabajador, ContadorGastoFijo
from src.models.models import Emisor, Comprobante, Certificado

# Reutilizar auth utils del registro.py existente
try:
    from passlib.context import CryptContext
    from jose import jwt, JWTError
except ImportError:
    raise ImportError("pip install passlib[bcrypt] python-jose[cryptography]")

import os

router = APIRouter(prefix="/contadores", tags=["contadores"])

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────
def crear_token_contador(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire, "tipo": "contador"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def obtener_contador_actual(request: Request, db: Session) -> Contador | None:
    token = request.cookies.get("contador_session")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("tipo") != "contador":
            return None
        contador_id = payload.get("contador_id")
        if not contador_id:
            return None
        return db.query(Contador).filter(Contador.id == contador_id, Contador.activo == True).first()
    except JWTError:
        return None


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, msg: str = ""):
    return templates.TemplateResponse("contadores/login.html", {
        "request": request,
        "error": None,
        "mensaje": msg
    })


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    contador = db.query(Contador).filter(
        (func.lower(Contador.email) == email.strip().lower()) |
        (Contador.ruc == email.strip())
    ).first()

    if not contador or not pwd_context.verify(password[:72], contador.password_hash):
        return templates.TemplateResponse("contadores/login.html", {
            "request": request,
            "error": "Credenciales incorrectas",
            "mensaje": ""
        })

    # Actualizar último login
    contador.ultimo_login = datetime.now(timezone.utc)
    db.commit()

    token = crear_token_contador({"contador_id": contador.id, "ruc": contador.ruc})
    response = RedirectResponse(url="/contadores/", status_code=303)
    response.set_cookie(
        key="contador_session",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=TOKEN_EXPIRE_HOURS * 3600
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/contadores/login", status_code=303)
    response.delete_cookie("contador_session")
    return response


# ─────────────────────────────────────────────
# DASHBOARD PRINCIPAL
# ─────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    contador = obtener_contador_actual(request, db)
    if not contador:
        return RedirectResponse(url="/contadores/login", status_code=303)

    # ── KPIs ──
    clientes = db.query(ContadorCliente).filter(
        ContadorCliente.contador_id == contador.id
    ).all()

    total_clientes = len(clientes)
    clientes_activos = sum(1 for c in clientes if c.estado == 'activo')
    clientes_nuevos = sum(1 for c in clientes if c.estado == 'nuevo')
    clientes_vencidos = sum(1 for c in clientes if c.estado == 'vencido')

    ingreso_mensual = sum(float(c.ingreso_mensual or 0) for c in clientes if c.estado == 'activo')

    # ── Datos de cada cliente ──
    clientes_detalle = []
    emisor_ids = [c.emisor_id for c in clientes]

    if emisor_ids:
        # Emisores
        emisores = {e.id: e for e in db.query(Emisor).filter(Emisor.id.in_(emisor_ids)).all()}

        # Comprobantes del mes actual
        mes_actual = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        comprobantes_mes = db.query(
            Comprobante.emisor_id,
            func.count(Comprobante.id).label('total'),
            func.sum(Comprobante.monto_total).label('monto')
        ).filter(
            Comprobante.emisor_id.in_(emisor_ids),
            Comprobante.creado_en >= mes_actual
        ).group_by(Comprobante.emisor_id).all()

        comp_map = {c.emisor_id: {'total': c.total, 'monto': float(c.monto or 0)} for c in comprobantes_mes}

        # Certificados
        certificados = db.query(Certificado).filter(
            Certificado.emisor_id.in_(emisor_ids),
            Certificado.activo == True
        ).all()
        cert_map = {c.emisor_id: c for c in certificados}

        for cc in clientes:
            emisor = emisores.get(cc.emisor_id)
            if not emisor:
                continue

            comp_data = comp_map.get(cc.emisor_id, {'total': 0, 'monto': 0})
            cert = cert_map.get(cc.emisor_id)

            cert_estado = 'sin_cert'
            cert_vence = None
            if cert and cert.fecha_vencimiento:
                cert_vence = cert.fecha_vencimiento
                dias_para_vencer = (cert.fecha_vencimiento.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days if cert.fecha_vencimiento.tzinfo is None else (cert.fecha_vencimiento - datetime.now(timezone.utc)).days
                if dias_para_vencer < 0:
                    cert_estado = 'vencido'
                elif dias_para_vencer <= 30:
                    cert_estado = 'por_vencer'
                else:
                    cert_estado = 'vigente'

            clientes_detalle.append({
                'id': cc.id,
                'emisor_id': cc.emisor_id,
                'ruc': emisor.ruc,
                'razon_social': emisor.razon_social,
                'nombre_comercial': emisor.nombre_comercial,
                'estado': cc.estado,
                'regimen': cc.regimen_tributario or 'No definido',
                'ingreso_mensual': float(cc.ingreso_mensual or 0),
                'comprobantes_mes': comp_data['total'],
                'ventas_mes': comp_data['monto'],
                'cert_estado': cert_estado,
                'cert_vence': cert_vence,
                'email': emisor.email,
                'telefono': emisor.telefono,
            })

    # ── Alertas ──
    alertas = []
    for c in clientes_detalle:
        if c['cert_estado'] == 'vencido':
            alertas.append({
                'tipo': 'danger',
                'icono': 'certificate',
                'msg': f"Certificado VENCIDO: {c['razon_social']}"
            })
        elif c['cert_estado'] == 'por_vencer':
            alertas.append({
                'tipo': 'warning',
                'icono': 'certificate',
                'msg': f"Certificado por vencer: {c['razon_social']}"
            })
        elif c['cert_estado'] == 'sin_cert':
            alertas.append({
                'tipo': 'info',
                'icono': 'upload',
                'msg': f"Sin certificado: {c['razon_social']}"
            })
        if c['comprobantes_mes'] == 0 and c['estado'] == 'activo':
            alertas.append({
                'tipo': 'warning',
                'icono': 'alert-triangle',
                'msg': f"Sin facturación este mes: {c['razon_social']}"
            })

    # ── Gestión del estudio ──
    trabajadores = db.query(ContadorTrabajador).filter(
        ContadorTrabajador.contador_id == contador.id,
        ContadorTrabajador.activo == True
    ).all()

    gastos = db.query(ContadorGastoFijo).filter(
        ContadorGastoFijo.contador_id == contador.id,
        ContadorGastoFijo.activo == True
    ).all()

    total_planilla = sum(float(t.sueldo_mensual or 0) + float(t.essalud or 0) for t in trabajadores)
    total_gastos = sum(float(g.monto_mensual or 0) for g in gastos)
    total_egresos = total_planilla + total_gastos

    # Impuesto aproximado (RER 1.5% de ingresos)
    impuesto_aprox = ingreso_mensual * 0.015

    utilidad_estimada = ingreso_mensual - total_egresos - impuesto_aprox

    return templates.TemplateResponse("contadores/dashboard.html", {
        "request": request,
        "contador": contador,
        # KPIs
        "total_clientes": total_clientes,
        "clientes_activos": clientes_activos,
        "clientes_nuevos": clientes_nuevos,
        "clientes_vencidos": clientes_vencidos,
        "ingreso_mensual": ingreso_mensual,
        # Detalle
        "clientes": clientes_detalle,
        "alertas": alertas[:8],  # Máx 8 alertas visibles
        # Estudio
        "trabajadores": trabajadores,
        "gastos": gastos,
        "total_planilla": total_planilla,
        "total_gastos": total_gastos,
        "total_egresos": total_egresos,
        "impuesto_aprox": impuesto_aprox,
        "utilidad_estimada": utilidad_estimada,
    })


# ─────────────────────────────────────────────
# API: Agregar cliente (invitar emisor)
# ─────────────────────────────────────────────
@router.post("/api/clientes/agregar")
async def agregar_cliente(
    request: Request,
    ruc: str = Form(...),
    ingreso_mensual: float = Form(0),
    regimen: str = Form(""),
    db: Session = Depends(get_db)
):
    contador = obtener_contador_actual(request, db)
    if not contador:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    # Verificar límite de plan
    total = db.query(func.count(ContadorCliente.id)).filter(
        ContadorCliente.contador_id == contador.id
    ).scalar()

    if total >= contador.max_clientes:
        return JSONResponse({
            "error": f"Límite de {contador.max_clientes} clientes alcanzado. Actualiza tu plan."
        }, status_code=400)

    # Buscar emisor por RUC
    emisor = db.query(Emisor).filter(Emisor.ruc == ruc.strip()).first()
    if not emisor:
        return JSONResponse({"error": f"RUC {ruc} no encontrado en facturalo.pro"}, status_code=404)

    # Verificar que no esté vinculado
    existe = db.query(ContadorCliente).filter(
        ContadorCliente.contador_id == contador.id,
        ContadorCliente.emisor_id == emisor.id
    ).first()
    if existe:
        return JSONResponse({"error": "Este cliente ya está vinculado"}, status_code=400)

    nuevo = ContadorCliente(
        contador_id=contador.id,
        emisor_id=emisor.id,
        estado="nuevo",
        ingreso_mensual=ingreso_mensual,
        regimen_tributario=regimen or None
    )
    db.add(nuevo)
    db.commit()

    return RedirectResponse(url="/contadores/", status_code=303)


# ─────────────────────────────────────────────
# API: Actualizar estado cliente
# ─────────────────────────────────────────────
@router.post("/api/clientes/{cliente_id}/estado")
async def cambiar_estado_cliente(
    cliente_id: int,
    request: Request,
    estado: str = Form(...),
    db: Session = Depends(get_db)
):
    contador = obtener_contador_actual(request, db)
    if not contador:
        return JSONResponse({"error": "No autenticado"}, status_code=401)

    cc = db.query(ContadorCliente).filter(
        ContadorCliente.id == cliente_id,
        ContadorCliente.contador_id == contador.id
    ).first()

    if not cc:
        return JSONResponse({"error": "Cliente no encontrado"}, status_code=404)

    cc.estado = estado
    if estado == 'inactivo':
        cc.fecha_desvinculacion = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(url="/contadores/", status_code=303)