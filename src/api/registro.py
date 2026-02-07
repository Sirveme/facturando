"""
facturalo.pro - Registro, Login, Logout y Dashboard Trial
=========================================================
Router para el flujo completo de conversión:
  /registro  → Formulario de registro (15 días gratis)
  /login     → Inicio de sesión
  /logout    → Cerrar sesión
  /mi-cuenta → Dashboard del usuario trial/activo

Dependencias nuevas (agregar a requirements.txt):
  pip install passlib[bcrypt] python-jose[cryptography] python-multipart
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import hashlib
import secrets
import re
import json

# === IMPORTAR DESDE TU PROYECTO ===
from src.api.dependencies import get_db
from src.api.frontend import templates

from src.models.models import Emisor
from src.api.auth_utils import obtener_emisor_actual

# === DEPENDENCIAS NUEVAS ===
try:
    from passlib.context import CryptContext
    from jose import jwt, JWTError
except ImportError:
    raise ImportError(
        "Instala: pip install passlib[bcrypt] python-jose[cryptography]"
    )

router = APIRouter()

# ─────────────────────────────────────────────
# CONFIGURACIÓN (mover a .env en producción)
# ─────────────────────────────────────────────
SECRET_KEY = "CAMBIAR-EN-PRODUCCION-usar-variable-de-entorno"  # os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 1 semana
TRIAL_DAYS = 15

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────
def generar_api_credentials():
    """Genera api_key y api_secret para el nuevo emisor"""
    api_key = "fpl_" + secrets.token_hex(24)
    api_secret = secrets.token_hex(32)
    api_secret_hash = hashlib.sha256(api_secret.encode()).hexdigest()
    return api_key, api_secret, api_secret_hash


def crear_token(data: dict, expires_hours: int = TOKEN_EXPIRE_HOURS) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def obtener_usuario_actual(request: Request, db: Session) -> Emisor | None:
    """Obtiene el emisor logueado desde la cookie de sesión"""
    token = request.cookies.get("session_token")
    if not token:
        return None
    payload = verificar_token(token)
    if not payload:
        return None
    emisor_id = payload.get("emisor_id")
    if not emisor_id:
        return None
    return db.query(Emisor).filter(Emisor.id == emisor_id).first()


def validar_ruc(ruc: str) -> tuple[bool, str]:
    """Validación básica de RUC peruano"""
    if not ruc or len(ruc) != 11:
        return False, "El RUC debe tener 11 dígitos"
    if not ruc.isdigit():
        return False, "El RUC solo debe contener números"
    if ruc[:2] not in ("10", "15", "17", "20"):
        return False, "RUC no válido. Debe iniciar con 10, 15, 17 o 20"
    return True, ""


def validar_password(password: str) -> tuple[bool, str]:
    """Validación de contraseña"""
    if len(password) < 8:
        return False, "La contraseña debe tener mínimo 8 caracteres"
    if not re.search(r'[A-Z]', password):
        return False, "Debe contener al menos una mayúscula"
    if not re.search(r'[0-9]', password):
        return False, "Debe contener al menos un número"
    return True, ""


def validar_email(email: str) -> tuple[bool, str]:
    """Validación básica de email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Email no válido"
    return True, ""


# ─────────────────────────────────────────────
# PÁGINA DE REGISTRO - GET
# ─────────────────────────────────────────────
@router.get("/registro", response_class=HTMLResponse)
async def pagina_registro(request: Request, plan: str = ""):
    """Muestra el formulario de registro"""
    return templates.TemplateResponse("registro.html", {
        "request": request,
        "plan": plan,
        "error": None,
        "form_data": {}
    })


