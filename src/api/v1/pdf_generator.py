"""
Generador de PDF para Comprobantes Electrónicos
Factura, Boleta, NC, ND - Formato SUNAT Perú

src/api/v1/pdf_generator.py  (facturalo.pro)

v5 - Cambios:
- FIX: Valor Venta e IGV por ítem calculados desde cantidad × precio_unitario
- RESUMEN (hash) debajo de ACEPTADO POR SUNAT
- Pie de página reubicado debajo del rectángulo (no se pierde al recortar)
- Distrito, Provincia, Departamento del cliente debajo de dirección
- Distrito, Provincia, Departamento del emisor (condicional)
- Branding facturalo.pro más visible + contador de empresas
- Glosas completas: Gravada, Exonerada, Inafecta, IGV, Total (siempre)
"""
import io
import os
import qrcode
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader


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
    "A": "CED. DIPL.",
}

# Colores
COLOR_PRIMARIO = HexColor("#1e40af")
COLOR_SECUNDARIO = HexColor("#3b82f6")
COLOR_GRIS = HexColor("#64748b")
COLOR_GRIS_TEXTO = HexColor("#64748b")
COLOR_GRIS_FONDO = HexColor("#e5e7eb")
COLOR_GRIS_OSCURO = HexColor("#374151")
COLOR_LINEA = HexColor("#e2e8f0")
COLOR_BORDE = HexColor("#d1d5db")
COLOR_VERDE = HexColor("#16a34a")
COLOR_ROJO = HexColor("#dc2626")
COLOR_HABIL = HexColor("#059669")

PERU_TZ = timezone(timedelta(hours=-5))
FACTURALO_URL = os.getenv("FACTURALO_PUBLIC_URL", "https://facturalo.pro")


# === UTILIDADES ===

