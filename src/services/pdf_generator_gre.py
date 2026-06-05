"""
Generador de la representación impresa (PDF A4) de la Guía de Remisión
Electrónica Remitente (GRE, tipo 09), con código QR obligatorio.

Mismas convenciones que el pdf_generator de facturas (ReportLab canvas + paleta
de src.services.pdf_templates.base). Módulo GRE separado: NO toca el flujo de
facturas, solo reutiliza colores/utilidades de estilo.

Composición del QR (verificada contra Greenter `QrRender::getImageDespatch`,
alineado a la representación impresa SUNAT para documentos sin monto):

    {RUC}|{tipoDoc=09}|{serie}|{numero}|{fechaEmision yyyy-mm-dd}|{tipoDocDest}|{numDocDest}|

El número va crudo (sin padding) para coincidir con el cbc:ID del XML ({serie}-{numero}).

API pública:
    generar_pdf_gre(db, guia_id) -> bytes
"""
import io
import logging

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import black, white
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader

from src.services.pdf_templates.base import (
    COLOR_PRIMARIO, COLOR_SECUNDARIO, COLOR_GRIS_TEXTO, COLOR_GRIS_FONDO,
    COLOR_GRIS_OSCURO, COLOR_LINEA, COLOR_BORDE, COLOR_VERDE,
    _rounded_rect, _safe_float,
)
from src.models.models import Emisor, GuiaRemision

logger = logging.getLogger(__name__)

TIPO_DOC_GRE = "09"
TITULO_GRE = "GUÍA DE REMISIÓN ELECTRÓNICA REMITENTE"

# Catálogo 20 — Motivo de traslado
MOTIVOS_TRASLADO = {
    "01": "Venta",
    "02": "Compra",
    "04": "Traslado entre establecimientos de la misma empresa",
    "08": "Importación",
    "09": "Exportación",
    "13": "Otros",
    "14": "Venta sujeta a confirmación del comprador",
    "17": "Traslado de bienes para transformación",
    "18": "Traslado emisor itinerante CP",
    "19": "Traslado a zona primaria",
}

# Catálogo 18 — Modalidad de traslado
MODALIDADES_TRASLADO = {
    "01": "Transporte público",
    "02": "Transporte privado",
}

# Catálogo 06 — Tipos de documento de identidad (para el destinatario)
TIPOS_DOC_IDENTIDAD = {
    "0": "DOC.", "1": "DNI", "4": "C.EXT.", "6": "RUC", "7": "PASAPORTE", "A": "CED.DIPL.",
}


def _qr_text(guia: GuiaRemision, emisor: Emisor) -> str:
    """Texto del QR de la GRE (formato Greenter/SUNAT, separado por |)."""
    fecha = guia.fecha_emision.strftime("%Y-%m-%d") if guia.fecha_emision else ""
    campos = [
        emisor.ruc or "",
        TIPO_DOC_GRE,
        guia.serie or "",
        str(guia.numero if guia.numero is not None else ""),
        fecha,
        str(guia.dest_tipo_doc or ""),
        str(guia.dest_num_doc or ""),
    ]
    return "|".join(campos) + "|"


def _draw_logo(c, emisor, x, y, w, h):
    """Dibuja el logo del emisor (blob o logo_url). Devuelve True si se cargó."""
    if getattr(emisor, "logo", None):
        try:
            c.drawImage(ImageReader(io.BytesIO(emisor.logo)), x, y, w, h,
                        preserveAspectRatio=True, mask="auto")
            return True
        except Exception as e:
            logger.warning("[PDF_GRE] Error cargando logo (blob): %s", e)
    url = getattr(emisor, "logo_url", None)
    if url:
        try:
            if url.startswith("/"):
                with open(url, "rb") as f:
                    data = f.read()
            else:
                import urllib.request
                data = urllib.request.urlopen(url, timeout=5).read()
            c.drawImage(ImageReader(io.BytesIO(data)), x, y, w, h,
                        preserveAspectRatio=True, mask="auto")
            return True
        except Exception as e:
            logger.warning("[PDF_GRE] Error cargando logo (url): %s", e)
    return False


def _label_valor(c, x, y, label, valor, label_w=38 * mm, size=8):
    """Dibuja 'label: valor' con la etiqueta en negrita."""
    c.setFont("Helvetica-Bold", size)
    c.setFillColor(black)
    c.drawString(x, y, label)
    c.setFont("Helvetica", size)
    c.drawString(x + label_w, y, valor or "-")


