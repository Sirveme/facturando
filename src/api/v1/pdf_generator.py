"""
Generador de PDF para Comprobantes Electrónicos
Factura, Boleta, NC, ND, Recibo
Formato compatible con CCPL (Colegio de Contadores Públicos de Loreto)
"""
import io
import os
import qrcode
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader

PERU_TZ = timezone(timedelta(hours=-5))

# === CONFIGURACIÓN ===
TIPOS_DOCUMENTO = {
    "01": "FACTURA ELECTRÓNICA",
    "03": "BOLETA DE VENTA ELECTRÓNICA",
    "07": "NOTA DE CRÉDITO ELECTRÓNICA",
    "08": "NOTA DE DÉBITO ELECTRÓNICA",
}

TIPOS_DOC_CORTO = {
    "01": "FACTURA",
    "03": "BOLETA",
    "07": "NOTA DE CRÉDITO",
    "08": "NOTA DE DÉBITO",
}

TIPOS_DOC_IDENTIDAD = {
    "0": "SIN DOC.",
    "1": "DNI",
    "4": "C.EXT.",
    "6": "RUC",
    "7": "PASAPORTE",
}

# Colores
COLOR_BORDE = HexColor("#444444")
COLOR_GRIS_OSCURO = HexColor("#4a4a4a")       # Header tabla + banda número
COLOR_GRIS_FONDO = HexColor("#d9d9d9")         # Fondo banda número
COLOR_GRIS_TEXTO = HexColor("#666666")
COLOR_LINEA = HexColor("#cccccc")
COLOR_VERDE = HexColor("#006633")
COLOR_ROJO = HexColor("#cc0000")

FACTURALO_URL = "https://facturalo.pro"


# =============================================
# UTILIDADES
# =============================================