def _convertir_grupo(n):
    """Convierte un número de 1 a 999 a texto"""
    unidades = ['', 'UN', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE']
    decenas = ['', 'DIEZ', 'VEINTE', 'TREINTA', 'CUARENTA', 'CINCUENTA',
               'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
    especiales = {
        11: 'ONCE', 12: 'DOCE', 13: 'TRECE', 14: 'CATORCE', 15: 'QUINCE',
        16: 'DIECISEIS', 17: 'DIECISIETE', 18: 'DIECIOCHO', 19: 'DIECINUEVE',
        21: 'VEINTIUN', 22: 'VEINTIDOS', 23: 'VEINTITRES', 24: 'VEINTICUATRO',
        25: 'VEINTICINCO', 26: 'VEINTISEIS', 27: 'VEINTISIETE', 28: 'VEINTIOCHO',
        29: 'VEINTINUEVE'
    }
    centenas = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS',
                'QUINIENTOS', 'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']

    if n == 0:
        return ''
    if n == 100:
        return 'CIEN'
    if n in especiales:
        return especiales[n]

    resultado = ''
    c_val = n // 100
    resto = n % 100

    if c_val > 0:
        resultado = centenas[c_val]
        if resto > 0:
            resultado += ' '

    if resto in especiales:
        resultado += especiales[resto]
    elif resto > 0:
        d = resto // 10
        u = resto % 10
        if d > 0:
            resultado += decenas[d]
            if u > 0:
                resultado += ' Y ' + unidades[u]
        else:
            resultado += unidades[u]

    return resultado


def numero_a_letras(numero):
    """Convierte número a texto. Ej: 168.00 -> 'CIENTO SESENTA Y OCHO CON 00/100 SOLES'"""
    numero = float(numero)
    entero = int(numero)
    decimales = round((numero - entero) * 100)

    if entero == 0:
        texto = 'CERO'
    elif entero < 1000:
        texto = _convertir_grupo(entero)
    elif entero < 1000000:
        miles = entero // 1000
        centenas_r = entero % 1000
        if miles == 1:
            texto = 'MIL'
        else:
            texto = _convertir_grupo(miles) + ' MIL'
        if centenas_r > 0:
            texto += ' ' + _convertir_grupo(centenas_r)
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


def _safe_float(val, default=0.0):
    """Convierte a float de forma segura"""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# =============================================
# GENERADOR PRINCIPAL (A4/A5)
# =============================================

def generar_pdf_comprobante(comprobante, emisor, cliente, items, formato="A4",
                            codigo_matricula=None, estado_colegiado=None,
                            habil_hasta=None, url_consulta=None):
    # === ROUTING POR NICHO (si el emisor tiene template específico) ===
    try:
        from src.services.pdf_templates import get_emisor_nicho, get_template_generator
        _nicho = get_emisor_nicho(emisor)
        print(f"📄 PDF ROUTING: emisor={emisor.ruc}, nicho={_nicho}, formato={formato}")
        if _nicho not in ("default", "ccploreto"):
            _template_fn = get_template_generator(_nicho)
            if _template_fn:
                print(f"📄 → Usando template: {_nicho}")
                return _template_fn(
                    comprobante, emisor, cliente, items, formato,
                    codigo_matricula, estado_colegiado, habil_hasta, url_consulta
                )
            else:
                print(f"📄 → Template '{_nicho}' no encontrado, usando default")
        else:
            print(f"📄 → Usando template default (nicho={_nicho})")
    except Exception as _e:
        print(f"📄 ⚠️ Error en routing de template: {_e}")
        import traceback
        traceback.print_exc()

    buffer = io.BytesIO()

    if formato == "TICKET":
        return _generar_ticket(buffer, comprobante, emisor, cliente, items,
                               codigo_matricula, estado_colegiado, habil_hasta)

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

    # [PUNTO 5] Distrito - Provincia - Departamento del emisor
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
    # [PUNTO 4] Incluye Distrito, Provincia, Departamento
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

    # Obtener ubicación del cliente
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

    # [PUNTO 4] Ubicación del cliente
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
    # TABLA DE ITEMS
    # [PUNTO 1] Valor Venta e IGV calculados
    # =============================================
    y = y - cliente_box_h - 5 * mm

    col_cant = 18 * mm
    col_igv = 22 * mm
    col_importe = 25 * mm
    col_valor = 25 * mm
    col_desc = content_w - col_cant - col_valor - col_igv - col_importe
    col_widths = [col_cant, col_desc, col_valor, col_igv, col_importe]

    style_desc = ParagraphStyle(
        'ItemDesc',
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
    )

    table_data = [["Cant.", "Descripcion", "Valor Venta", "IGV", "Importe"]]

    for item in items:
        cantidad_num = _safe_float(item.cantidad, 1)
        precio_num = _safe_float(getattr(item, 'precio_unitario', None) or
                                 getattr(item, 'valor_unitario', None), 0)
        cantidad = f"{cantidad_num:.0f}"
        desc = item.descripcion or ""

        # [FIX PUNTO 1] Calcular valor venta e IGV
        valor_venta = _safe_float(item.subtotal, 0) or _safe_float(item.monto_linea, 0)
        if valor_venta == 0 and precio_num > 0:
            valor_venta = round(cantidad_num * precio_num, 2)

        tipo_afectacion = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')
        igv_calculado = _safe_float(item.igv, 0)
        if igv_calculado == 0 and tipo_afectacion == '10' and valor_venta > 0:
            igv_calculado = round(valor_venta * 0.18, 2)

        importe_total = round(valor_venta + igv_calculado, 2)

        valor_str = f"{valor_venta:,.2f}"
        igv_str = f"{igv_calculado:,.2f}"
        importe_str = f"{importe_total:,.2f}"

        if '\n' in desc:
            lineas = desc.split('\n')
            html_parts = [f'<font size="7.5"><b>{lineas[0]}</b></font>']
            for extra_line in lineas[1:]:
                html_parts.append(f'<br/><font size="6.5" color="#64748b">{extra_line}</font>')
            desc_cell = Paragraph(''.join(html_parts), style_desc)
        else:
            desc_cell = desc

        table_data.append([cantidad, desc_cell, valor_str, igv_str, importe_str])

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_GRIS_OSCURO),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
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
    # TOTALES [PUNTO 7] Siempre todas las glosas
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

    # Estado colegiado (opcional)
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
    # [PUNTO 2] Hash debajo de ACEPTADO
    # [PUNTO 3] Pie debajo del rectángulo
    # =============================================
    y -= 5 * mm

    qr_size = 24 * mm
    footer_text_w = content_w - qr_size - 5 * mm
    footer_h = 28 * mm

    _rounded_rect(c, ml, y - footer_h, footer_text_w, footer_h, r=2 * mm,
                  stroke_color=COLOR_BORDE, line_width=0.75)

    # Línea 1: Representación impresa
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 4 * mm, y - 5.5 * mm, f"Representación impresa de la {tipo_nombre}")

    # Línea 2: Estado SUNAT
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

    # [PUNTO 2] Línea 3: Resumen (hash) debajo del estado
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
    # [PUNTO 3] PIE debajo del rectángulo
    # [PUNTO 6] Branding facturalo.pro más visible
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

    # [PUNTO 6] Línea separadora + branding
    pie_y = y - 2 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.line(ml + 30 * mm, pie_y + 3 * mm, mr - 30 * mm, pie_y + 3 * mm)

    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_GRIS_OSCURO)
    c.drawCentredString(w / 2, pie_y,
                        f"Facturación electrónica por facturalo.pro  |  {datetime.now(tz=PERU_TZ).strftime('%d/%m/%Y %H:%M')}")

    # Slogan dinámico por nicho del emisor
    try:
        from src.services.pdf_templates import get_emisor_nicho, get_slogan
        _footer_slogan = get_slogan(get_emisor_nicho(emisor))
    except Exception:
        _footer_slogan = "Más de 80 empresas ya usan Facturalo.pro"

    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS_TEXTO)
    c.drawCentredString(w / 2, pie_y - 4 * mm, _footer_slogan)

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# =============================================
# GENERADOR TICKET (80mm)
# =============================================