# ─────────────────────────────────────────────
# PÁGINA DE REGISTRO - POST
# ─────────────────────────────────────────────
@router.post("/registro", response_class=HTMLResponse)
async def procesar_registro(
    request: Request,
    ruc: str = Form(...),
    razon_social: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    nombre_contacto: str = Form(""),
    telefono: str = Form(""),
    plan: str = Form("emprendedor"),
    acepta_terminos: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Procesa el formulario de registro"""
    form_data = {
        "ruc": ruc.strip(),
        "razon_social": razon_social.strip(),
        "email": email.strip().lower(),
        "nombre_contacto": nombre_contacto.strip(),
        "telefono": telefono.strip(),
        "plan": plan
    }

    # --- Validaciones ---
    # 1. Términos
    if not acepta_terminos:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": "Debes aceptar los términos y condiciones",
            "form_data": form_data
        })

    # 2. RUC
    ruc_valido, ruc_error = validar_ruc(ruc.strip())
    if not ruc_valido:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": ruc_error,
            "form_data": form_data
        })

    # 3. Email
    email_valido, email_error = validar_email(email.strip())
    if not email_valido:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": email_error,
            "form_data": form_data
        })

    # 4. Password
    if password != password_confirm:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": "Las contraseñas no coinciden",
            "form_data": form_data
        })

    pwd_valido, pwd_error = validar_password(password)
    if not pwd_valido:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": pwd_error,
            "form_data": form_data
        })

    # 5. RUC duplicado
    existe_ruc = db.query(Emisor).filter(Emisor.ruc == ruc.strip()).first()
    if existe_ruc:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": f"El RUC {ruc} ya está registrado. ¿Olvidaste tu contraseña?",
            "form_data": form_data
        })

    # 6. Email duplicado
    existe_email = db.query(Emisor).filter(
        func.lower(Emisor.email) == email.strip().lower()
    ).first()
    if existe_email:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": "Este email ya está registrado",
            "form_data": form_data
        })

    # --- Crear emisor con cuenta trial ---
    api_key, api_secret, api_secret_hash = generar_api_credentials()

    nuevo_emisor = Emisor(
        id=str(uuid4()),
        ruc=ruc.strip(),
        razon_social=razon_social.strip(),
        email=email.strip().lower(),
        password_hash=pwd_context.hash(password[:72]),
        nombre_contacto=nombre_contacto.strip(),
        telefono=telefono.strip(),
        # API credentials
        api_key=api_key,
        api_secret=api_secret_hash,
        api_activa=True,
        # Trial config
        plan="trial",
        trial_inicio=datetime.now(timezone.utc),
        trial_fin=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
        docs_mes_limite=50,  # 50 docs en trial
        docs_mes_usados=0,
        modo_test=True,  # Empieza en modo prueba
        # Metadata
        creado_en=datetime.now(timezone.utc),
        activo=True,
    )

    try:
        db.add(nuevo_emisor)
        db.commit()
        db.refresh(nuevo_emisor)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": f"Error al crear la cuenta: {str(e)}",
            "form_data": form_data
        })

    # --- Login automático después del registro ---
    token = crear_token({
        "emisor_id": nuevo_emisor.id,
        "ruc": nuevo_emisor.ruc,
        "email": nuevo_emisor.email
    })

    # Redirigir al dashboard trial con el api_secret visible (solo esta vez)
    response = RedirectResponse(
        url=f"/mi-cuenta?bienvenido=1&secret={api_secret}",
        status_code=303
    )
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,     # Cambiar a False en localhost
        samesite="lax",
        max_age=TOKEN_EXPIRE_HOURS * 3600
    )
    return response


# ─────────────────────────────────────────────
# PÁGINA DE LOGIN - GET
# ─────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def pagina_login(request: Request, msg: str = ""):
    """Muestra el formulario de login"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "mensaje": msg
    })