def numero_a_letras(numero):
    """Convierte número a texto en español (soles peruanos)"""
    unidades = ['', 'UNO', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE']
    decenas = ['', 'DIEZ', 'VEINTE', 'TREINTA', 'CUARENTA', 'CINCUENTA',
               'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
    especiales = {
        11: 'ONCE', 12: 'DOCE', 13: 'TRECE', 14: 'CATORCE', 15: 'QUINCE',
        16: 'DIECISEIS', 17: 'DIECISIETE', 18: 'DIECIOCHO', 19: 'DIECINUEVE',
        21: 'VEINTIUNO', 22: 'VEINTIDOS', 23: 'VEINTITRES', 24: 'VEINTICUATRO',
        25: 'VEINTICINCO', 26: 'VEINTISEIS', 27: 'VEINTISIETE', 28: 'VEINTIOCHO',
        29: 'VEINTINUEVE'
    }
    centenas = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS',
                'QUINIENTOS', 'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']

    def _convertir_grupo(n):
        if n == 0:
            return ''
        if n == 100:
            return 'CIEN'
        resultado = ''
        if n >= 100:
            resultado += centenas[n // 100] + ' '
            n = n % 100
        if n in especiales:
            resultado += especiales[n]
        elif n >= 10:
            resultado += decenas[n // 10]
            resto = n % 10
            if resto > 0:
                resultado += ' Y ' + unidades[resto]
        elif n > 0:
            resultado += unidades[n]
        return resultado.strip()

    try:
        numero = float(numero)
    except (TypeError, ValueError):
        return "CERO CON 00/100 SOLES"

    entero = int(numero)
    decimales = int(round((numero - entero) * 100))

    if entero == 0:
        texto = 'CERO'
    elif entero == 1:
        texto = 'UNO'
    elif entero < 1000:
        texto = _convertir_grupo(entero)
    elif entero < 1000000:
        miles = entero // 1000
        resto = entero % 1000
        texto = 'MIL' if miles == 1 else _convertir_grupo(miles) + ' MIL'
        if resto > 0:
            texto += ' ' + _convertir_grupo(resto)
    elif entero < 1000000000:
        millones = entero // 1000000
        resto = entero % 1000000
        texto = 'UN MILLON' if millones == 1 else _convertir_grupo(millones) + ' MILLONES'
        if resto > 0:
            miles = resto // 1000
            centenas_r = resto % 1000
            if miles > 0:
                texto += ' MIL' if miles == 1 else ' ' + _convertir_grupo(miles) + ' MIL'
            if centenas_r > 0:
                texto += ' ' + _convertir_grupo(centenas_r)
    else:
        texto = str(entero)

    return f"{texto} CON {decimales:02d}/100 SOLES"


def _rounded_rect(c, x, y, w, h, r=3*mm, stroke=1, fill=0,
                  stroke_color=None, fill_color=None, line_width=None):
    """Dibuja rectángulo con esquinas redondeadas"""
    if stroke_color:
        c.setStrokeColor(stroke_color)
    if fill_color:
        c.setFillColor(fill_color)
    if line_width is not None:
        c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, r, stroke=stroke, fill=fill)


# =============================================
# GENERADOR PRINCIPAL (A4/A5)
# =============================================

def generar_pdf_comprobante(comprobante, emisor, cliente, items, formato="A4",
                            codigo_matricula=None):
    """
    Genera PDF de comprobante electrónico.

    Args:
        comprobante: objeto Comprobante (SQLAlchemy)
        emisor: objeto Emisor
        cliente: objeto Cliente
        items: lista de LineaDetalle
        formato: "A4", "A5" o "TICKET"
        codigo_matricula: código de matrícula del colegiado (opcional)

    Returns:
        bytes del PDF
    """
    buffer = io.BytesIO()

    if formato == "TICKET":
        return _generar_ticket(buffer, comprobante, emisor, cliente, items, codigo_matricula)

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
    header_y = y

    # --- Logo del emisor ---
    logo_w = 22 * mm
    text_start_x = ml

    # Intentar logo desde bytes (campo logo) o desde URL (campo logo_url)
    logo_loaded = False
    
    # Opción 1: bytes en DB
    if hasattr(emisor, 'logo') and emisor.logo:
        try:
            logo_buffer = io.BytesIO(emisor.logo)
            c.drawImage(ImageReader(logo_buffer), ml, y - 24 * mm, logo_w, 22 * mm,
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass

    # Opción 2: URL (logo_url)
    if not logo_loaded and hasattr(emisor, 'logo_url') and emisor.logo_url:
        try:
            import urllib.request
            logo_data = urllib.request.urlopen(emisor.logo_url, timeout=5).read()
            logo_buffer = io.BytesIO(logo_data)
            c.drawImage(ImageReader(logo_buffer), ml, y - 24 * mm, logo_w, 22 * mm,
                        preserveAspectRatio=True, mask='auto')
            logo_loaded = True
        except Exception:
            pass

    if logo_loaded:
        text_start_x = ml + logo_w + 4 * mm

   

    # --- Datos emisor ---
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(black)
    razon = emisor.razon_social or ""
    if len(razon) > 35:
        c.setFont("Helvetica-Bold", 10)
    c.drawString(text_start_x, y, razon)

    y -= 5.5 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_GRIS_TEXTO)

    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawString(text_start_x, y, emisor.direccion)
        y -= 4 * mm

    ubicacion_parts = []
    if hasattr(emisor, 'provincia') and emisor.provincia:
        ubicacion_parts.append(emisor.provincia)
    if hasattr(emisor, 'departamento') and emisor.departamento:
        ubicacion_parts.append(emisor.departamento)
    if ubicacion_parts:
        c.drawString(text_start_x, y, " - ".join(ubicacion_parts))
        y -= 4 * mm

    if hasattr(emisor, 'telefono') and emisor.telefono:
        c.drawString(text_start_x, y, f"Tel: {emisor.telefono}")
        y -= 4 * mm

    if hasattr(emisor, 'email') and emisor.email:
        c.drawString(text_start_x, y, emisor.email)

    # --- Recuadro tipo documento (derecha) - esquinas redondeadas ---
    box_w = 62 * mm
    box_h = 34 * mm
    box_x = mr - box_w
    box_y = header_y - box_h

    _rounded_rect(c, box_x, box_y, box_w, box_h, r=3 * mm,
                  stroke_color=COLOR_BORDE, line_width=1.5)

    # RUC
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 10 * mm, f"RUC      {emisor.ruc}")

    # Tipo (BOLETA / ELECTRÓNICA)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 18 * mm, tipo_corto)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 23.5 * mm, "ELECTRÓNICA")

    # Banda gris para el número
    band_h = 7 * mm
    band_y = box_y + 2 * mm
    band_x = box_x + 3 * mm
    band_w = box_w - 6 * mm
    _rounded_rect(c, band_x, band_y, band_w, band_h, r=2 * mm,
                  stroke=0, fill=1, fill_color=COLOR_GRIS_FONDO)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w / 2, band_y + 2 * mm, numero_formato)

    # =============================================
    # DATOS DEL CLIENTE
    # =============================================
    y = box_y - 8 * mm

    cliente_box_w = content_w * 0.60
    cliente_box_h = 24 * mm

    # Recuadro cliente - esquinas redondeadas
    _rounded_rect(c, ml, y - cliente_box_h, cliente_box_w, cliente_box_h, r=2.5 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    cx = ml + 4 * mm
    cy = y - 4.5 * mm
    c.setFillColor(black)

    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")
    direccion_cliente = comprobante.cliente_direccion or (getattr(cliente, 'direccion', '') if cliente else "")

    # CLIENTE:
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cx, cy, "CLIENTE:")
    cy -= 4.5 * mm

    # Indentación común para todos los valores
    val_indent = 28 * mm

    # NRO DOC: DNI [xxxxx] Matrícula [xx-xxxxx]
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cx, cy, "NRO DOC:")
    c.setFont("Helvetica", 7.5)
    if codigo_matricula:
        doc_text = f"DNI [{num_doc}]  Matrícula [{codigo_matricula}]"
    else:
        tipo_doc_label = TIPOS_DOC_IDENTIDAD.get(
            comprobante.cliente_tipo_documento or (cliente.tipo_documento if cliente else ""), "DOC.")
        doc_text = f"{tipo_doc_label} {num_doc}"
    c.drawString(cx + val_indent, cy, doc_text)
    cy -= 4.5 * mm

    # DENOMINACIÓN / RAZÓN SOCIAL según tipo
    if es_factura:
        label_nombre = "RAZÓN SOCIAL:"
    else:
        label_nombre = "DENOMINACIÓN:"
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cx, cy, label_nombre)
    c.setFont("Helvetica", 7.5)
    nombre_trunc = nombre_cliente[:48] if len(nombre_cliente) > 48 else nombre_cliente
    c.drawString(cx + val_indent, cy, nombre_trunc)
    cy -= 4.5 * mm

    # DIRECCIÓN (siempre, incluso en boleta)
    if direccion_cliente:
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "DIRECCIÓN:")
        c.setFont("Helvetica", 7)
        dir_trunc = direccion_cliente[:55] if len(direccion_cliente) > 55 else direccion_cliente
        c.drawString(cx + val_indent, cy, dir_trunc)

    # Recuadro fecha/moneda - esquinas redondeadas
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

    # =============================================
    # TABLA DE ITEMS (header con fondo gris oscuro)
    # =============================================
    y = y - cliente_box_h - 5 * mm

    col_cant = 18 * mm
    col_igv = 22 * mm
    col_importe = 25 * mm
    col_valor = 25 * mm
    col_desc = content_w - col_cant - col_valor - col_igv - col_importe
    col_widths = [col_cant, col_desc, col_valor, col_igv, col_importe]

    table_data = [["Cant.", "Descripcion", "Valor Venta", "IGV", "Importe"]]

    for item in items:
        cantidad = f"{float(item.cantidad):.0f}" if item.cantidad else "1"
        desc = item.descripcion or ""
        valor = f"{float(item.subtotal or 0):.2f}"
        igv_item = f"{float(item.igv or 0):.2f}"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)
        table_data.append([cantidad, desc, valor, igv_item, f"{total_item:.2f}"])

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header con fondo gris oscuro
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_GRIS_OSCURO),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),

        # Bordes
        ('BOX', (0, 0), (-1, -1), 0.75, COLOR_BORDE),
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, 0), 0.5, COLOR_GRIS_OSCURO),

        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))

    table_w, table_h = table.wrap(content_w, y)
    table.drawOn(c, ml, y - table_h)
    y = y - table_h

    # Espacio mínimo para área de items
    min_items_area = 50 * mm
    items_area_used = table_h - 8 * mm
    if items_area_used < min_items_area:
        y -= (min_items_area - items_area_used)

    # =============================================
    # TOTALES
    # =============================================
    y -= 3 * mm

    totales_label_x = mr - 68 * mm
    totales_valor_x = mr - 3 * mm

    op_gravada = float(comprobante.op_gravada or 0)
    op_exonerada = float(comprobante.op_exonerada or 0)
    op_inafecta = float(comprobante.op_inafecta or 0)
    monto_igv = float(comprobante.monto_igv or 0)
    total = float(comprobante.monto_total or 0)

    def draw_total_line(label, valor, y_pos, bold=False, size=8.5):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.setFillColor(black)
        c.drawRightString(totales_label_x + 33 * mm, y_pos, label)
        c.drawString(totales_label_x + 35 * mm, y_pos, "S/")
        c.drawRightString(totales_valor_x, y_pos, f"{valor:,.2f}")
        return y_pos - 5 * mm

    if op_gravada > 0:
        y = draw_total_line("OP. GRAVADA", op_gravada, y)
    if op_exonerada > 0:
        y = draw_total_line("VALOR VENTA", op_exonerada, y)
    if op_inafecta > 0:
        y = draw_total_line("OP. INAFECTA", op_inafecta, y)

    y = draw_total_line("IGV 18%", monto_igv, y)
    y = draw_total_line("TOTAL", total, y, bold=True, size=9.5)

    # =============================================
    # IMPORTE EN LETRAS - esquinas redondeadas
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
    # FOOTER: Representación + RESUMEN + QR
    # =============================================
    y -= 5 * mm

    qr_size = 24 * mm
    footer_text_w = content_w - qr_size - 5 * mm
    footer_h = 20 * mm

    # Recuadro texto - esquinas redondeadas
    _rounded_rect(c, ml, y - footer_h, footer_text_w, footer_h, r=2 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 4 * mm, y - 5.5 * mm, f"Representación impresa de la {tipo_nombre}")

    # RESUMEN (hash del XML firmado - sirve para verificación ante SUNAT)
    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica-Bold", 7)
        c.drawString(ml + 4 * mm, y - 11.5 * mm, "RESUMEN:")
        c.setFont("Helvetica", 7)
        c.drawString(ml + 23 * mm, y - 11.5 * mm, hash_cpe)

    # Estado SUNAT
    estado = getattr(comprobante, 'estado', '')
    estado_y = y - 16.5 * mm if hash_cpe else y - 11.5 * mm
    if estado == "aceptado":
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(COLOR_VERDE)
        c.drawString(ml + 4 * mm, estado_y, "ACEPTADO POR SUNAT")
    elif estado == "rechazado":
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(COLOR_ROJO)
        c.drawString(ml + 4 * mm, estado_y, "RECHAZADO POR SUNAT")

    # --- QR (derecha, borde cuadrado) ---
    qr_x = mr - qr_size
    qr_y = y - qr_size

    # QR redirige a facturalo.pro/verificar/{id}
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

    # --- Pie de página ---
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(w / 2, 8 * mm,
                        f"Generado por facturalo.pro | {datetime.now(tz=PERU_TZ).strftime('%d/%m/%Y %H:%M')}")

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# =============================================
# FORMATO TICKET (80mm)
# =============================================