def _generar_ticket(buffer, comprobante, emisor, cliente, items,
                    codigo_matricula=None, estado_colegiado=None, habil_hasta=None):
    """Genera PDF en formato ticket (80mm)"""
    ticket_w = 80 * mm
    base_h = 200 * mm
    extra_per_item = 15 * mm
    n_items = len(items) if items else 1
    total_h = base_h + (n_items * extra_per_item)

    c = canvas.Canvas(buffer, pagesize=(ticket_w, total_h))

    ml = 3 * mm
    mr = ticket_w - 3 * mm
    y = total_h - 5 * mm

    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    tipo_corto = TIPOS_DOC_CORTO.get(comprobante.tipo_documento, "COMPROBANTE")
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    hora = comprobante.fecha_emision.strftime("%H:%M") if comprobante.fecha_emision else ""
    es_factura = comprobante.tipo_documento == "01"

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(black)
    c.drawCentredString(ticket_w / 2, y, emisor.razon_social or "")
    y -= 4 * mm

    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(ticket_w / 2, y, f"RUC: {emisor.ruc}")
    y -= 3.5 * mm

    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawCentredString(ticket_w / 2, y, emisor.direccion)
        y -= 3.5 * mm

    if hasattr(emisor, 'web') and emisor.web:
        c.drawCentredString(ticket_w / 2, y, emisor.web)
        y -= 3.5 * mm

    y -= 2 * mm
    c.setStrokeColor(COLOR_LINEA)
    c.setLineWidth(0.5)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(black)
    c.drawCentredString(ticket_w / 2, y, tipo_nombre)
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(ticket_w / 2, y, numero_formato)
    y -= 5 * mm

    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRIS)
    c.drawString(ml, y, f"Fecha: {fecha}  Hora: {hora}")
    y -= 3.5 * mm
    forma_pago_texto = getattr(comprobante, 'forma_pago', 'Contado') or 'Contado'
    c.drawString(ml, y, f"Forma de pago: {forma_pago_texto}")
    y -= 4 * mm

    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")

    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(black)
    c.drawString(ml, y, "CLIENTE:")
    y -= 3.5 * mm

    if es_factura:
        c.setFont("Helvetica", 6)
        c.drawString(ml, y, f"RUC: {num_doc}")
        y -= 3.5 * mm
        c.drawString(ml, y, nombre_cliente[:40])
    else:
        c.setFont("Helvetica", 6)
        if codigo_matricula:
            c.drawString(ml, y, f"COD {codigo_matricula}")
        else:
            c.drawString(ml, y, f"DNI: {num_doc}")
        y -= 3.5 * mm
        c.drawString(ml, y, nombre_cliente[:40])

    y -= 5 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 6)
    c.drawString(ml, y, "Cant.")
    c.drawString(ml + 12 * mm, y, "Descripción")
    c.drawRightString(mr, y, "Total")
    y -= 3 * mm
    c.setStrokeColor(COLOR_LINEA)
    c.line(ml, y, mr, y)
    y -= 3.5 * mm

    c.setFont("Helvetica", 5.5)
    for item in items:
        cantidad_num = _safe_float(item.cantidad, 1)
        precio_num = _safe_float(getattr(item, 'precio_unitario', None) or
                                 getattr(item, 'valor_unitario', None), 0)
        cantidad = f"{cantidad_num:.0f}"
        desc = item.descripcion or ""

        valor_venta = _safe_float(item.subtotal, 0) or _safe_float(item.monto_linea, 0)
        if valor_venta == 0 and precio_num > 0:
            valor_venta = round(cantidad_num * precio_num, 2)
        tipo_afectacion = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')
        igv_item = _safe_float(item.igv, 0)
        if igv_item == 0 and tipo_afectacion == '10' and valor_venta > 0:
            igv_item = round(valor_venta * 0.18, 2)
        total_item = round(valor_venta + igv_item, 2)

        c.setFillColor(black)
        c.drawString(ml, y, cantidad)

        if '\n' in desc:
            lineas = desc.split('\n')
            c.setFont("Helvetica-Bold", 5.5)
            c.drawString(ml + 12 * mm, y, lineas[0][:35])
            c.drawRightString(mr, y, f"{total_item:.2f}")
            for extra in lineas[1:]:
                y -= 3 * mm
                c.setFont("Helvetica", 5)
                c.setFillColor(COLOR_GRIS)
                c.drawString(ml + 12 * mm, y, extra[:42])
            c.setFillColor(black)
            c.setFont("Helvetica", 5.5)
        else:
            c.drawString(ml + 12 * mm, y, desc[:35])
            c.drawRightString(mr, y, f"{total_item:.2f}")

        y -= 4 * mm

    c.setStrokeColor(COLOR_LINEA)
    c.line(ml, y, mr, y)
    y -= 4 * mm

    total = _safe_float(comprobante.monto_total, 0)
    monto_igv = _safe_float(comprobante.monto_igv, 0)
    op_exonerada = _safe_float(comprobante.op_exonerada, 0)

    if op_exonerada > 0:
        c.setFont("Helvetica", 6)
        c.drawString(ml, y, "VALOR VENTA:")
        c.drawRightString(mr, y, f"S/ {op_exonerada:.2f}")
        y -= 3.5 * mm

    c.setFont("Helvetica", 6)
    c.drawString(ml, y, "IGV 18%:")
    c.drawRightString(mr, y, f"S/ {monto_igv:.2f}")
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 7)
    c.drawString(ml, y, "TOTAL:")
    c.drawRightString(mr, y, f"S/ {total:.2f}")
    y -= 5 * mm

    if estado_colegiado and codigo_matricula:
        if estado_colegiado.upper() == "HÁBIL":
            c.setFont("Helvetica-Bold", 6)
            c.setFillColor(COLOR_HABIL)
            texto_estado = "Colegiado HÁBIL"
            if habil_hasta:
                texto_estado += f" hasta {habil_hasta}"
            c.drawCentredString(ticket_w / 2, y, texto_estado)
        y -= 4 * mm

    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    importe_letras = numero_a_letras(total)
    if len(importe_letras) > 45:
        c.drawString(ml, y, importe_letras[:45])
        y -= 3 * mm
        c.drawString(ml, y, importe_letras[45:])
    else:
        c.drawString(ml, y, importe_letras)
    y -= 4 * mm

    try:
        qr_url = f"{FACTURALO_URL}/verificar/{comprobante.id}"
        qr_img = qrcode.make(qr_url, box_size=2, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        qr_size = 20 * mm
        c.drawImage(ImageReader(qr_buffer), (ticket_w - qr_size) / 2, y - qr_size,
                    qr_size, qr_size)
        y -= qr_size + 3 * mm
    except Exception:
        y -= 3 * mm

    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(ticket_w / 2, y, f"Representación impresa de la {tipo_nombre}")
    y -= 3 * mm

    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica", 5)
        c.drawCentredString(ticket_w / 2, y, f"Resumen: {hash_cpe}")
        y -= 3 * mm

    c.setFont("Helvetica", 5.5)
    c.drawCentredString(ticket_w / 2, y, "Facturación electrónica por facturalo.pro")

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes