"""
Template PDF para Bodegas - facturalo.pro

Diferencias con el template default:
- Tabla de items con 4 columnas: Cant. | Descripción | P.Unit | Importe
  (en lugar de 5: Cant | Desc | Valor Venta | IGV | Importe)
- Slogan: "El favorito de los bodegueros"
"""
import io
import qrcode
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import black, white
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader

from src.services.pdf_templates.base import (
    TIPOS_DOCUMENTO, TIPOS_DOC_CORTO, TIPOS_DOC_IDENTIDAD,
    COLOR_SECUNDARIO, COLOR_GRIS, COLOR_GRIS_TEXTO, COLOR_GRIS_FONDO,
    COLOR_GRIS_OSCURO, COLOR_LINEA, COLOR_BORDE,
    COLOR_VERDE, COLOR_ROJO, COLOR_HABIL,
    PERU_TZ, FACTURALO_URL,
    _rounded_rect, _safe_float, numero_a_letras,
    _generar_ticket,
)
from src.services.pdf_templates import get_slogan


def generar_pdf_bodega(comprobante, emisor, cliente, items, formato="A4",
                       codigo_matricula=None, estado_colegiado=None,
                       habil_hasta=None, url_consulta=None):
    """
    Genera PDF de comprobante con formato bodega (4 columnas).
    Para TICKET, delega al generador compartido.
    """
    buffer = io.BytesIO()

    if formato == "TICKET":
        return _generar_ticket_bodega(buffer, comprobante, emisor, cliente, items,
                                      codigo_matricula, estado_colegiado, habil_hasta,
                                      es_ticket=True)

    if formato == "A5":
        pagesize = (148 * mm, 210 * mm)
    else:
        pagesize = A4

    w, h = pagesize
    c = canvas.Canvas(buffer, pagesize=pagesize)

    ml = 15 * mm
    mr = w - 15 * mm
    content_w = mr - ml
    y = h - 15 * mm

    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    tipo_corto = TIPOS_DOC_CORTO.get(comprobante.tipo_documento, "COMPROBANTE")
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    hora = comprobante.fecha_emision.strftime("%H:%M") if comprobante.fecha_emision else ""
    es_factura = comprobante.tipo_documento == "01"

    # =============================================
    # HEADER: Logo + Emisor | Recuadro Documento
    # =============================================
    header_top = y

    box_w = 62 * mm
    box_h = 34 * mm
    box_x = mr - box_w
    box_y = header_top - box_h

    _rounded_rect(c, box_x, box_y, box_w, box_h, r=3 * mm,
                  stroke_color=COLOR_BORDE, line_width=1.5)

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 10 * mm, f"RUC      {emisor.ruc}")

    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 18 * mm, tipo_corto)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 23.5 * mm, "ELECTRÓNICA")

    band_h = 7 * mm
    band_y = box_y + 2 * mm
    band_x = box_x + 3 * mm
    band_w = box_w - 6 * mm
    _rounded_rect(c, band_x, band_y, band_w, band_h, r=2 * mm,
                  stroke=0, fill=1, fill_color=COLOR_GRIS_FONDO)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w / 2, band_y + 2 * mm, numero_formato)

    # --- Logo ---
    logo_w = 22 * mm
    logo_h = 22 * mm
    text_start_x = ml
    logo_loaded = False
    logo_y = header_top - logo_h - 1 * mm

    if hasattr(emisor, 'logo') and emisor.logo:
        try:
            logo_buffer = io.BytesIO(emisor.logo)
            c.drawImage(ImageReader(logo_buffer), ml, logo_y, logo_w, logo_h,
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass

    if not logo_loaded and hasattr(emisor, 'logo_url') and emisor.logo_url:
        try:
            import urllib.request
            logo_data = urllib.request.urlopen(emisor.logo_url, timeout=5).read()
            logo_buffer = io.BytesIO(logo_data)
            c.drawImage(ImageReader(logo_buffer), ml, logo_y, logo_w, logo_h,
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass

    if logo_loaded:
        text_start_x = ml + logo_w + 4 * mm

    # --- Datos emisor ---
    ey = header_top - 4 * mm

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(black)
    razon = emisor.razon_social or ""
    if len(razon) > 35:
        c.setFont("Helvetica-Bold", 10)
    c.drawString(text_start_x, ey, razon)
    ey -= 5 * mm

    c.setFont("Helvetica", 7.5)
    c.setFillColor(COLOR_GRIS_TEXTO)

    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawString(text_start_x, ey, emisor.direccion)
        ey -= 3.5 * mm

    ubicacion_parts = []
    if hasattr(emisor, 'distrito') and emisor.distrito:
        ubicacion_parts.append(emisor.distrito)
    if hasattr(emisor, 'provincia') and emisor.provincia:
        ubicacion_parts.append(emisor.provincia)
    if hasattr(emisor, 'departamento') and emisor.departamento:
        ubicacion_parts.append(emisor.departamento)
    if ubicacion_parts:
        c.drawString(text_start_x, ey, " - ".join(ubicacion_parts))
        ey -= 3.5 * mm

    if hasattr(emisor, 'telefono') and emisor.telefono:
        c.drawString(text_start_x, ey, f"Tel: {emisor.telefono}")
        ey -= 3.5 * mm

    if hasattr(emisor, 'email') and emisor.email:
        c.drawString(text_start_x, ey, emisor.email)
        ey -= 3.5 * mm

    if hasattr(emisor, 'web') and emisor.web:
        c.setFillColor(COLOR_SECUNDARIO)
        c.drawString(text_start_x, ey, emisor.web)
        c.setFillColor(COLOR_GRIS_TEXTO)

    # =============================================
    # DATOS DEL CLIENTE
    # =============================================
    y = box_y - 8 * mm

    cliente_box_w = content_w * 0.60
    cliente_box_h = 28 * mm

    _rounded_rect(c, ml, y - cliente_box_h, cliente_box_w, cliente_box_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    cx = ml + 4 * mm
    cy = y - 4.5 * mm
    c.setFillColor(black)

    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")
    direccion_cliente = comprobante.cliente_direccion or (getattr(cliente, 'direccion', '') if cliente else "")

    cliente_distrito = getattr(comprobante, 'cliente_distrito', '') or ''
    cliente_provincia = getattr(comprobante, 'cliente_provincia', '') or ''
    cliente_departamento = getattr(comprobante, 'cliente_departamento', '') or ''

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cx, cy, "CLIENTE:")
    cy -= 4.5 * mm

    val_indent = 28 * mm

    if es_factura:
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "RUC:")
        c.setFont("Helvetica", 7.5)
        c.drawString(cx + val_indent, cy, num_doc)
        cy -= 4.5 * mm

        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "RAZÓN SOCIAL:")
        c.setFont("Helvetica", 7.5)
        nombre_trunc = nombre_cliente[:48] if len(nombre_cliente) > 48 else nombre_cliente
        c.drawString(cx + val_indent, cy, nombre_trunc)
        cy -= 4.5 * mm

        if direccion_cliente:
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(cx, cy, "DIRECCIÓN:")
            c.setFont("Helvetica", 7)
            dir_trunc = direccion_cliente[:55] if len(direccion_cliente) > 55 else direccion_cliente
            c.drawString(cx + val_indent, cy, dir_trunc)
            cy -= 4.5 * mm

    else:
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "NRO DOC:")
        c.setFont("Helvetica", 7.5)
        if codigo_matricula:
            doc_text = f"COD {codigo_matricula}"
        else:
            tipo_doc_label = TIPOS_DOC_IDENTIDAD.get(
                comprobante.cliente_tipo_documento or
                (cliente.tipo_documento if cliente else ""), "DOC.")
            doc_text = f"{tipo_doc_label} [{num_doc}]"
        c.drawString(cx + val_indent, cy, doc_text)
        cy -= 4.5 * mm

        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "DENOMINACIÓN:")
        c.setFont("Helvetica", 7.5)
        nombre_trunc = nombre_cliente[:48] if len(nombre_cliente) > 48 else nombre_cliente
        c.drawString(cx + val_indent, cy, nombre_trunc)
        cy -= 4.5 * mm

        if direccion_cliente:
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(cx, cy, "DIRECCIÓN:")
            c.setFont("Helvetica", 7)
            dir_trunc = direccion_cliente[:55] if len(direccion_cliente) > 55 else direccion_cliente
            c.drawString(cx + val_indent, cy, dir_trunc)
            cy -= 4.5 * mm

    ubic_parts = []
    if cliente_distrito:
        ubic_parts.append(cliente_distrito.strip())
    if cliente_provincia:
        ubic_parts.append(cliente_provincia.strip())
    if cliente_departamento:
        ubic_parts.append(cliente_departamento.strip())
    if ubic_parts:
        c.setFont("Helvetica", 6.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawString(cx + val_indent, cy, " - ".join(ubic_parts))
        c.setFillColor(black)

    # Recuadro fecha/moneda (derecha)
    fecha_box_x = ml + cliente_box_w + 2 * mm
    fecha_box_w = content_w - cliente_box_w - 2 * mm

    _rounded_rect(c, fecha_box_x, y - cliente_box_h, fecha_box_w, cliente_box_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    fx = fecha_box_x + 4 * mm
    fxr = fecha_box_x + fecha_box_w - 4 * mm
    fy = y - 6 * mm
    c.setFillColor(black)

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Fecha Emisión:")
    c.setFont("Helvetica", 8)
    c.drawRightString(fxr, fy, fecha)
    fy -= 5.5 * mm

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Hora Emisión:")
    c.setFont("Helvetica", 8)
    c.drawRightString(fxr, fy, hora)
    fy -= 5.5 * mm

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Moneda:")
    c.setFont("Helvetica", 8)
    moneda_texto = "SOLES" if (comprobante.moneda or "PEN") == "PEN" else comprobante.moneda
    c.drawRightString(fxr, fy, moneda_texto)
    fy -= 5.5 * mm

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Forma Pago:")
    c.setFont("Helvetica", 8)
    forma_pago_texto = getattr(comprobante, 'forma_pago', 'Contado') or 'Contado'
    c.drawRightString(fxr, fy, forma_pago_texto.upper())

    # =============================================
    # TABLA DE ITEMS - BODEGA: 4 COLUMNAS
    # Cant. | Descripción | P.Unit | Importe
    # =============================================
    y = y - cliente_box_h - 5 * mm

    col_cant = 18 * mm
    col_punit = 28 * mm
    col_importe = 28 * mm
    col_desc = content_w - col_cant - col_punit - col_importe
    col_widths = [col_cant, col_desc, col_punit, col_importe]

    style_desc = ParagraphStyle(
        'ItemDesc',
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
    )

    table_data = [["Cant.", "Descripción", "P.Unit", "Importe"]]

    for item in items:
        cantidad_num = _safe_float(item.cantidad, 1)
        cantidad = f"{cantidad_num:.0f}"
        desc = item.descripcion or ""

        # === PRECIO UNITARIO (lo que muestra la columna P.Unit) ===
        precio_unitario = _safe_float(getattr(item, 'precio_unitario', None), 0)
        valor_unitario = _safe_float(getattr(item, 'valor_unitario', None), 0)
        subtotal_linea = _safe_float(item.subtotal, 0)

        if precio_unitario > 0:
            precio_display = precio_unitario
        elif valor_unitario > 0:
            precio_display = valor_unitario
        elif subtotal_linea > 0 and cantidad_num > 0:
            # Fallback: calcular desde subtotal / cantidad
            precio_display = round(subtotal_linea / cantidad_num, 2)
        else:
            precio_display = 0

        # === IMPORTE (cantidad × precio + IGV) ===
        valor_venta = subtotal_linea or _safe_float(item.monto_linea, 0)
        if valor_venta == 0 and precio_display > 0:
            valor_venta = round(cantidad_num * precio_display, 2)

        tipo_afectacion = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')
        igv_calculado = _safe_float(item.igv, 0)
        if igv_calculado == 0 and tipo_afectacion == '10' and valor_venta > 0:
            igv_calculado = round(valor_venta * 0.18, 2)

        importe_total = round(valor_venta + igv_calculado, 2)

        punit_str = f"{precio_display:,.2f}"
        importe_str = f"{importe_total:,.2f}"

        if '\n' in desc:
            lineas = desc.split('\n')
            html_parts = [f'<font size="7.5"><b>{lineas[0]}</b></font>']
            for extra_line in lineas[1:]:
                html_parts.append(f'<br/><font size="6.5" color="#64748b">{extra_line}</font>')
            desc_cell = Paragraph(''.join(html_parts), style_desc)
        else:
            desc_cell = desc

        table_data.append([cantidad, desc_cell, punit_str, importe_str])

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_GRIS_OSCURO),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),     # Cant. centrada
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),       # P.Unit derecha
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),       # Importe derecha
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 0.75, COLOR_BORDE),
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, 0), 0.5, COLOR_GRIS_OSCURO),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))

    table_w, table_h = table.wrap(content_w, y)
    table.drawOn(c, ml, y - table_h)
    y = y - table_h

    n_items = len(items) if items else 1
    if n_items <= 2:
        min_items_area = 25 * mm
    elif n_items <= 5:
        min_items_area = 15 * mm
    else:
        min_items_area = 5 * mm

    items_area_used = table_h - 8 * mm
    if items_area_used < min_items_area:
        y -= (min_items_area - items_area_used)

    # =============================================
    # TOTALES
    # =============================================
    y -= 3 * mm

    totales_label_x = mr - 68 * mm
    totales_valor_x = mr - 3 * mm

    op_gravada = _safe_float(comprobante.op_gravada, 0)
    op_exonerada = _safe_float(comprobante.op_exonerada, 0)
    op_inafecta = _safe_float(comprobante.op_inafecta, 0)
    monto_igv = _safe_float(comprobante.monto_igv, 0)
    total = _safe_float(comprobante.monto_total, 0)

    if op_gravada == 0 and monto_igv > 0:
        op_gravada = round(monto_igv / 0.18, 2)

    subtotal_venta = op_gravada + op_exonerada + op_inafecta

    def draw_total_line(label, valor, y_pos, bold=False, size=8.5):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.setFillColor(black)
        c.drawRightString(totales_label_x + 33 * mm, y_pos, label)
        c.drawString(totales_label_x + 35 * mm, y_pos, "S/")
        c.drawRightString(totales_valor_x, y_pos, f"{valor:,.2f}")
        return y_pos - 5 * mm

    y = draw_total_line("Op. Gravada", op_gravada, y)
    y = draw_total_line("Op. Inafecta", op_inafecta, y)
    y = draw_total_line("Op. Exonerada", op_exonerada, y)
    y = draw_total_line("Sub Total", subtotal_venta, y)

    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.line(totales_label_x, y + 3 * mm, mr, y + 3 * mm)

    y = draw_total_line("IGV 18%", monto_igv, y)
    y = draw_total_line("TOTAL", total, y, bold=True, size=9.5)

    # Estado colegiado (opcional - no aplica a bodegas normalmente)
    if estado_colegiado and codigo_matricula:
        y -= 2 * mm
        if estado_colegiado.upper() == "HÁBIL":
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(COLOR_HABIL)
            estado_text = "Colegiado HÁBIL"
            if habil_hasta:
                estado_text += f" vigente hasta: {habil_hasta}"
            c.drawRightString(mr, y, estado_text)
        else:
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(COLOR_ROJO)
            c.drawRightString(mr, y, "Colegiado INHÁBIL")
        y -= 4 * mm

    # =============================================
    # IMPORTE EN LETRAS
    # =============================================
    y -= 3 * mm
    letras_h = 9 * mm

    _rounded_rect(c, ml, y - letras_h, content_w, letras_h, r=2 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(black)
    c.drawString(ml + 4 * mm, y - 6 * mm, "IMPORTE EN LETRAS:")
    importe_letras = numero_a_letras(total)
    c.setFont("Helvetica", 7.5)
    c.drawString(ml + 40 * mm, y - 6 * mm, importe_letras)

    y -= letras_h

    # =============================================
    # FOOTER: Representación + Estado + Hash + QR
    # =============================================
    y -= 5 * mm

    qr_size = 24 * mm
    footer_text_w = content_w - qr_size - 5 * mm
    footer_h = 28 * mm

    _rounded_rect(c, ml, y - footer_h, footer_text_w, footer_h, r=2 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 4 * mm, y - 5.5 * mm, f"Representación impresa de la {tipo_nombre}")

    next_y = y - 12 * mm
    estado = getattr(comprobante, 'estado', '')
    if estado == "aceptado":
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(COLOR_VERDE)
        c.drawString(ml + 4 * mm, next_y, "ACEPTADO POR SUNAT")
        next_y -= 5 * mm
    elif estado == "rechazado":
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(COLOR_ROJO)
        c.drawString(ml + 4 * mm, next_y, "RECHAZADO POR SUNAT")
        next_y -= 5 * mm

    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawString(ml + 4 * mm, next_y, f"Resumen: {hash_cpe}")

    # --- QR (derecha) ---
    qr_x = mr - qr_size
    qr_y = y - qr_size

    qr_url = f"{FACTURALO_URL}/verificar/{comprobante.id}"

    try:
        qr_img = qrcode.make(qr_url, box_size=3, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        c.drawImage(ImageReader(qr_buffer), qr_x, qr_y, qr_size, qr_size)
        c.setStrokeColor(COLOR_BORDE)
        c.setLineWidth(0.5)
        c.rect(qr_x, qr_y, qr_size, qr_size)
    except Exception:
        c.setStrokeColor(COLOR_LINEA)
        c.rect(qr_x, qr_y, qr_size, qr_size)
        c.setFont("Helvetica", 6)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(qr_x + qr_size / 2, qr_y + qr_size / 2, "QR")

    # =============================================
    # PIE DE PÁGINA + SLOGAN BODEGA
    # =============================================
    y = min(y - footer_h, qr_y) - 3 * mm

    consulta_url = url_consulta or getattr(emisor, 'url_consulta', None)
    if consulta_url:
        c.setFont("Helvetica", 6.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(w / 2, y,
                            f"Consulte el estado de habilitación en {consulta_url}")
        y -= 4 * mm

    if hasattr(emisor, 'cuentas_bancarias') and emisor.cuentas_bancarias:
        c.setFont("Helvetica", 6)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(w / 2, y, f"Cuentas para pagos: {emisor.cuentas_bancarias}")
        y -= 4 * mm

    # Línea separadora + branding
    pie_y = y - 2 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.line(ml + 30 * mm, pie_y + 3 * mm, mr - 30 * mm, pie_y + 3 * mm)

    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_GRIS_OSCURO)
    c.drawCentredString(w / 2, pie_y,
                        f"Facturación electrónica por facturalo.pro  |  {datetime.now(tz=PERU_TZ).strftime('%d/%m/%Y %H:%M')}")

    # Slogan del nicho bodega
    slogan = get_slogan("bodega")
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(w / 2, pie_y - 4 * mm, slogan)

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# =============================================
# TICKET BODEGA (80mm) - Con P.Unit
# Cant | Descripción | P.U | Total
# =============================================

# =============================================
# TICKET BODEGA MEJORADO (80mm)
# Reemplazar en: C:\facturalo\src\services\pdf_templates\bodega.py
# 
# Características:
# - Logo del negocio
# - RUC destacado
# - Datos del cliente (o guiones si vacío)
# - Tabla con Cant | Unid | Precio | Total
# - Catálogo virtual destacado (https://quevendi.pro/{whatsapp})
# - QR + URL de verificación facturalo.pro/verificar
# - Código interno QVDI-{sale_id}
# - Leyenda Amazonía condicional por ubigeo
# - Espaciado "con aire" entre secciones
# =============================================

# =============================================
# TICKET BODEGA v2 MEJORADO (80mm)
# Reemplazar en: C:\facturalo\src\services\pdf_templates\bodega.py
# 
# CAMBIOS v2:
# - Espacio reservado para logo (rectángulo redondeado)
# - Si no hay logo, muestra el nicho/rubro
# - Razón social destacada (más grande que "BOLETA...")
# - Totales inteligentes (solo muestra lo que aplica)
# - Footer con DOS sistemas: QueVendi + Facturalo
# =============================================

# =============================================
# TICKET BODEGA v3 MEJORADO (80mm)
# Reemplazar en: C:\facturalo\src\services\pdf_templates\bodega.py
# 
# CAMBIOS v3:
# - Logo alineado a la IZQUIERDA (no centrado)
# - Iconos profesionales por nicho si no hay logo
# - Razón social al lado del logo
# - Datos del emisor alineados correctamente
# =============================================

# =============================================
# TICKET BODEGA v4 FINAL (80mm)
# Reemplazar función _generar_ticket_bodega en:
# C:\facturalo\src\services\pdf_templates\bodega.py
# 
# ICONOS: Opción A aprobada
# =============================================

def _generar_ticket_bodega(buffer, comprobante, emisor, cliente, items,
                           codigo_matricula=None, estado_colegiado=None,
                           habil_hasta=None, es_ticket=False):
    """Genera PDF en formato ticket (80mm) con diseño final v4 para bodegas."""
    
    ticket_w = 80 * mm
    base_h = 300 * mm
    extra_per_item = 12 * mm
    n_items = len(items) if items else 1
    total_h = base_h + (n_items * extra_per_item)

    c = canvas.Canvas(buffer, pagesize=(ticket_w, total_h))

    ml = 3 * mm
    mr = ticket_w - 3 * mm
    center_x = ticket_w / 2
    y = total_h - 5 * mm

    # === DATOS DEL COMPROBANTE ===
    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_doc = comprobante.tipo_documento
    
    if tipo_doc == "01":
        tipo_nombre = "FACTURA ELECTRÓNICA"
    elif tipo_doc == "03":
        tipo_nombre = "BOLETA DE VENTA ELECTRÓNICA"
    elif tipo_doc == "07":
        tipo_nombre = "NOTA DE CRÉDITO ELECTRÓNICA"
    elif tipo_doc == "08":
        tipo_nombre = "NOTA DE DÉBITO ELECTRÓNICA"
    else:
        tipo_nombre = "COMPROBANTE ELECTRÓNICO"
    
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    hora = comprobante.fecha_emision.strftime("%H:%M") if comprobante.fecha_emision else ""

    # === CONFIG Y DATOS DEL EMISOR ===
    config = getattr(emisor, 'config_json', {}) or {}
    nicho = config.get('nicho', 'comercio')
    es_amazonia = config.get('es_amazonia', False)
    telefono_emisor = getattr(emisor, 'telefono', '') or ''
    email_emisor = getattr(emisor, 'email', '') or ''

    # =============================================
    # SECCIÓN 1: LOGO (izquierda) + DATOS EMISOR (derecha)
    # =============================================
    
    logo_box_w = 18 * mm
    logo_box_h = 18 * mm
    logo_box_x = ml
    logo_box_y = y - logo_box_h
    
    text_start_x = logo_box_x + logo_box_w + 3 * mm
    text_y = y
    
    logo_loaded = False
    
    # Intentar cargar logo binario
    if hasattr(emisor, 'logo') and emisor.logo:
        try:
            logo_buffer = io.BytesIO(emisor.logo)
            c.drawImage(ImageReader(logo_buffer), logo_box_x, logo_box_y,
                        logo_box_w, logo_box_h, 
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass
    
    # Intentar cargar logo desde URL
    if not logo_loaded and hasattr(emisor, 'logo_url') and emisor.logo_url:
        try:
            import urllib.request
            logo_data = urllib.request.urlopen(emisor.logo_url, timeout=5).read()
            logo_buffer = io.BytesIO(logo_data)
            c.drawImage(ImageReader(logo_buffer), logo_box_x, logo_box_y,
                        logo_box_w, logo_box_h,
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass
    
    # Si no hay logo, dibujar icono profesional del nicho
    if not logo_loaded:
        _dibujar_icono_nicho(c, nicho, logo_box_x, logo_box_y, logo_box_w, logo_box_h)

    # =============================================
    # DATOS DEL EMISOR (al lado del logo)
    # =============================================
    
    nombre_mostrar = emisor.nombre_comercial or emisor.razon_social or ""
    
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    
    if len(nombre_mostrar) > 22:
        c.setFont("Helvetica-Bold", 7)
    
    c.drawString(text_start_x, text_y - 4*mm, nombre_mostrar[:28])
    
    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRIS_TEXTO)
    direccion = getattr(emisor, 'direccion', '') or ''
    if direccion:
        c.drawString(text_start_x, text_y - 8*mm, direccion[:32])
    
    contacto_line = ""
    if telefono_emisor:
        contacto_line = f"Teléfono: {telefono_emisor}"
    if email_emisor:
        if contacto_line:
            contacto_line += f"  {email_emisor}"
        else:
            contacto_line = email_emisor
    
    if contacto_line:
        c.setFont("Helvetica", 5)
        c.drawString(text_start_x, text_y - 11.5*mm, contacto_line[:38])
    
    establecimiento = getattr(emisor, 'establecimiento_anexo', '') or ''
    if establecimiento:
        c.setFont("Helvetica", 5)
        c.drawString(text_start_x, text_y - 14.5*mm, f"Sucursales: {establecimiento[:30]}")

    y = logo_box_y - 3 * mm

    # =============================================
    # SECCIÓN 2: RUC (centrado, destacado)
    # =============================================
    
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    c.drawCentredString(center_x, y, f"RUC: {emisor.ruc}")
    y -= 5 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 5 * mm

    # =============================================
    # SECCIÓN 3: TIPO DOCUMENTO
    # =============================================
    
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_GRIS_OSCURO)
    c.drawCentredString(center_x, y, tipo_nombre)
    y -= 4 * mm
    
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(black)
    c.drawCentredString(center_x, y, numero_formato)
    y -= 5 * mm

    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRIS_TEXTO)
    forma_pago = getattr(comprobante, 'forma_pago', 'Contado') or 'Contado'
    c.drawString(ml, y, f"Fecha: {fecha}  Hora: {hora}")
    c.drawRightString(mr, y, f"F. Pago: {forma_pago}")
    y -= 4 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    # =============================================
    # SECCIÓN 4: DATOS DEL CLIENTE
    # =============================================
    
    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")
    direccion_cliente = comprobante.cliente_direccion or (getattr(cliente, 'direccion', '') if cliente else "")
    tipo_doc_cliente = comprobante.cliente_tipo_documento or (cliente.tipo_documento if cliente else "0")

    if not num_doc or num_doc in ["00000000", "0"]:
        num_doc = "-"
    if not nombre_cliente or nombre_cliente.upper() in ["CLIENTE VARIOS", "CLIENTES VARIOS", ""]:
        nombre_cliente = "CLIENTE VARIOS"
    if not direccion_cliente:
        direccion_cliente = "-"

    if tipo_doc_cliente == "6":
        label_doc = "RUC"
    elif tipo_doc_cliente == "1":
        label_doc = "DNI"
    else:
        label_doc = "Doc"

    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(black)
    c.drawString(ml, y, "CLIENTE:")
    y -= 3.5 * mm

    c.setFont("Helvetica", 6)
    c.drawString(ml, y, f"{label_doc}: {num_doc}")
    y -= 3.5 * mm
    c.drawString(ml, y, f"Nombre: {nombre_cliente[:35]}")
    y -= 3.5 * mm
    c.drawString(ml, y, f"Dirección: {direccion_cliente[:35]}")
    y -= 4 * mm

    y -= 2 * mm
    c.setStrokeColor(COLOR_LINEA)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    # =============================================
    # SECCIÓN 5: TABLA DE ITEMS
    # =============================================
    
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(black)
    c.drawString(ml, y, "Producto")
    c.drawString(ml + 38 * mm, y, "Cant")
    c.drawString(ml + 46 * mm, y, "Unid")
    c.drawRightString(mr - 12 * mm, y, "Precio")
    c.drawRightString(mr, y, "Total")
    y -= 2.5 * mm
    
    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.line(ml, y, mr, y)
    y -= 3 * mm

    for item in items:
        cantidad_num = _safe_float(item.cantidad, 1)
        cantidad = f"{cantidad_num:.0f}" if cantidad_num == int(cantidad_num) else f"{cantidad_num:.2f}"
        desc = item.descripcion or ""
        unidad = getattr(item, 'unidad_medida', None) or getattr(item, 'unidad', None) or "NIU"

        precio_unitario = _safe_float(getattr(item, 'precio_unitario', None), 0)
        valor_unitario = _safe_float(getattr(item, 'valor_unitario', None), 0)
        subtotal_linea = _safe_float(item.subtotal, 0)

        if precio_unitario > 0:
            precio_display = precio_unitario
        elif valor_unitario > 0:
            precio_display = valor_unitario
        elif subtotal_linea > 0 and cantidad_num > 0:
            precio_display = round(subtotal_linea / cantidad_num, 2)
        else:
            precio_display = 0

        valor_venta = subtotal_linea or _safe_float(getattr(item, 'monto_linea', 0), 0)
        if valor_venta == 0 and precio_display > 0:
            valor_venta = round(cantidad_num * precio_display, 2)
        
        tipo_afectacion = str(getattr(item, 'tipo_afectacion_igv', '20') or '20')
        igv_item = _safe_float(getattr(item, 'igv', 0), 0)
        if igv_item == 0 and tipo_afectacion == '10' and valor_venta > 0:
            igv_item = round(valor_venta * 0.18, 2)
        
        total_item = round(valor_venta + igv_item, 2)

        c.setFillColor(black)

        desc_limpia = desc.split('\n')[0] if '\n' in desc else desc
        c.setFont("Helvetica-Bold", 5.5)
        c.drawString(ml, y, desc_limpia[:28])
        y -= 3.5 * mm

        c.setFont("Helvetica", 5.5)
        c.drawString(ml + 38 * mm, y, cantidad)
        c.drawString(ml + 46 * mm, y, unidad[:6])
        c.drawRightString(mr - 12 * mm, y, f"{precio_display:.2f}")
        c.drawRightString(mr, y, f"{total_item:.2f}")
        y -= 4 * mm

    y -= 1 * mm
    c.setStrokeColor(COLOR_LINEA)
    c.line(ml, y, mr, y)
    y -= 4 * mm

    # =============================================
    # SECCIÓN 6: TOTALES INTELIGENTES
    # =============================================
    
    total = _safe_float(comprobante.monto_total, 0)
    monto_igv = _safe_float(comprobante.monto_igv, 0)
    op_gravada = _safe_float(comprobante.op_gravada, 0)
    op_exonerada = _safe_float(comprobante.op_exonerada, 0)
    op_inafecta = _safe_float(comprobante.op_inafecta, 0)
    op_gratuita = _safe_float(getattr(comprobante, 'op_gratuita', 0), 0)
    icbper = _safe_float(getattr(comprobante, 'icbper', 0), 0)

    c.setFont("Helvetica", 6)
    c.setFillColor(black)

    if op_gravada > 0:
        c.drawString(ml, y, "Op. Gravada:")
        c.drawRightString(mr, y, f"S/ {op_gravada:.2f}")
        y -= 3.5 * mm

    if op_exonerada > 0:
        c.drawString(ml, y, "Op. Exonerada:")
        c.drawRightString(mr, y, f"S/ {op_exonerada:.2f}")
        y -= 3.5 * mm

    if op_inafecta > 0:
        c.drawString(ml, y, "Op. Inafecta:")
        c.drawRightString(mr, y, f"S/ {op_inafecta:.2f}")
        y -= 3.5 * mm

    if op_gratuita > 0:
        c.drawString(ml, y, "Op. Gratuita:")
        c.drawRightString(mr, y, f"S/ {op_gratuita:.2f}")
        y -= 3.5 * mm

    if monto_igv > 0 or op_gravada > 0:
        c.drawString(ml, y, "IGV 18%:")
        c.drawRightString(mr, y, f"S/ {monto_igv:.2f}")
        y -= 3.5 * mm

    if icbper > 0:
        c.drawString(ml, y, "ICBPER:")
        c.drawRightString(mr, y, f"S/ {icbper:.2f}")
        y -= 3.5 * mm

    y -= 1 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(ml, y, "TOTAL:")
    c.drawRightString(mr, y, f"S/ {total:.2f}")
    y -= 5 * mm

    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    importe_letras = numero_a_letras(total)
    
    if len(importe_letras) > 45:
        c.drawCentredString(center_x, y, f"[son: {importe_letras[:45]}")
        y -= 3 * mm
        c.drawCentredString(center_x, y, f"{importe_letras[45:]}]")
    else:
        c.drawCentredString(center_x, y, f"[son: {importe_letras}]")
    y -= 5 * mm

    # =============================================
    # SECCIÓN 7: CATÁLOGO VIRTUAL (DESTACADO)
    # =============================================
    
    if telefono_emisor:
        box_h = 16 * mm
        box_y = y - box_h
        
        c.setStrokeColor(COLOR_SECUNDARIO)
        c.setLineWidth(1.5)
        c.roundRect(ml + 2*mm, box_y, mr - ml - 4*mm, box_h, 3*mm, stroke=1, fill=0)
        
        c.setFont("Helvetica-Bold", 6)
        c.setFillColor(COLOR_GRIS_OSCURO)
        c.drawCentredString(center_x, y - 3.5 * mm, "HAZ TUS PEDIDOS EN LÍNEA GRATIS")
        
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_SECUNDARIO)
        c.drawCentredString(center_x, y - 8 * mm, f"HTTPS://QUEVENDI.PRO/{telefono_emisor}")
        
        c.setFont("Helvetica", 5.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(center_x, y - 12.5 * mm, "PARA RECOJOS O DELIVERY")
        
        y = box_y - 5 * mm

    # =============================================
    # SECCIÓN 8: QR + VERIFICACIÓN
    # =============================================
    
    qr_size = 18 * mm
    qr_x = ml
    qr_y = y - qr_size
    
    qr_url = f"{FACTURALO_URL}/verificar/{comprobante.id}"
    
    try:
        qr_img = qrcode.make(qr_url, box_size=2, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        c.drawImage(ImageReader(qr_buffer), qr_x, qr_y, qr_size, qr_size)
    except Exception:
        c.setStrokeColor(COLOR_LINEA)
        c.rect(qr_x, qr_y, qr_size, qr_size)
        c.setFont("Helvetica", 5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(qr_x + qr_size/2, qr_y + qr_size/2, "QR")

    text_x = qr_x + qr_size + 3 * mm
    text_y = y - 3 * mm
    
    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawString(text_x, text_y, "Representación impresa de la")
    text_y -= 3 * mm
    c.drawString(text_x, text_y, f"{tipo_nombre}.")
    text_y -= 4 * mm
    c.drawString(text_x, text_y, "Verifique en:")
    text_y -= 3 * mm
    c.setFillColor(COLOR_SECUNDARIO)
    c.drawString(text_x, text_y, "https://facturalo.pro/verificar")
    text_y -= 3 * mm
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawString(text_x, text_y, "o en https://sunat.gob.pe")

    y = qr_y - 4 * mm

    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica", 4.5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawString(ml, y, f"Resumen: {hash_cpe[:45]}")
        y -= 3 * mm

    ref_externa = getattr(comprobante, 'referencia_externa', '') or ''
    if ref_externa and 'QUEVENDI-VENTA-' in ref_externa:
        sale_id = ref_externa.replace('QUEVENDI-VENTA-', '')
        codigo_interno = f"QVDI-{sale_id.zfill(8)}"
        c.setFont("Helvetica", 5)
        c.drawString(ml, y, f"Interno: {codigo_interno}")
        y -= 3 * mm

    # =============================================
    # SECCIÓN 9: LEYENDA AMAZONÍA
    # =============================================
    
    if es_amazonia:
        y -= 3 * mm
        c.setStrokeColor(COLOR_LINEA)
        c.setDash(1, 2)
        c.line(ml, y, mr, y)
        c.setDash()
        y -= 4 * mm
        
        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(black)
        c.drawCentredString(center_x, y, '"BIENES TRANSFERIDOS EN LA AMAZONÍA')
        y -= 3 * mm
        c.drawCentredString(center_x, y, 'PARA SER CONSUMIDOS EN LA MISMA"')
        y -= 4 * mm

    # =============================================
    # SECCIÓN 10: PIE - DOS SISTEMAS
    # =============================================
    
    y -= 3 * mm
    c.setStrokeColor(COLOR_LINEA)
    c.setDash(1, 2)
    c.line(ml + 10 * mm, y, mr - 10 * mm, y)
    c.setDash()
    y -= 5 * mm

    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(center_x, y, "Sistema de Ventas:")
    y -= 3 * mm
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(COLOR_SECUNDARIO)
    c.drawCentredString(center_x, y, "https://quevendi.pro")
    y -= 2.5 * mm
    c.setFont("Helvetica", 4.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(center_x, y, "Usado en todo el Perú")
    y -= 5 * mm

    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(center_x, y, "Sistema de Facturación:")
    y -= 3 * mm
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(COLOR_SECUNDARIO)
    c.drawCentredString(center_x, y, "https://facturalo.pro")
    y -= 2.5 * mm
    c.setFont("Helvetica", 4.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(center_x, y, "Preferido por Contadores y Empresas")
    y -= 5 * mm

    from src.services.pdf_templates import get_slogan
    slogan = get_slogan(nicho)
    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(center_x, y, slogan)

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# =============================================
# FUNCIÓN AUXILIAR: Dibujar icono por nicho
# =============================================

def _dibujar_icono_nicho(c, nicho, box_x, box_y, box_w, box_h):
    """Dibuja un icono profesional según el nicho del negocio."""
    
    # Rectángulo contenedor con esquinas redondeadas
    c.setStrokeColor(COLOR_GRIS_OSCURO)
    c.setLineWidth(1)
    c.roundRect(box_x, box_y, box_w, box_h, 2*mm, stroke=1, fill=0)
    
    # Centro del icono
    cx = box_x + box_w / 2
    cy = box_y + box_h / 2
    
    # Escala para el icono (80% del contenedor)
    scale = min(box_w, box_h) * 0.4
    
    c.setStrokeColor(COLOR_GRIS_OSCURO)
    c.setFillColor(COLOR_GRIS_OSCURO)
    c.setLineWidth(0.6)
    
    if nicho == "bodega":
        # BODEGA: Estante con 3 niveles y productos
        # Estructura del estante
        for i, offset in enumerate([-0.6, 0, 0.6]):
            y_line = cy + offset * scale
            c.line(cx - scale, y_line, cx + scale, y_line)
        # Verticales
        c.line(cx - scale, cy - 0.6*scale, cx - scale, cy + 0.8*scale)
        c.line(cx + scale, cy - 0.6*scale, cx + scale, cy + 0.8*scale)
        # Productos (pequeños rectángulos)
        c.rect(cx - 0.7*scale, cy + 0.65*scale, 0.3*scale, 0.12*scale, stroke=0, fill=1)
        c.rect(cx - 0.2*scale, cy + 0.65*scale, 0.4*scale, 0.12*scale, stroke=0, fill=1)
        c.rect(cx + 0.4*scale, cy + 0.65*scale, 0.3*scale, 0.12*scale, stroke=0, fill=1)
        c.rect(cx - 0.5*scale, cy + 0.05*scale, 0.35*scale, 0.12*scale, stroke=0, fill=1)
        c.rect(cx + 0.2*scale, cy + 0.05*scale, 0.5*scale, 0.12*scale, stroke=0, fill=1)
        
    elif nicho == "minimarket":
        # MINIMARKET: Carrito de compras
        # Cuerpo del carrito
        p = c.beginPath()
        p.moveTo(cx - 0.8*scale, cy + 0.5*scale)
        p.lineTo(cx - 0.5*scale, cy - 0.3*scale)
        p.lineTo(cx + 0.7*scale, cy - 0.3*scale)
        p.lineTo(cx + 0.9*scale, cy + 0.5*scale)
        p.close()
        c.drawPath(p, stroke=1, fill=0)
        # Ruedas
        c.circle(cx - 0.3*scale, cy - 0.55*scale, 0.12*scale, stroke=1, fill=1)
        c.circle(cx + 0.5*scale, cy - 0.55*scale, 0.12*scale, stroke=1, fill=1)
        # Manija
        c.line(cx - 0.8*scale, cy + 0.5*scale, cx - 1.0*scale, cy + 0.8*scale)
        # Productos dentro
        c.rect(cx - 0.3*scale, cy - 0.1*scale, 0.25*scale, 0.35*scale, stroke=0, fill=1)
        c.rect(cx + 0.1*scale, cy - 0.05*scale, 0.2*scale, 0.25*scale, stroke=0, fill=1)
        
    elif nicho == "farmacia":
        # FARMACIA: Cruz médica
        c.setLineWidth(0)
        # Vertical
        c.rect(cx - 0.2*scale, cy - 0.8*scale, 0.4*scale, 1.6*scale, stroke=0, fill=1)
        # Horizontal
        c.rect(cx - 0.8*scale, cy - 0.2*scale, 1.6*scale, 0.4*scale, stroke=0, fill=1)
        
    elif nicho == "ferreteria":
        # FERRETERÍA: Llave inglesa
        c.setLineWidth(0.8)
        # Mango (diagonal)
        c.line(cx - 0.7*scale, cy + 0.7*scale, cx + 0.3*scale, cy - 0.3*scale)
        # Cabeza circular
        c.circle(cx + 0.5*scale, cy - 0.5*scale, 0.35*scale, stroke=1, fill=0)
        c.setFillColor(white)
        c.circle(cx + 0.5*scale, cy - 0.5*scale, 0.15*scale, stroke=0, fill=1)
        c.setFillColor(COLOR_GRIS_OSCURO)
        # Extremo del mango
        c.rect(cx - 0.85*scale, cy + 0.55*scale, 0.25*scale, 0.25*scale, stroke=1, fill=0)
        
    elif nicho == "restaurante":
        # RESTAURANTE: Cloche/Bandeja con tapa
        c.setLineWidth(0.8)
        # Plato base (elipse)
        c.ellipse(cx - 0.9*scale, cy - 0.5*scale, cx + 0.9*scale, cy - 0.2*scale)
        # Tapa (arco)
        p = c.beginPath()
        p.moveTo(cx - 0.75*scale, cy - 0.25*scale)
        p.curveTo(cx - 0.75*scale, cy + 0.6*scale, cx + 0.75*scale, cy + 0.6*scale, cx + 0.75*scale, cy - 0.25*scale)
        c.drawPath(p, stroke=1, fill=0)
        # Agarradera
        c.circle(cx, cy + 0.55*scale, 0.1*scale, stroke=1, fill=1)
        
    elif nicho == "cafeteria":
        # CAFETERÍA: Taza con vapor
        c.setLineWidth(0.8)
        # Cuerpo de la taza
        p = c.beginPath()
        p.moveTo(cx - 0.6*scale, cy + 0.3*scale)
        p.lineTo(cx - 0.5*scale, cy - 0.5*scale)
        p.lineTo(cx + 0.5*scale, cy - 0.5*scale)
        p.lineTo(cx + 0.6*scale, cy + 0.3*scale)
        p.close()
        c.drawPath(p, stroke=1, fill=0)
        # Asa
        p = c.beginPath()
        p.moveTo(cx + 0.6*scale, cy + 0.1*scale)
        p.curveTo(cx + 1.0*scale, cy + 0.1*scale, cx + 1.0*scale, cy - 0.3*scale, cx + 0.6*scale, cy - 0.3*scale)
        c.drawPath(p, stroke=1, fill=0)
        # Vapor (3 líneas onduladas)
        c.setLineWidth(0.5)
        for x_offset in [-0.25, 0, 0.25]:
            p = c.beginPath()
            x = cx + x_offset*scale
            p.moveTo(x, cy + 0.45*scale)
            p.curveTo(x + 0.08*scale, cy + 0.55*scale, x - 0.08*scale, cy + 0.65*scale, x, cy + 0.75*scale)
            c.drawPath(p, stroke=1, fill=0)
        
    elif nicho == "libreria":
        # LIBRERÍA: Libro abierto
        c.setLineWidth(0.8)
        # Lomo central
        c.line(cx, cy - 0.6*scale, cx, cy + 0.5*scale)
        # Página izquierda
        p = c.beginPath()
        p.moveTo(cx, cy + 0.5*scale)
        p.lineTo(cx - 0.8*scale, cy + 0.3*scale)
        p.lineTo(cx - 0.8*scale, cy - 0.5*scale)
        p.lineTo(cx, cy - 0.6*scale)
        c.drawPath(p, stroke=1, fill=0)
        # Página derecha
        p = c.beginPath()
        p.moveTo(cx, cy + 0.5*scale)
        p.lineTo(cx + 0.8*scale, cy + 0.3*scale)
        p.lineTo(cx + 0.8*scale, cy - 0.5*scale)
        p.lineTo(cx, cy - 0.6*scale)
        c.drawPath(p, stroke=1, fill=0)
        # Líneas de texto
        c.setLineWidth(0.3)
        c.line(cx - 0.65*scale, cy + 0.05*scale, cx - 0.2*scale, cy + 0.1*scale)
        c.line(cx - 0.6*scale, cy - 0.15*scale, cx - 0.25*scale, cy - 0.1*scale)
        c.line(cx + 0.2*scale, cy + 0.1*scale, cx + 0.65*scale, cy + 0.05*scale)
        c.line(cx + 0.25*scale, cy - 0.1*scale, cx + 0.6*scale, cy - 0.15*scale)
        
    else:
        # DEFAULT: Tienda con toldo
        c.setLineWidth(0.8)
        # Estructura de la tienda
        c.rect(cx - 0.7*scale, cy - 0.5*scale, 1.4*scale, 0.9*scale, stroke=1, fill=0)
        # Toldo (ondulado)
        p = c.beginPath()
        p.moveTo(cx - 0.85*scale, cy + 0.4*scale)
        p.lineTo(cx - 0.75*scale, cy + 0.7*scale)
        p.lineTo(cx + 0.75*scale, cy + 0.7*scale)
        p.lineTo(cx + 0.85*scale, cy + 0.4*scale)
        c.drawPath(p, stroke=1, fill=0)
        # Ondas del toldo
        wave_y = cy + 0.4*scale
        for i in range(4):
            x1 = cx - 0.85*scale + i * 0.425*scale
            x2 = x1 + 0.425*scale
            p = c.beginPath()
            p.moveTo(x1, wave_y)
            p.curveTo(x1 + 0.1*scale, wave_y + 0.15*scale, x2 - 0.1*scale, wave_y + 0.15*scale, x2, wave_y)
            c.drawPath(p, stroke=1, fill=0)
        # Puerta
        c.rect(cx - 0.2*scale, cy - 0.5*scale, 0.4*scale, 0.5*scale, stroke=1, fill=0)
        c.circle(cx + 0.1*scale, cy - 0.25*scale, 0.05*scale, stroke=1, fill=1)