"""
UI de Guías de Remisión Electrónica (GRE) — listado + emisión.

Consume gre_service.emitir_guia (síncrono) sin modificarlo. Misma auth del
dashboard (obtener_emisor_actual).

Rutas:
  GET  /guias                     listado
  GET  /guias/nueva               form de emisión (?comprobante_id= pre-llena)
  POST /guias/emitir              crea la GRE y la emite (JSON in/out)
  POST /guias/{id}/reintentar     reintenta emisión (estado 'error')
  GET  /guias/{id}/pdf            sirve GuiaRemision.pdf (inline)
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from sqlalchemy.orm import Session, defer

from src.api.dependencies import get_db
from src.api.auth_utils import obtener_emisor_actual
from src.api.frontend import templates
from src.models.models import (
    Emisor, Comprobante, GuiaRemision, GuiaRemisionItem, GuiaRemisionDocRelacionado,
)
from src.services.gre_service import emitir_guia, peru_now
from src.services.pdf_generator_gre import (
    MOTIVOS_TRASLADO, MODALIDADES_TRASLADO, TIPOS_DOC_RELACIONADO,
)

router = APIRouter()

# Tono de badge por estado
ESTADO_TONO = {
    "pendiente": "muted",
    "enviado": "info",
    "aceptado": "success",
    "aceptado_observado": "success",
    "rechazado": "danger",
    "error": "warning",
}


def _dec(valor, default="0"):
    try:
        return Decimal(str(valor if valor not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _int_or_none(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (ValueError, TypeError):
        return None


@router.get("/guias", response_class=HTMLResponse)
async def guias_list(request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")

    guias = (
        db.query(GuiaRemision)
        .filter(GuiaRemision.emisor_id == emisor.id)
        # No cargar blobs en el listado.
        .options(defer(GuiaRemision.pdf), defer(GuiaRemision.xml_firmado),
                 defer(GuiaRemision.cdr_zip))
        .order_by(GuiaRemision.created_at.desc())
        .limit(100)
        .all()
    )
    # Mapa de comprobantes vinculados (serie-numero) para el listado.
    comp_ids = [g.comprobante_id for g in guias if g.comprobante_id]
    comps = {}
    if comp_ids:
        for c in db.query(Comprobante).filter(Comprobante.id.in_(comp_ids)).all():
            comps[c.id] = f"{c.serie}-{c.numero}"

    # Documentos relacionados por guía (defensivo: la tabla puede no existir aún).
    docs_rel = {}
    try:
        guia_ids = [g.id for g in guias]
        if guia_ids:
            for d in (db.query(GuiaRemisionDocRelacionado)
                      .filter(GuiaRemisionDocRelacionado.guia_id.in_(guia_ids))
                      .order_by(GuiaRemisionDocRelacionado.orden).all()):
                docs_rel.setdefault(d.guia_id, []).append(d)
    except Exception:
        db.rollback()
        docs_rel = {}

    return templates.TemplateResponse("guias/list.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "guias": guias, "comps": comps, "docs_rel": docs_rel,
        "tipos_doc_rel": TIPOS_DOC_RELACIONADO,
        "motivos": MOTIVOS_TRASLADO, "estado_tono": ESTADO_TONO,
    })


@router.get("/guias/nueva", response_class=HTMLResponse)
async def guias_nueva(request: Request, comprobante_id: str = "", db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")

    prefill = {
        "comprobante_id": "",
        "dest_tipo_doc": "6", "dest_num_doc": "", "dest_razon_social": "",
        "llegada_direccion": "",
        "items": [],
    }
    comp_label = ""
    if comprobante_id:
        comp = (
            db.query(Comprobante)
            .filter(Comprobante.id == comprobante_id, Comprobante.emisor_id == emisor.id)
            .first()
        )
        if comp:
            prefill["comprobante_id"] = comp.id
            prefill["dest_tipo_doc"] = comp.cliente_tipo_documento or "6"
            prefill["dest_num_doc"] = comp.cliente_numero_documento or ""
            prefill["dest_razon_social"] = comp.cliente_razon_social or ""
            prefill["llegada_direccion"] = comp.cliente_direccion or ""
            comp_label = f"{comp.serie}-{comp.numero}"
            for ln in (comp.lineas or []):
                prefill["items"].append({
                    "codigo": ln.codigo or "",
                    "descripcion": ln.descripcion or "",
                    "cantidad": float(ln.cantidad or 1),
                    "unidad_medida": ln.unidad or "NIU",
                })

    return templates.TemplateResponse("guias/nueva.html", {
        "request": request, "emisor": emisor, "user_ruc": emisor.ruc,
        "prefill": prefill, "comp_label": comp_label,
        "hoy": peru_now().date().isoformat(),
        "partida_ubigeo_def": emisor.ubigeo or "",
        "partida_direccion_def": emisor.direccion or "",
        "tipos_doc_rel": TIPOS_DOC_RELACIONADO,
    })


def _es_ubigeo(v) -> bool:
    v = (str(v) if v is not None else "").strip()
    return len(v) == 6 and v.isdigit()


def _validar_payload_gre(data: dict, emisor: Emisor) -> str | None:
    """Validación de servidor (espejo de la del cliente). Devuelve el primer
    mensaje de error claro, o None si todo está OK."""
    # Items
    items = [it for it in (data.get("items") or [])
             if (it.get("descripcion") or "").strip()]
    if not items:
        return "Agrega al menos un ítem con descripción."
    for i, it in enumerate(items, start=1):
        cant = _dec(it.get("cantidad"), "0")
        if cant <= 0:
            return f"El ítem {i} ('{(it.get('descripcion') or '').strip()[:30]}') necesita una cantidad mayor a 0."

    # Peso
    if _dec(data.get("peso_bruto_total"), "0") <= 0:
        return "El peso bruto total debe ser mayor a 0."

    # Motivo 13 → descripción obligatoria
    motivo = (data.get("motivo_traslado") or "01").strip()
    if motivo == "13" and not (data.get("descripcion_motivo") or "").strip():
        return "El motivo 'Otros' (13) requiere una descripción."

    # Transporte
    modalidad = (data.get("modalidad_traslado") or "02").strip()
    if modalidad == "02" and not bool(data.get("indicador_vehiculo_m1l")):
        if not (data.get("vehiculo_placa") or "").strip() or not (data.get("conductor_num_doc") or "").strip():
            return "Transporte privado: indica la placa del vehículo y el documento del conductor."
    elif modalidad == "01":
        if not (data.get("transportista_num_doc") or "").strip():
            return "Transporte público: indica el RUC del transportista."

    # Ubigeos (partida cae al del emisor si viene vacío)
    partida_ubigeo = (data.get("partida_ubigeo") or emisor.ubigeo or "")
    if not _es_ubigeo(partida_ubigeo):
        return "El ubigeo de partida debe tener 6 dígitos numéricos."
    if not _es_ubigeo(data.get("llegada_ubigeo")):
        return "El ubigeo de llegada debe tener 6 dígitos numéricos."

    # Documentos relacionados: número + RUC emisor obligatorios
    for j, doc in enumerate(data.get("documentos_relacionados") or [], start=1):
        numero = (doc.get("numero") or "").strip()
        ruc = (doc.get("emisor_doc_ruc") or "").strip()
        if not numero:
            return f"El documento relacionado #{j} necesita un número."
        if len(ruc) != 11 or not ruc.isdigit():
            return f"El documento relacionado #{j} necesita el RUC (11 dígitos) de su emisor."
    return None


def _crear_guia_desde_payload(db, emisor: Emisor, data: dict) -> GuiaRemision:
    serie = emisor.gre_serie or "T060"
    g = GuiaRemision(
        emisor_id=emisor.id,
        serie=serie,
        numero=None,  # lo asigna emitir_guia al confirmar el envío
        fecha_emision=data.get("fecha_emision") or peru_now().date().isoformat(),
        fecha_inicio_traslado=data.get("fecha_inicio_traslado") or peru_now().date().isoformat(),
        motivo_traslado=(data.get("motivo_traslado") or "01"),
        descripcion_motivo=data.get("descripcion_motivo") or None,
        modalidad_traslado=(data.get("modalidad_traslado") or "02"),
        peso_bruto_total=_dec(data.get("peso_bruto_total"), "0"),
        unidad_peso=data.get("unidad_peso") or "KGM",
        numero_bultos=_int_or_none(data.get("numero_bultos")),
        indicador_vehiculo_m1l=bool(data.get("indicador_vehiculo_m1l")),
        dest_tipo_doc=data.get("dest_tipo_doc") or "6",
        dest_num_doc=data.get("dest_num_doc") or "",
        dest_razon_social=data.get("dest_razon_social") or "",
        partida_ubigeo=data.get("partida_ubigeo") or emisor.ubigeo,
        partida_direccion=data.get("partida_direccion") or emisor.direccion,
        llegada_ubigeo=data.get("llegada_ubigeo") or "",
        llegada_direccion=data.get("llegada_direccion") or "",
        comprobante_id=(data.get("comprobante_id") or None),
        estado="pendiente",
    )

    # Transporte condicional
    if g.modalidad_traslado == "02" and not g.indicador_vehiculo_m1l:
        g.vehiculo_placa = data.get("vehiculo_placa") or None
        g.conductor_tipo_doc = data.get("conductor_tipo_doc") or "1"
        g.conductor_num_doc = data.get("conductor_num_doc") or None
        g.conductor_nombres = data.get("conductor_nombres") or None
        g.conductor_licencia = data.get("conductor_licencia") or None
    elif g.modalidad_traslado == "01":
        g.transportista_tipo_doc = data.get("transportista_tipo_doc") or "6"
        g.transportista_num_doc = data.get("transportista_num_doc") or None
        g.transportista_razon_social = data.get("transportista_razon_social") or None

    g.items = []
    for i, it in enumerate(data.get("items", []), start=1):
        if not (it.get("descripcion") or "").strip():
            continue
        g.items.append(GuiaRemisionItem(
            orden=i,
            codigo=(it.get("codigo") or None),
            descripcion=it.get("descripcion") or "",
            cantidad=_dec(it.get("cantidad"), "1"),
            unidad_medida=it.get("unidad_medida") or "NIU",
        ))

    # Documentos relacionados (FASE 1). El comprobante_id sigue generando su
    # referencia tipo 01 aparte; aquí van SOLO los adicionales.
    g.docs_relacionados = []
    for j, doc in enumerate(data.get("documentos_relacionados", []), start=1):
        tipo = (doc.get("tipo_doc") or "").strip()
        numero = (doc.get("numero") or "").strip()
        if not tipo or not numero:
            continue
        g.docs_relacionados.append(GuiaRemisionDocRelacionado(
            orden=j,
            tipo_doc=tipo,
            descripcion=(doc.get("descripcion") or None),
            numero=numero,
            emisor_doc_ruc=(doc.get("emisor_doc_ruc") or None),
        ))

    db.add(g)
    db.commit()
    return g


@router.post("/guias/emitir")
async def guias_emitir(request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return JSONResponse({"exito": False, "error": "No autorizado"}, status_code=401)

    data = await request.json()
    error = _validar_payload_gre(data, emisor)
    if error:
        return JSONResponse({"exito": False, "error": error}, status_code=400)

    try:
        guia = _crear_guia_desde_payload(db, emisor, data)
    except Exception as e:
        db.rollback()
        return JSONResponse({"exito": False, "error": f"Error creando la guía: {e}"}, status_code=400)

    resultado = emitir_guia(db, guia.id)
    resultado["guia_id"] = guia.id
    if resultado.get("exito") or resultado.get("estado") in ("aceptado", "aceptado_observado", "enviado"):
        resultado["redirect"] = "/guias"
    return JSONResponse(resultado)


@router.post("/guias/{guia_id}/reintentar")
async def guias_reintentar(guia_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return JSONResponse({"exito": False, "error": "No autorizado"}, status_code=401)

    guia = (
        db.query(GuiaRemision)
        .filter(GuiaRemision.id == guia_id, GuiaRemision.emisor_id == emisor.id)
        .first()
    )
    if not guia:
        return JSONResponse({"exito": False, "error": "Guía no encontrada"}, status_code=404)

    resultado = emitir_guia(db, guia.id)
    resultado["guia_id"] = guia.id
    resultado["redirect"] = "/guias"
    return JSONResponse(resultado)


@router.get("/guias/{guia_id}/pdf")
async def guias_pdf(guia_id: str, request: Request, regen: int = 0, db: Session = Depends(get_db)):
    try:
        emisor = await obtener_emisor_actual(request, db)
    except Exception:
        return RedirectResponse(url="/login")

    guia = (
        db.query(GuiaRemision)
        .filter(GuiaRemision.id == guia_id, GuiaRemision.emisor_id == emisor.id)
        .first()
    )
    if not guia:
        return RedirectResponse(url="/guias")

    # FASE 4 — Regenerar el PDF EN producción (con logo) y re-cachear antes de servir.
    # Solo guías aceptadas: el PDF cacheado pudo generarse en local sin acceso al logo.
    if regen and guia.estado in ("aceptado", "aceptado_observado"):
        from src.services.pdf_generator_gre import generar_pdf_gre
        try:
            guia.pdf = generar_pdf_gre(db, guia.id)
            db.commit()
        except Exception:
            db.rollback()

    if not guia.pdf:
        return RedirectResponse(url="/guias")

    return Response(
        content=bytes(guia.pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{guia.serie}-{guia.numero}.pdf"'},
    )
