"""
UI de stock/kardex sobre la tabla `producto` existente.

El catálogo (lista, crear, editar, desactivar) lo maneja /productos
(dashboard/productos.html + api/productos.py). Aquí solo vive lo específico de
stock: kardex por producto y entrada/ajuste manual.

Rutas:
  GET  /stock                      -> redirige a /productos (catálogo + stock)
  GET  /stock/{id}/kardex          movimientos del producto
  GET  /stock/ajuste               form de entrada/ajuste manual
  POST /stock/ajuste               registra movimiento manual

Auth por emisor. Sin alert/confirm nativos.
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.api.frontend import templates
from src.models.models import Producto, MovimientoStock
from src.services.stock_service import registrar_movimiento

router = APIRouter()


def _dec_or_none(valor):
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


@router.get("/stock")
async def stock_index():
    # El catálogo con stock ya vive en /productos.
    return RedirectResponse(url="/productos")


@router.get("/stock/ajuste", response_class=HTMLResponse)
async def stock_ajuste_form(request: Request, producto_id: str = "", db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")

    productos = (
        db.query(Producto)
        .filter_by(emisor_id=emisor.id, activo=True)
        .order_by(Producto.codigo_interno)
        .all()
    )
    return templates.TemplateResponse("stock/ajuste.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "productos": productos, "producto_sel": producto_id,
    })


@router.post("/stock/ajuste")
async def stock_ajuste_post(
    request: Request,
    producto_id: str = Form(...),
    tipo: str = Form(...),
    cantidad: str = Form(...),
    glosa: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login", status_code=303)

    cant = _dec_or_none(cantidad)
    if tipo in ("entrada", "salida", "ajuste") and cant is not None:
        try:
            registrar_movimiento(
                db, emisor.id, producto_id, tipo, cant,
                origen_tipo="manual", origen_id=None,
                glosa=(glosa or "").strip() or f"Movimiento manual ({tipo})",
            )
        except Exception:
            db.rollback()
    return RedirectResponse(url=f"/stock/{producto_id}/kardex", status_code=303)


@router.get("/stock/{producto_id}/kardex", response_class=HTMLResponse)
async def stock_kardex(producto_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")

    prod = (
        db.query(Producto)
        .filter_by(id=producto_id, emisor_id=emisor.id)
        .first()
    )
    if not prod:
        return RedirectResponse(url="/productos")

    movimientos = (
        db.query(MovimientoStock)
        .filter_by(producto_id=producto_id, emisor_id=emisor.id)
        .order_by(MovimientoStock.fecha.desc(), MovimientoStock.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("stock/kardex.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "producto": prod, "movimientos": movimientos,
    })
