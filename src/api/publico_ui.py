"""
publico_ui.py — Página pública por comprobante (Task C, compartir/descargar).

Ruta top-level /c/{token} (NO bajo /api → sin conflicto con el catch-all
/api/comprobantes/{id} ni con /api/v1/*). El acceso es por token aleatorio no
adivinable (comprobante.share_token, ~256 bits); no requiere API key.

Muestra datos básicos + estado y permite descargar PDF, XML y CDR (ZIP).

Zona libre (archivo nuevo). No toca emisión, XML ni el flujo SOAP: solo lee datos ya
guardados y reusa el generador de PDF existente.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.models.models import Comprobante, Emisor, Cliente, LineaDetalle

router = APIRouter()

_TIPOS = {
    "01": "Factura electrónica",
    "03": "Boleta de venta electrónica",
    "07": "Nota de crédito electrónica",
    "08": "Nota de débito electrónica",
}

# Estado → (etiqueta, color de fondo, color de texto, color de borde)
_ESTADOS = {
    "aceptado": ("Aceptado por SUNAT", "#ecfdf5", "#047857", "#a7f3d0"),
    "aceptado_con_observaciones": ("Aceptado con observaciones", "#fffbeb", "#b45309", "#fde68a"),
    "rechazado": ("Rechazado por SUNAT", "#fef2f2", "#b91c1c", "#fecaca"),
    "anulado": ("Anulado", "#f3f4f6", "#374151", "#e5e7eb"),
}


def _buscar_por_token(db: Session, token: str) -> Comprobante:
    token = (token or "").strip()
    # Guardas: token vacío o absurdamente largo → 404 sin tocar BD.
    if not token or len(token) > 64:
        raise HTTPException(404, detail="No encontrado")
    comp = db.query(Comprobante).filter(Comprobante.share_token == token).first()
    if not comp:
        raise HTTPException(404, detail="No encontrado")
    return comp


def _esc(s) -> str:
    s = "" if s is None else str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


@router.get("/c/{token}", response_class=HTMLResponse, include_in_schema=False)
def pagina_publica(token: str, db: Session = Depends(get_db)):
    comp = _buscar_por_token(db, token)
    emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()

    tipo = _TIPOS.get(comp.tipo_documento, "Comprobante electrónico")
    numero = comp.numero_formato or f"{comp.serie}-{comp.numero:08d}"
    fecha = comp.fecha_emision.strftime("%d/%m/%Y") if comp.fecha_emision else "—"
    etiqueta, bg, fg, bd = _ESTADOS.get(
        comp.estado, (comp.estado or "—", "#f3f4f6", "#374151", "#e5e7eb"))
    total = f"{float(comp.monto_total or 0):,.2f}"
    moneda = comp.moneda or "PEN"
    simbolo = "S/" if moneda == "PEN" else moneda + " "

    msg_sunat = ""
    if comp.respuesta and comp.respuesta.descripcion:
        msg_sunat = comp.respuesta.descripcion

    # Descargas disponibles según lo que exista.
    tiene_xml = bool(comp.xml)
    tiene_cdr = bool(comp.respuesta and comp.respuesta.cdr_xml)

    botones = [
        f'<a class="btn" href="/c/{_esc(token)}/pdf" target="_blank" rel="noopener">Descargar PDF</a>'
    ]
    if tiene_xml:
        botones.append(f'<a class="btn btn-sec" href="/c/{_esc(token)}/xml">XML firmado</a>')
    if tiene_cdr:
        botones.append(f'<a class="btn btn-sec" href="/c/{_esc(token)}/cdr">CDR (ZIP)</a>')

    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{_esc(numero)} · {_esc(emisor.razon_social if emisor else 'Comprobante')}</title>
<style>
  :root {{ --line:#e5e7eb; --muted:#6b7280; --ink:#111827; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#f8fafc; color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.5; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:24px 16px 48px; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:14px;
    padding:22px 20px; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
  .emisor {{ font-weight:700; font-size:17px; }}
  .ruc {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  .tipo {{ color:var(--muted); font-size:13px; margin-top:16px; text-transform:uppercase;
    letter-spacing:.04em; }}
  .numero {{ font-size:26px; font-weight:800; letter-spacing:.01em; margin:2px 0 4px; }}
  .estado {{ display:inline-block; font-size:13px; font-weight:600; padding:5px 12px;
    border-radius:999px; background:{bg}; color:{fg}; border:1px solid {bd}; margin:6px 0 2px; }}
  .msg {{ color:var(--muted); font-size:13px; margin-top:8px; }}
  .grid {{ margin-top:18px; border-top:1px solid var(--line); padding-top:16px; }}
  .row {{ display:flex; justify-content:space-between; gap:12px; padding:6px 0; font-size:14px; }}
  .row .k {{ color:var(--muted); }}
  .row .v {{ text-align:right; font-weight:600; }}
  .total {{ font-size:20px; }}
  .btns {{ margin-top:22px; display:flex; flex-direction:column; gap:10px; }}
  .btn {{ display:block; text-align:center; text-decoration:none; padding:13px 16px;
    border-radius:10px; font-weight:700; font-size:15px; background:#111827; color:#fff;
    border:1px solid #111827; }}
  .btn-sec {{ background:#fff; color:#111827; border:1px solid var(--line); font-weight:600; }}
  .pie {{ text-align:center; color:var(--muted); font-size:12px; margin-top:22px; }}
  .pie a {{ color:var(--muted); }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="emisor">{_esc(emisor.razon_social if emisor else '')}</div>
      <div class="ruc">RUC {_esc(emisor.ruc if emisor else '')}</div>

      <div class="tipo">{_esc(tipo)}</div>
      <div class="numero">{_esc(numero)}</div>
      <span class="estado">{_esc(etiqueta)}</span>
      {f'<div class="msg">{_esc(msg_sunat)}</div>' if msg_sunat else ''}

      <div class="grid">
        <div class="row"><span class="k">Fecha de emisión</span><span class="v">{_esc(fecha)}</span></div>
        <div class="row"><span class="k">Cliente</span><span class="v">{_esc(comp.cliente_razon_social or '—')}</span></div>
        <div class="row"><span class="k">Documento</span><span class="v">{_esc(comp.cliente_numero_documento or '—')}</span></div>
        <div class="row total"><span class="k">Total</span><span class="v">{_esc(simbolo)}{total}</span></div>
      </div>

      <div class="btns">
        {''.join(botones)}
      </div>
    </div>
    <div class="pie">Comprobante electrónico · <a href="https://facturalo.pro" target="_blank" rel="noopener">facturalo.pro</a></div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/c/{token}/pdf", include_in_schema=False)
def publico_pdf(token: str, formato: str = "A4", db: Session = Depends(get_db)):
    comp = _buscar_por_token(db, token)
    emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
    if not emisor:
        raise HTTPException(404, detail="No encontrado")
    items = db.query(LineaDetalle).filter(
        LineaDetalle.comprobante_id == comp.id).order_by(LineaDetalle.orden).all()
    cliente = db.query(Cliente).filter(Cliente.id == comp.cliente_id).first()

    fmt = (formato or "A4").upper()
    if fmt not in ("A4", "A5", "TICKET"):
        fmt = "A4"
    codigo_matricula = comp.observaciones if (comp.observaciones and comp.observaciones.startswith("10-")) else None

    from src.api.v1.pdf_generator import generar_pdf_comprobante
    try:
        pdf_bytes = generar_pdf_comprobante(comp, emisor, cliente, items,
                                            formato=fmt, codigo_matricula=codigo_matricula)
    except Exception as e:
        raise HTTPException(500, detail=f"Error al generar PDF: {e}")

    fecha_str = comp.fecha_emision.strftime("%Y%m%d") if comp.fecha_emision else ""
    filename = f"{emisor.ruc}_{comp.serie}-{comp.numero:08d}_{fecha_str}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/c/{token}/xml", include_in_schema=False)
def publico_xml(token: str, db: Session = Depends(get_db)):
    comp = _buscar_por_token(db, token)
    if not comp.xml:
        raise HTTPException(404, detail="XML no disponible")
    emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
    filename = f"{emisor.ruc}-{comp.tipo_documento}-{comp.serie}-{comp.numero:08d}.xml"
    return Response(
        content=comp.xml if isinstance(comp.xml, (bytes, bytearray)) else comp.xml.encode(),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/c/{token}/cdr", include_in_schema=False)
def publico_cdr(token: str, db: Session = Depends(get_db)):
    comp = _buscar_por_token(db, token)
    cdr_xml = comp.respuesta.cdr_xml if comp.respuesta else None
    if not cdr_xml:
        raise HTTPException(404, detail="CDR no disponible")
    emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
    # Reusa el empaquetador del endpoint autenticado (ZIP estándar R-<nombre>.zip).
    from src.api.v1.comprobantes import _cdr_zip_bytes, _nombre_cdr
    base = _nombre_cdr(emisor, comp)
    return Response(
        content=_cdr_zip_bytes(emisor, comp, cdr_xml),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="R-{base}.zip"'})
