"""
Panel Importadores (MOCK navegable) — demo Glen Cask.

Vistas Jinja2 alimentadas por importaciones_mock. Misma auth del dashboard
(obtener_emisor_actual). NO toca ningún flujo real.

Rutas:
  GET /importaciones                          listado de operaciones
  GET /importaciones/{codigo}                 detalle (timeline + secciones)
  GET /importaciones/{codigo}/export/{fmt}    descarga Pre-DAM (txt/xml/json)
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.api.frontend import templates
from src.services import importaciones_mock as mock

router = APIRouter()


@router.get("/importaciones", response_class=HTMLResponse)
async def importaciones_list(request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("importaciones/list.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "operaciones": mock.listar_operaciones(),
    })


@router.get("/importaciones/{codigo}/export/{fmt}")
async def importaciones_export(codigo: str, fmt: str, request: Request, db: Session = Depends(get_db)):
    try:
        await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")
    res = mock.exportar_pre_dam(codigo, fmt)
    if not res:
        return RedirectResponse(url=f"/importaciones/{codigo}")
    contenido, media_type, filename = res
    return Response(
        content=contenido,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/importaciones/{codigo}", response_class=HTMLResponse)
async def importaciones_detalle(codigo: str, request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")
    op = mock.obtener_operacion(codigo)
    if not op:
        return RedirectResponse(url="/importaciones")
    return templates.TemplateResponse("importaciones/detalle.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "op": op,
    })