def _render_pdf_gre(guia: GuiaRemision, emisor: Emisor) -> bytes:
    buffer = io.BytesIO()
    w, h = A4
    c = canvas.Canvas(buffer, pagesize=A4)

    ml = 15 * mm
    mr = w - 15 * mm
    content_w = mr - ml
    y = h - 15 * mm

    numero_fmt = f"{guia.serie}-{guia.numero}"

    # =====================================================================
    # CABECERA: logo + emisor | recuadro documento
    # =====================================================================
    header_top = y

    box_w = 70 * mm
    box_h = 30 * mm
    box_x = mr - box_w
    box_y = header_top - box_h

    _rounded_rect(c, box_x, box_y, box_w, box_h, r=3 * mm,
                  stroke_color=COLOR_PRIMARIO, line_width=1.5)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 7 * mm, f"RUC {emisor.ruc}")

    # Título (puede ir en dos líneas)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(COLOR_PRIMARIO)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 13 * mm, "GUÍA DE REMISIÓN")
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 17.5 * mm, "ELECTRÓNICA REMITENTE")

    band_h = 6.5 * mm
    _rounded_rect(c, box_x + 3 * mm, box_y + 2 * mm, box_w - 6 * mm, band_h, r=2 * mm,
                  stroke=0, fill=1, fill_color=COLOR_GRIS_FONDO)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(box_x + box_w / 2, box_y + 4 * mm, numero_fmt)

    # Logo + datos del emisor (izquierda)
    logo_w, logo_h = 38 * mm, 16 * mm
    logo_y = header_top - logo_h
    logo_ok = _draw_logo(c, emisor, ml, logo_y, logo_w, logo_h)

    ey = (logo_y - 4 * mm) if logo_ok else (header_top - 4 * mm)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(black)
    razon = emisor.razon_social or ""
    if len(razon) > 38:
        c.setFont("Helvetica-Bold", 9)
    c.drawString(ml, ey, razon)
    ey -= 5 * mm

    c.setFont("Helvetica", 7.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    if getattr(emisor, "direccion", None):
        c.drawString(ml, ey, emisor.direccion[:75])
        ey -= 3.8 * mm
    contacto = []
    if getattr(emisor, "telefono", None):
        contacto.append(f"Tel: {emisor.telefono}")
    if getattr(emisor, "email", None):
        contacto.append(emisor.email)
    if contacto:
        c.drawString(ml, ey, "  ".join(contacto)[:75])

    # =====================================================================
    # DATOS DEL TRASLADO
    # =====================================================================
    y = box_y - 9 * mm
    sec_h = 30 * mm
    _rounded_rect(c, ml, y - sec_h, content_w, sec_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    c.setFillColor(COLOR_PRIMARIO)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(ml + 4 * mm, y - 5 * mm, "DATOS DEL TRASLADO")

    col1_x = ml + 4 * mm
    col2_x = ml + content_w / 2 + 2 * mm
    ry = y - 11 * mm

    fecha_emi = guia.fecha_emision.strftime("%d/%m/%Y") if guia.fecha_emision else "-"
    fecha_ini = guia.fecha_inicio_traslado.strftime("%d/%m/%Y") if guia.fecha_inicio_traslado else "-"

    motivo_cod = guia.motivo_traslado or ""
    motivo_desc = MOTIVOS_TRASLADO.get(motivo_cod, "")
    if motivo_cod == "13" and getattr(guia, "descripcion_motivo", None):
        motivo_desc = guia.descripcion_motivo
    motivo_txt = f"{motivo_cod} - {motivo_desc}".strip(" -")

    modalidad_cod = guia.modalidad_traslado or ""
    modalidad_txt = f"{modalidad_cod} - {MODALIDADES_TRASLADO.get(modalidad_cod, '')}".strip(" -")

    peso = _safe_float(guia.peso_bruto_total, 0)
    peso_txt = f"{peso:g} {guia.unidad_peso or 'KGM'}"
    bultos_txt = str(guia.numero_bultos) if guia.numero_bultos is not None else "-"

    _label_valor(c, col1_x, ry, "Fecha emisión:", fecha_emi, label_w=30 * mm)
    _label_valor(c, col2_x, ry, "Inicio traslado:", fecha_ini, label_w=30 * mm)
    ry -= 5 * mm
    _label_valor(c, col1_x, ry, "Motivo:", motivo_txt[:55], label_w=30 * mm)
    ry -= 5 * mm
    _label_valor(c, col1_x, ry, "Modalidad:", modalidad_txt, label_w=30 * mm)
    _label_valor(c, col2_x, ry, "Peso bruto:", peso_txt, label_w=30 * mm)
    ry -= 5 * mm
    _label_valor(c, col1_x, ry, "N° de bultos:", bultos_txt, label_w=30 * mm)

    # Leyenda M1L / datos de transporte
    y = y - sec_h - 4 * mm
    if getattr(guia, "indicador_vehiculo_m1l", False):
        _rounded_rect(c, ml, y - 8 * mm, content_w, 8 * mm, r=2 * mm,
                      stroke=0, fill=1, fill_color=COLOR_GRIS_FONDO)
        c.setFillColor(COLOR_GRIS_OSCURO)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(w / 2, y - 5.2 * mm,
                            "Traslado en vehículo categoría M1 o L")
        y -= 12 * mm
    elif modalidad_cod == "02":
        sec_h = 16 * mm
        _rounded_rect(c, ml, y - sec_h, content_w, sec_h, r=2.5 * mm,
                      stroke_color=COLOR_BORDE, line_width=0.75)
        c.setFillColor(COLOR_PRIMARIO)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(ml + 4 * mm, y - 5 * mm, "TRANSPORTE PRIVADO")
        ry = y - 11 * mm
        _label_valor(c, ml + 4 * mm, ry, "Placa:", guia.vehiculo_placa or "-", label_w=20 * mm)
        cond = guia.conductor_nombres or "-"
        tipo_l = TIPOS_DOC_IDENTIDAD.get(str(guia.conductor_tipo_doc or "1"), "DOC.")
        cond_doc = f"{tipo_l} {guia.conductor_num_doc or '-'}"
        _label_valor(c, col2_x, ry, "Conductor:", cond[:30], label_w=22 * mm)
        ry -= 5 * mm
        _label_valor(c, ml + 4 * mm, ry, "Doc.:", cond_doc, label_w=20 * mm)
        _label_valor(c, col2_x, ry, "Licencia:", guia.conductor_licencia or "-", label_w=22 * mm)
        y -= sec_h + 4 * mm
    elif modalidad_cod == "01":
        sec_h = 11 * mm
        _rounded_rect(c, ml, y - sec_h, content_w, sec_h, r=2.5 * mm,
                      stroke_color=COLOR_BORDE, line_width=0.75)
        c.setFillColor(COLOR_PRIMARIO)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(ml + 4 * mm, y - 5 * mm, "TRANSPORTISTA")
        tipo_l = TIPOS_DOC_IDENTIDAD.get(str(guia.transportista_tipo_doc or "6"), "RUC")
        transp = f"{tipo_l} {guia.transportista_num_doc or '-'}  {guia.transportista_razon_social or ''}"
        c.setFont("Helvetica", 8)
        c.setFillColor(black)
        c.drawString(ml + 4 * mm, y - 9 * mm, transp[:90])
        y -= sec_h + 4 * mm

    # =====================================================================
    # DESTINATARIO
    # =====================================================================
    sec_h = 14 * mm
    _rounded_rect(c, ml, y - sec_h, content_w, sec_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)
    c.setFillColor(COLOR_PRIMARIO)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(ml + 4 * mm, y - 5 * mm, "DESTINATARIO")
    tipo_l = TIPOS_DOC_IDENTIDAD.get(str(guia.dest_tipo_doc or "6"), "DOC.")
    _label_valor(c, ml + 4 * mm, y - 10.5 * mm, f"{tipo_l}:",
                 f"{guia.dest_num_doc or '-'}   {guia.dest_razon_social or ''}"[:85],
                 label_w=18 * mm)
    y -= sec_h + 4 * mm

    # =====================================================================
    # PARTIDA Y LLEGADA
    # =====================================================================
    sec_h = 18 * mm
    half = (content_w - 3 * mm) / 2
    for i, (titulo, ubigeo, direccion) in enumerate([
        ("PUNTO DE PARTIDA", guia.partida_ubigeo, guia.partida_direccion),
        ("PUNTO DE LLEGADA", guia.llegada_ubigeo, guia.llegada_direccion),
    ]):
        bx = ml + i * (half + 3 * mm)
        _rounded_rect(c, bx, y - sec_h, half, sec_h, r=2.5 * mm,
                      stroke_color=COLOR_BORDE, line_width=0.75)
        c.setFillColor(COLOR_PRIMARIO)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(bx + 4 * mm, y - 5 * mm, titulo)
        c.setFillColor(black)
        _label_valor(c, bx + 4 * mm, y - 10.5 * mm, "Ubigeo:", ubigeo or "-",
                     label_w=18 * mm, size=8)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawString(bx + 4 * mm, y - 15 * mm, (direccion or "-")[:55])
    y -= sec_h + 5 * mm

    # =====================================================================
    # TABLA DE ITEMS
    # =====================================================================
    table_data = [["#", "Código", "Descripción", "Unidad", "Cantidad"]]
    for it in (guia.items or []):
        cant = _safe_float(it.cantidad, 0)
        table_data.append([
            str(it.orden),
            it.codigo or "-",
            (it.descripcion or "")[:60],
            it.unidad_medida or "NIU",
            f"{cant:g}",
        ])
    if len(table_data) == 1:
        table_data.append(["1", "-", "-", "NIU", "0"])

    col_widths = [10 * mm, 25 * mm, content_w - 10 * mm - 25 * mm - 22 * mm - 25 * mm,
                  22 * mm, 25 * mm]
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_GRIS_OSCURO),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.75, COLOR_BORDE),
        ("LINEBELOW", (0, 0), (-1, 0), 1, COLOR_BORDE),
        ("INNERGRID", (0, 1), (-1, -1), 0.4, COLOR_LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    _, table_h = table.wrap(content_w, y)
    table.drawOn(c, ml, y - table_h)
    y -= table_h + 5 * mm

    # Factura vinculada (si existe)
    comp = getattr(guia, "comprobante", None)
    if comp is not None:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_GRIS_OSCURO)
        c.drawString(ml, y, f"Documento relacionado: {comp.serie}-{comp.numero}")
        y -= 6 * mm

    # =====================================================================
    # PIE: QR + hash + estado + leyenda
    # =====================================================================
    qr_size = 30 * mm
    footer_h = 34 * mm
    if y - footer_h < 15 * mm:
        y = 15 * mm + footer_h  # evita salirse de la página

    footer_text_w = content_w - qr_size - 5 * mm
    _rounded_rect(c, ml, y - footer_h, footer_text_w, footer_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(ml + 4 * mm, y - 6 * mm,
                 "Representación impresa de la Guía de Remisión Electrónica")

    estado = getattr(guia, "estado", "")
    ty = y - 13 * mm
    if estado in ("aceptado", "aceptado_observado"):
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_VERDE)
        etiqueta = "ACEPTADO POR SUNAT" + (" (CON OBSERVACIONES)" if estado == "aceptado_observado" else "")
        c.drawString(ml + 4 * mm, ty, etiqueta)
        ty -= 5 * mm

    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_GRIS_TEXTO)
    hash_cpe = getattr(guia, "hash_cpe", None) or ""
    if hash_cpe:
        c.drawString(ml + 4 * mm, ty, f"DigestValue (hash): {hash_cpe}")
        ty -= 4.5 * mm
    if getattr(guia, "num_ticket", None):
        c.drawString(ml + 4 * mm, ty, f"Ticket SUNAT: {guia.num_ticket}")
        ty -= 4.5 * mm
    c.setFillColor(COLOR_SECUNDARIO)
    c.drawString(ml + 4 * mm, ty, "Verifique su comprobante en https://www.sunat.gob.pe")

    # QR (derecha)
    qr_x = mr - qr_size
    qr_y = y - footer_h + 2 * mm
    qr_text = _qr_text(guia, emisor)
    try:
        qr_img = qrcode.make(qr_text, box_size=3, border=1)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), qr_x, qr_y, qr_size, qr_size)
        c.setStrokeColor(COLOR_BORDE)
        c.setLineWidth(0.5)
        c.rect(qr_x, qr_y, qr_size, qr_size)
    except Exception as e:
        logger.error("[PDF_GRE] Error generando QR: %s", e)
        c.setStrokeColor(COLOR_LINEA)
        c.rect(qr_x, qr_y, qr_size, qr_size)

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generar_pdf_gre(db, guia_id: str) -> bytes:
    """Genera el PDF (A4 + QR) de una GRE. Carga guía + emisor desde la BD.

    Args:
        db: sesión SQLAlchemy.
        guia_id: id de la GuiaRemision.

    Returns:
        bytes del PDF.
    """
    guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
    if not guia:
        raise ValueError(f"Guía {guia_id} no encontrada")
    emisor = db.query(Emisor).filter(Emisor.id == guia.emisor_id).first()
    if not emisor:
        raise ValueError(f"Emisor de la guía {guia_id} no encontrado")
    return _render_pdf_gre(guia, emisor)
