"""
Selectores de documentos de referencia para la GRE (zGuia-13).

Auth del dashboard (obtener_emisor_actual), como /api/productos/buscar.

Rutas:
  GET /api/comprobantes/recientes?q=        facturas ACEPTADAS (últimos 60 días)
  GET /api/docs-referencia?tipo=&q=         documentos para filas de docs
                                            relacionados (09=guías; 50=DAM placeholder)
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.models.models import Comprobante, GuiaRemision
from src.services.gre_service import peru_now

router = APIRouter(prefix="/api", tags=["referencias"])

VENTANA_DIAS = 60
COMP_ACEPTADOS = ("aceptado", "aceptado_con_observaciones")
GUIA_ACEPTADAS = ("aceptado", "aceptado_observado")


@router.get("/comprobantes/recientes")
async def comprobantes_recientes(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Facturas (tipo 01) ACEPTADAS del emisor, últimos 60 días, más reciente
    primero. Búsqueda por número (serie-numero) o cliente. Para el selector de
    factura de referencia de la GRE."""
    emisor = await obtener_emisor_actual(request, db)
    desde = peru_now().date() - timedelta(days=VENTANA_DIAS)

    query = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor.id,
        Comprobante.tipo_documento == "01",
        Comprobante.estado.in_(COMP_ACEPTADOS),
        Comprobante.fecha_emision >= desde,
    )
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Comprobante.numero_formato.ilike(like),
            Comprobante.serie.ilike(like),
            Comprobante.cliente_razon_social.ilike(like),
            Comprobante.cliente_numero_documento.ilike(like),
        ))

    comps = query.order_by(Comprobante.fecha_emision.desc(),
                           Comprobante.numero.desc()).limit(15).all()
    return {
        "exito": True,
        "datos": [{
            "id": c.id,
            "serie": c.serie,
            "numero": c.numero,
            "label": c.numero_formato or f"{c.serie}-{c.numero}",
            "fecha": str(c.fecha_emision)[:10] if c.fecha_emision else "",
            "cliente": c.cliente_razon_social or c.cliente_numero_documento or "",
            "total": float(c.monto_total or 0),
            "moneda": c.moneda or "PEN",
        } for c in comps],
    }


@router.get("/docs-referencia")
async def docs_referencia(request: Request, tipo: str = "", q: str = "", db: Session = Depends(get_db)):
    """Documentos para las filas de documentos relacionados de la GRE.

    Forma uniforme de cada ítem: {numero, label, sublabel, emisor_ruc} — pensada
    para que CUALQUIER fuente (guías, y a futuro DAM de importaciones) se liste
    igual que las facturas.

      tipo 09 (guía remitente): guías ACEPTADAS del emisor, últimos 60 días.
      tipo 50 (DAM):            vacío POR AHORA — extensión: cuando exista el
                                módulo de importaciones, listar aquí las DAM
                                registradas con la misma forma.
      otros:                    sin sugerencias (entrada manual).
    """
    emisor = await obtener_emisor_actual(request, db)
    tipo = (tipo or "").strip()
    q = (q or "").strip()
    desde = peru_now().date() - timedelta(days=VENTANA_DIAS)
    datos = []

    if tipo == "09":
        query = db.query(GuiaRemision).filter(
            GuiaRemision.emisor_id == emisor.id,
            GuiaRemision.estado.in_(GUIA_ACEPTADAS),
            GuiaRemision.numero.isnot(None),
            GuiaRemision.fecha_emision >= desde,
        )
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                GuiaRemision.serie.ilike(like),
                GuiaRemision.dest_razon_social.ilike(like),
            ))
        guias = query.order_by(GuiaRemision.created_at.desc()).limit(15).all()
        for g in guias:
            datos.append({
                "numero": f"{g.serie}-{g.numero}",
                "label": f"{g.serie}-{g.numero}",
                "sublabel": (g.dest_razon_social or "")[:40],
                # Guía emitida por el propio emisor -> su RUC es el emisor del doc.
                "emisor_ruc": emisor.ruc,
            })

    elif tipo == "50":
        # DAM: documento externo. Sin fuente hasta el módulo de importaciones real.
        # Extensión futura: poblar `datos` con las DAM registradas (misma forma).
        datos = []

    return {"exito": True, "tipo": tipo, "datos": datos}