# ─────────────────────────────────────────────
# PÁGINA DE LOGIN - POST
# ─────────────────────────────────────────────
@router.post("/login", response_class=HTMLResponse)
async def procesar_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Procesa el login"""
    # Buscar por email O por RUC
    emisor = db.query(Emisor).filter(
        (func.lower(Emisor.email) == email.strip().lower()) |
        (Emisor.ruc == email.strip())
    ).first()

    if not emisor or not emisor.password_hash:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Email/RUC o contraseña incorrectos",
            "mensaje": ""
        })

    if not pwd_context.verify(password[:72], emisor.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Email/RUC o contraseña incorrectos",
            "mensaje": ""
        })

    # Crear token de sesión
    token = crear_token({
        "emisor_id": emisor.id,
        "ruc": emisor.ruc,
        "email": emisor.email
    })

    response = RedirectResponse(url="/mi-cuenta", status_code=303)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=TOKEN_EXPIRE_HOURS * 3600
    )
    return response


# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────
@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login?msg=Sesión cerrada", status_code=303)
    response.delete_cookie("session_token")
    return response


# ─────────────────────────────────────────────
# DASHBOARD MI CUENTA (Trial + Activos)
# ─────────────────────────────────────────────
@router.get("/mi-cuenta", response_class=HTMLResponse)
async def dashboard_mi_cuenta(
    request: Request,
    bienvenido: int = 0,
    secret: str = "",
    db: Session = Depends(get_db)
):
    """Dashboard del usuario - muestra API keys, estado trial, etc."""
    emisor = obtener_usuario_actual(request, db)
    if not emisor:
        return RedirectResponse(url="/login", status_code=303)

    # Calcular días restantes de trial
    dias_restantes = None
    trial_activo = False
    if emisor.plan == "trial" and emisor.trial_fin:
        ahora = datetime.now(timezone.utc)
        if emisor.trial_fin.tzinfo is None:
            # Si trial_fin no tiene timezone, asumir UTC
            from datetime import timezone as tz
            trial_fin_utc = emisor.trial_fin.replace(tzinfo=tz.utc)
        else:
            trial_fin_utc = emisor.trial_fin
        delta = trial_fin_utc - ahora
        dias_restantes = max(0, delta.days)
        trial_activo = dias_restantes > 0

    # Porcentaje de documentos usados
    docs_porcentaje = 0
    if emisor.docs_mes_limite and emisor.docs_mes_limite > 0:
        docs_porcentaje = min(100, int(
            (emisor.docs_mes_usados or 0) / emisor.docs_mes_limite * 100
        ))

    return templates.TemplateResponse("mi_cuenta.html", {
        "request": request,
        "emisor": emisor,
        "bienvenido": bienvenido == 1,
        "api_secret_visible": secret if bienvenido == 1 else "",
        "dias_restantes": dias_restantes,
        "trial_activo": trial_activo,
        "docs_porcentaje": docs_porcentaje,
    })


# ─────────────────────────────────────────────
# OLVIDÉ MI CONTRASEÑA - GET
# ─────────────────────────────────────────────
@router.get("/olvide-clave", response_class=HTMLResponse)
async def pagina_olvide_clave(request: Request):
    return templates.TemplateResponse("olvide_clave.html", {
        "request": request,
        "error": None,
        "enviado": False
    })


# ─────────────────────────────────────────────
# OLVIDÉ MI CONTRASEÑA - POST
# ─────────────────────────────────────────────
@router.post("/olvide-clave", response_class=HTMLResponse)
async def procesar_olvide_clave(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    """Genera token de recuperación y (en producción) envía email"""
    emisor = db.query(Emisor).filter(
        func.lower(Emisor.email) == email.strip().lower()
    ).first()

    # Siempre mostrar éxito (no revelar si el email existe)
    if emisor:
        # Generar token de recuperación (1 hora de vida)
        reset_token = crear_token(
            {"emisor_id": emisor.id, "tipo": "reset"},
            expires_hours=1
        )
        # TODO: Enviar email con link:
        # https://facturalo.pro/restablecer-clave?token={reset_token}
        # Por ahora, imprimir en logs para desarrollo:
        print(f"[RESET] Token para {email}: {reset_token}")

    return templates.TemplateResponse("olvide_clave.html", {
        "request": request,
        "error": None,
        "enviado": True
    })


# ─────────────────────────────────────────────
# RESTABLECER CONTRASEÑA - GET
# ─────────────────────────────────────────────
@router.get("/restablecer-clave", response_class=HTMLResponse)
async def pagina_restablecer_clave(request: Request, token: str = ""):
    if not token:
        return RedirectResponse(url="/olvide-clave", status_code=303)

    payload = verificar_token(token)
    if not payload or payload.get("tipo") != "reset":
        return templates.TemplateResponse("restablecer_clave.html", {
            "request": request,
            "error": "El enlace ha expirado o no es válido. Solicita uno nuevo.",
            "token": "",
            "valido": False
        })

    return templates.TemplateResponse("restablecer_clave.html", {
        "request": request,
        "error": None,
        "token": token,
        "valido": True
    })


# ─────────────────────────────────────────────
# RESTABLECER CONTRASEÑA - POST
# ─────────────────────────────────────────────
@router.post("/restablecer-clave", response_class=HTMLResponse)
async def procesar_restablecer_clave(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db)
):
    payload = verificar_token(token)
    if not payload or payload.get("tipo") != "reset":
        return templates.TemplateResponse("restablecer_clave.html", {
            "request": request,
            "error": "El enlace ha expirado. Solicita uno nuevo.",
            "token": "",
            "valido": False
        })

    if password != password_confirm:
        return templates.TemplateResponse("restablecer_clave.html", {
            "request": request,
            "error": "Las contraseñas no coinciden",
            "token": token,
            "valido": True
        })

    pwd_valido, pwd_error = validar_password(password)
    if not pwd_valido:
        return templates.TemplateResponse("restablecer_clave.html", {
            "request": request,
            "error": pwd_error,
            "token": token,
            "valido": True
        })

    emisor = db.query(Emisor).filter(
        Emisor.id == payload["emisor_id"]
    ).first()

    if emisor:
        emisor.password_hash = pwd_context.hash(password[:72])
        db.commit()

    return RedirectResponse(
        url="/login?msg=Contraseña actualizada. Inicia sesión.",
        status_code=303
    )


# ─────────────────────────────────────────────
# CAMBIAR CONTRASEÑA (usuario logueado)
# ─────────────────────────────────────────────
@router.post("/mi-cuenta/cambiar-clave", response_class=HTMLResponse)
async def cambiar_clave(
    request: Request,
    clave_actual: str = Form(...),
    clave_nueva: str = Form(...),
    clave_confirmar: str = Form(...),
    db: Session = Depends(get_db)
):
    emisor = obtener_usuario_actual(request, db)
    if not emisor:
        return RedirectResponse(url="/login", status_code=303)

    if not pwd_context.verify(clave_actual[:72], emisor.password_hash):
        # Redirigir con error
        return RedirectResponse(
            url="/mi-cuenta?error_clave=La contraseña actual es incorrecta",
            status_code=303
        )

    if clave_nueva != clave_confirmar:
        return RedirectResponse(
            url="/mi-cuenta?error_clave=Las contraseñas nuevas no coinciden",
            status_code=303
        )

    pwd_valido, pwd_error = validar_password(clave_nueva)
    if not pwd_valido:
        return RedirectResponse(
            url=f"/mi-cuenta?error_clave={pwd_error}",
            status_code=303
        )

    emisor.password_hash = pwd_context.hash(clave_nueva[:72])
    db.commit()

    return RedirectResponse(
        url="/mi-cuenta?msg=Contraseña actualizada correctamente",
        status_code=303
    )


# ─────────────────────────────────────────────
# API: Validar RUC en tiempo real (AJAX)
# ─────────────────────────────────────────────
@router.get("/api/validar-ruc/{ruc}")
async def api_validar_ruc(ruc: str, db: Session = Depends(get_db)):
    """Endpoint AJAX para validar RUC durante el registro"""
    valido, error = validar_ruc(ruc)
    if not valido:
        return {"valido": False, "error": error}

    # Verificar si ya existe
    existe = db.query(Emisor).filter(Emisor.ruc == ruc).first()
    if existe:
        return {"valido": False, "error": "Este RUC ya está registrado"}

    # TODO: Consultar API SUNAT para obtener razón social
    # Por ahora, solo validación local
    return {"valido": True, "error": None}


# ─────────────────────────────────────────────
# UTILIDAD: Obtener emisor actual desde JWT
#─────────────────────────────────────────────

async def obtener_emisor_actual(request: Request, db: Session) -> Emisor:
    """Obtiene el emisor autenticado desde el JWT"""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autorizado")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        emisor_id = payload.get("emisor_id")
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesión expirada")
    
    emisor = db.query(Emisor).filter(Emisor.id == emisor_id).first()
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    
    return emisor