def _generar_ticket(buffer, comprobante, emisor, cliente, items, codigo_matricula=None):
    """Genera PDF formato ticket 80mm"""
    ticket_w = 80 * mm
    ticket_h = (140 + len(items) * 14) * mm

    c = canvas.Canvas(buffer, pagesize=(ticket_w, ticket_h))
    ml = 3 * mm
    mr = ticket_w - 3 * mm
    y = ticket_h - 5 * mm

    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    es_factura = comprobante.tipo_documento == "01"

    # Logo en ticket
    if hasattr(emisor, 'logo') and emisor.logo:
        try:
            logo_buffer = io.BytesIO(emisor.logo)
            logo_s = 15 * mm
            c.drawImage(ImageReader(logo_buffer),
                        (ticket_w - logo_s) / 2, y - logo_s,
                        logo_s, logo_s,
                        preserveAspectRatio=True, mask='auto')
            y -= logo_s + 2 * mm
        except Exception:
            pass
    elif hasattr(emisor, 'logo_url') and emisor.logo_url:
        try:
            import urllib.request
            logo_data = urllib.request.urlopen(emisor.logo_url, timeout=5).read()
            logo_buffer = io.BytesIO(logo_data)
            logo_s = 15 * mm
            c.drawImage(ImageReader(logo_buffer),
                        (ticket_w - logo_s) / 2, y - logo_s,
                        logo_s, logo_s,
                        preserveAspectRatio=True, mask='auto')
            y -= logo_s + 2 * mm
        except Exception:
            pass

    # --- Emisor ---
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    c.drawCentredString(ticket_w / 2, y, emisor.razon_social or "")
    y -= 4 * mm

    c.setFont("Helvetica", 7)
    c.drawCentredString(ticket_w / 2, y, f"RUC: {emisor.ruc}")
    y -= 3.5 * mm

    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawCentredString(ticket_w / 2, y, emisor.direccion[:40])
        y -= 3.5 * mm

    if hasattr(emisor, 'telefono') and emisor.telefono:
        c.drawCentredString(ticket_w / 2, y, f"Tel: {emisor.telefono}")
        y -= 3.5 * mm

    # Línea
    c.setStrokeColor(COLOR_GRIS_TEXTO)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    # Tipo y número
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(ticket_w / 2, y, tipo_nombre)
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(ticket_w / 2, y, numero_formato)
    y -= 5 * mm

    # Fecha y hora
    c.setFont("Helvetica", 7)
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    hora = comprobante.fecha_emision.strftime("%H:%M") if comprobante.fecha_emision else ""
    c.drawString(ml, y, f"Fecha: {fecha}  Hora: {hora}")
    y -= 4 * mm

    # Cliente
    num_doc = comprobante.cliente_numero_documento or ""
    nombre = comprobante.cliente_razon_social or ""
    direccion = comprobante.cliente_direccion or ""

    if codigo_matricula:
        c.drawString(ml, y, f"DNI [{num_doc}] Matrícula [{codigo_matricula}]")
    else:
        c.drawString(ml, y, f"Doc: {num_doc}")
    y -= 3.5 * mm

    label = "R.Social:" if es_factura else "Cliente:"
    if len(nombre) > 30:
        nombre = nombre[:27] + "..."
    c.drawString(ml, y, f"{label} {nombre}")
    y -= 3.5 * mm

    if direccion:
        if len(direccion) > 33:
            direccion = direccion[:30] + "..."
        c.drawString(ml, y, f"Dir: {direccion}")
        y -= 3.5 * mm

    # Línea
    y -= 1 * mm
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    # Items header
    c.setFont("Helvetica-Bold", 7)
    c.drawString(ml, y, "CANT")
    c.drawString(ml + 12 * mm, y, "DESCRIPCIÓN")
    c.drawRightString(mr, y, "TOTAL")
    y -= 1 * mm
    c.line(ml, y, mr, y)
    y -= 3 * mm

    # Items
    c.setFont("Helvetica", 7)
    for item in items:
        desc = item.descripcion or ""
        cant = f"{float(item.cantidad):.0f}" if item.cantidad else "1"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)

        if len(desc) > 28:
            c.drawString(ml, y, cant)
            c.drawString(ml + 12 * mm, y, desc[:28])
            c.drawRightString(mr, y, f"{total_item:.2f}")
            y -= 3.5 * mm
            c.drawString(ml + 12 * mm, y, desc[28:56])
        else:
            c.drawString(ml, y, cant)
            c.drawString(ml + 12 * mm, y, desc)
            c.drawRightString(mr, y, f"{total_item:.2f}")
        y -= 3.5 * mm

    # Totales
    y -= 2 * mm
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    total = float(comprobante.monto_total or 0)
    monto_igv = float(comprobante.monto_igv or 0)
    subtotal = total - monto_igv

    c.setFont("Helvetica", 7)
    c.drawString(ml, y, "SUBTOTAL:")
    c.drawRightString(mr, y, f"S/ {subtotal:.2f}")
    y -= 3.5 * mm

    c.drawString(ml, y, "IGV 18%:")
    c.drawRightString(mr, y, f"S/ {monto_igv:.2f}")
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(ml, y, "TOTAL:")
    c.drawRightString(mr, y, f"S/ {total:.2f}")
    y -= 5 * mm

    # Importe en letras
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    importe_letras = numero_a_letras(total)
    if len(importe_letras) > 45:
        c.drawString(ml, y, importe_letras[:45])
        y -= 3 * mm
        c.drawString(ml, y, importe_letras[45:])
    else:
        c.drawString(ml, y, importe_letras)
    y -= 5 * mm

    # QR
    try:
        qr_url = f"{FACTURALO_URL}/verificar/{comprobante.id}"
        qr_img = qrcode.make(qr_url, box_size=2, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        qr_s = 20 * mm
        c.drawImage(ImageReader(qr_buffer), (ticket_w - qr_s) / 2, y - qr_s, qr_s, qr_s)
        y -= qr_s + 3 * mm
    except Exception:
        y -= 3 * mm

    # Hash
    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica", 5)
        c.setFillColor(COLOR_GRIS_TEXTO)
        c.drawCentredString(ticket_w / 2, y, f"Hash: {hash_cpe}")
        y -= 3.5 * mm

    # Footer
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(ticket_w / 2, y, "Representación impresa del CE")
    y -= 3 * mm
    c.drawCentredString(ticket_w / 2, y, "facturalo.pro")
    y -= 3 * mm
    c.drawCentredString(ticket_w / 2, y,
                        datetime.now(tz=PERU_TZ).strftime('%d/%m/%Y %H:%M'))

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes