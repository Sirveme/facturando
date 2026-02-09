"""
Generador de PDF para Comprobantes Electrónicos
Factura, Boleta, NC, ND - Formato SUNAT Perú
Compatible con formato CCPL (Colegio de Contadores Públicos de Loreto)
"""
import io
import os
import qrcode
from datetime import datetime
from decimal import Decimal
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader


# === CONFIGURACIÓN ===
TIPOS_DOCUMENTO = {
    "01": "FACTURA ELECTRÓNICA",
    "03": "BOLETA DE VENTA ELECTRÓNICA",
    "07": "NOTA DE CRÉDITO ELECTRÓNICA",
    "08": "NOTA DE DÉBITO ELECTRÓNICA",
}

TIPOS_DOC_IDENTIDAD = {
    "0": "SIN DOC.",
    "1": "DNI",
    "4": "C.EXT.",
    "6": "RUC",
    "7": "PASAPORTE",
}

COLOR_PRIMARIO = HexColor("#1a3a5c")
COLOR_BORDE = HexColor("#333333")
COLOR_HEADER_BG = HexColor("#2d5f8a")
COLOR_GRIS = HexColor("#666666")
COLOR_GRIS_CLARO = HexColor("#f5f5f5")
COLOR_LINEA = HexColor("#cccccc")
COLOR_VERDE = HexColor("#006633")
COLOR_ROJO = HexColor("#cc0000")


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
        if miles == 1:
            texto = 'MIL'
        else:
            texto = _convertir_grupo(miles) + ' MIL'
        if resto > 0:
            texto += ' ' + _convertir_grupo(resto)
    elif entero < 1000000000:
        millones = entero // 1000000
        resto = entero % 1000000
        if millones == 1:
            texto = 'UN MILLON'
        else:
            texto = _convertir_grupo(millones) + ' MILLONES'
        if resto > 0:
            miles = resto // 1000
            centenas_r = resto % 1000
            if miles > 0:
                if miles == 1:
                    texto += ' MIL'
                else:
                    texto += ' ' + _convertir_grupo(miles) + ' MIL'
            if centenas_r > 0:
                texto += ' ' + _convertir_grupo(centenas_r)
    else:
        texto = str(entero)
    
    return f"{texto} CON {decimales:02d}/100 SOLES"


def generar_pdf_comprobante(comprobante, emisor, cliente, items, formato="A4"):
    """
    Genera PDF de comprobante electrónico.
    
    Args:
        comprobante: objeto Comprobante (SQLAlchemy)
        emisor: objeto Emisor
        cliente: objeto Cliente
        items: lista de LineaDetalle
        formato: "A4", "A5" o "TICKET"
    
    Returns:
        bytes del PDF
    """
    buffer = io.BytesIO()
    
    if formato == "TICKET":
        return _generar_ticket(buffer, comprobante, emisor, cliente, items)
    elif formato == "A5":
        pagesize = (148 * mm, 210 * mm)
    else:
        pagesize = A4
    
    w, h = pagesize
    c = canvas.Canvas(buffer, pagesize=pagesize)
    
    # Márgenes
    ml = 15 * mm   # margen izquierdo
    mr = w - 15 * mm  # margen derecho
    content_w = mr - ml
    y = h - 15 * mm  # posición vertical inicial
    
    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    hora = comprobante.fecha_emision.strftime("%H:%M") if comprobante.fecha_emision else ""
    
    # =============================================
    # HEADER: Logo + Emisor | Recuadro Documento
    # =============================================
    header_y = y
    
    # --- Logo del emisor (si existe) ---
    logo_path = None
    if hasattr(emisor, 'logo_path') and emisor.logo_path and os.path.exists(emisor.logo_path):
        logo_path = emisor.logo_path
    
    logo_w = 20 * mm
    text_start_x = ml
    
    if logo_path:
        try:
            c.drawImage(logo_path, ml, y - 22 * mm, logo_w, 20 * mm, preserveAspectRatio=True, mask='auto')
            text_start_x = ml + logo_w + 3 * mm
        except:
            pass
    
    # --- Datos emisor ---
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_PRIMARIO)
    c.drawString(text_start_x, y, emisor.razon_social or "")
    
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_GRIS)
    
    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawString(text_start_x, y, emisor.direccion)
        y -= 4 * mm
    
    # Ciudad / Departamento
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
    
    # --- Recuadro tipo documento (derecha) ---
    box_w = 65 * mm
    box_h = 30 * mm
    box_x = mr - box_w
    box_y = header_y - box_h
    
    # Borde grueso
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(2)
    c.rect(box_x, box_y, box_w, box_h)
    
    # RUC
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 9 * mm, f"RUC      {emisor.ruc}")
    
    # Tipo documento
    c.setFont("Helvetica-Bold", 10)
    tipo_lineas = tipo_nombre.split(" ELECTRÓNICA")
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 16 * mm, tipo_lineas[0])
    if len(tipo_lineas) > 1:
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(box_x + box_w / 2, box_y + box_h - 21 * mm, "ELECTRÓNICA")
    
    # Número
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(box_x + box_w / 2, box_y + 4 * mm, numero_formato)
    
    # =============================================
    # DATOS DEL CLIENTE
    # =============================================
    y = box_y - 8 * mm
    
    # Recuadro cliente (izquierda)
    cliente_box_w = content_w * 0.58
    cliente_box_h = 22 * mm
    
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(0.75)
    c.rect(ml, y - cliente_box_h, cliente_box_w, cliente_box_h)
    
    # Contenido cliente
    cx = ml + 3 * mm
    cy = y - 4 * mm
    
    tipo_doc_texto = TIPOS_DOC_IDENTIDAD.get(
        comprobante.cliente_tipo_documento or (cliente.tipo_documento if cliente else ""),
        "DOC."
    )
    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")
    direccion_cliente = comprobante.cliente_direccion or (getattr(cliente, 'direccion', '') if cliente else "")
    
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(black)
    c.drawString(cx, cy, "CLIENTE:")
    cy -= 4 * mm
    
    c.drawString(cx, cy, f"NRO DOC:")
    c.setFont("Helvetica", 7.5)
    c.drawString(cx + 25 * mm, cy, f"COD {tipo_doc_texto}-{num_doc}")
    cy -= 4 * mm
    
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(cx, cy, "DENOMINACIÓN:")
    c.setFont("Helvetica", 7.5)
    nombre_trunc = nombre_cliente[:45] if len(nombre_cliente) > 45 else nombre_cliente
    c.drawString(cx + 25 * mm, cy, nombre_trunc)
    cy -= 4 * mm
    
    if direccion_cliente:
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(cx, cy, "DIRECCIÓN:")
        c.setFont("Helvetica", 7)
        dir_trunc = direccion_cliente[:50] if len(direccion_cliente) > 50 else direccion_cliente
        c.drawString(cx + 25 * mm, cy, dir_trunc)
    
    # Recuadro fecha/moneda (derecha)
    fecha_box_x = ml + cliente_box_w
    fecha_box_w = content_w - cliente_box_w
    
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(0.75)
    c.rect(fecha_box_x, y - cliente_box_h, fecha_box_w, cliente_box_h)
    
    fx = fecha_box_x + 3 * mm
    fy = y - 5 * mm
    
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Fecha Emisión:")
    c.setFont("Helvetica", 8)
    c.drawString(fx + 25 * mm, fy, fecha)
    fy -= 5 * mm
    
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Hora Emisión:")
    c.setFont("Helvetica", 8)
    c.drawString(fx + 25 * mm, fy, hora)
    fy -= 5 * mm
    
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(fx, fy, "Moneda:")
    c.setFont("Helvetica", 8)
    moneda_texto = "SOLES" if (comprobante.moneda or "PEN") == "PEN" else comprobante.moneda
    c.drawString(fx + 25 * mm, fy, moneda_texto)
    
    # =============================================
    # TABLA DE ITEMS
    # =============================================
    y = y - cliente_box_h - 5 * mm
    
    # Anchos de columna
    col_cant = 18 * mm
    col_igv = 22 * mm
    col_importe = 25 * mm
    col_valor = 25 * mm
    col_desc = content_w - col_cant - col_valor - col_igv - col_importe
    col_widths = [col_cant, col_desc, col_valor, col_igv, col_importe]
    
    # Headers
    table_data = [["Cant.", "Descripcion", "Valor Venta", "IGV", "Importe"]]
    
    for item in items:
        cantidad = f"{float(item.cantidad):.0f}" if item.cantidad else "1"
        
        # Descripción - puede ser multilínea
        desc = item.descripcion or ""
        
        valor = f"{float(item.subtotal or 0):.2f}"
        igv_item = f"{float(item.igv or 0):.2f}"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)
        
        table_data.append([
            cantidad,
            desc,
            valor,
            igv_item,
            f"{total_item:.2f}"
        ])
    
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),    # Cant
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),      # Valor
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),      # IGV
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),      # Importe
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Bordes
        ('BOX', (0, 0), (-1, 0), 1, COLOR_BORDE),
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLOR_BORDE),
        ('BOX', (0, 1), (-1, -1), 0.5, COLOR_LINEA),
        ('INNERGRID', (0, 0), (-1, 0), 0.5, white),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    
    table_w, table_h = table.wrap(content_w, y)
    table.drawOn(c, ml, y - table_h)
    y = y - table_h
    
    # Espacio vacío (simular área de items vacía como en el formato original)
    min_items_area = 60 * mm
    items_area_used = table_h - 8 * mm  # descontar header
    if items_area_used < min_items_area:
        y -= (min_items_area - items_area_used)
    
    # =============================================
    # TOTALES (alineados a la derecha)
    # =============================================
    y -= 3 * mm
    
    totales_label_x = mr - 70 * mm
    totales_valor_x = mr - 3 * mm
    
    op_gravada = float(comprobante.op_gravada or 0)
    op_exonerada = float(comprobante.op_exonerada or 0)
    op_inafecta = float(comprobante.op_inafecta or 0)
    igv = float(comprobante.monto_igv or 0)
    total = float(comprobante.monto_total or 0)
    
    def draw_total_line(label, valor, y_pos, bold=False, size=8.5):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.setFillColor(black)
        c.drawString(totales_label_x, y_pos, label)
        c.drawString(totales_label_x + 42 * mm, y_pos, "S/")
        c.drawRightString(totales_valor_x, y_pos, f"{valor:,.2f}")
        return y_pos - 5 * mm
    
    if op_gravada > 0:
        y = draw_total_line("OP. GRAVADA", op_gravada, y)
    if op_exonerada > 0:
        y = draw_total_line("VALOR VENTA", op_exonerada, y)
    if op_inafecta > 0:
        y = draw_total_line("OP. INAFECTA", op_inafecta, y)
    
    y = draw_total_line("IGV 18%", igv, y)
    y = draw_total_line("TOTAL", total, y, bold=True, size=9)
    
    # =============================================
    # IMPORTE EN LETRAS
    # =============================================
    y -= 3 * mm
    letras_h = 8 * mm
    
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(0.75)
    c.rect(ml, y - letras_h, content_w, letras_h)
    
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(black)
    c.drawString(ml + 3 * mm, y - 5.5 * mm, "IMPORTE EN LETRAS:")
    
    importe_letras = numero_a_letras(total)
    c.setFont("Helvetica", 7.5)
    c.drawString(ml + 38 * mm, y - 5.5 * mm, importe_letras)
    
    y -= letras_h
    
    # =============================================
    # FOOTER: Representación impresa + Hash + QR
    # =============================================
    y -= 5 * mm
    
    # Recuadro de representación impresa
    footer_h = 18 * mm
    qr_size = 22 * mm
    footer_text_w = content_w - qr_size - 5 * mm
    
    c.setStrokeColor(COLOR_BORDE)
    c.setLineWidth(0.75)
    c.rect(ml, y - footer_h, footer_text_w, footer_h)
    
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(black)
    c.drawString(ml + 3 * mm, y - 5 * mm, f"Representación impresa de la {tipo_nombre}")
    
    # Hash/Resumen
    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        c.setFont("Helvetica-Bold", 7)
        c.drawString(ml + 3 * mm, y - 11 * mm, "RESUMEN:")
        c.setFont("Helvetica", 7)
        c.drawString(ml + 22 * mm, y - 11 * mm, hash_cpe)
    
    # Estado SUNAT
    estado = getattr(comprobante, 'estado', '')
    if estado == "aceptado":
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(COLOR_VERDE)
        c.drawString(ml + 3 * mm, y - 15.5 * mm, "✓ ACEPTADO POR SUNAT")
    elif estado == "rechazado":
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(COLOR_ROJO)
        c.drawString(ml + 3 * mm, y - 15.5 * mm, "✗ RECHAZADO POR SUNAT")
    
    # --- QR Code (derecha) ---
    qr_x = mr - qr_size
    qr_y = y - qr_size
    
    qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{igv:.2f}|{total:.2f}|{fecha}|{comprobante.cliente_tipo_documento or ''}|{comprobante.cliente_numero_documento or ''}"
    if hash_cpe:
        qr_data += f"|{hash_cpe}"
    
    try:
        qr_img = qrcode.make(qr_data, box_size=3, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        c.drawImage(ImageReader(qr_buffer), qr_x, qr_y, qr_size, qr_size)
    except Exception as e:
        # Si falla QR, dibujar placeholder
        c.setStrokeColor(COLOR_LINEA)
        c.rect(qr_x, qr_y, qr_size, qr_size)
        c.setFont("Helvetica", 6)
        c.setFillColor(COLOR_GRIS)
        c.drawCentredString(qr_x + qr_size/2, qr_y + qr_size/2, "QR")
    
    # =============================================
    # PIE DE PÁGINA
    # =============================================
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(w / 2, 8 * mm, f"Generado por facturalo.pro | {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _generar_ticket(buffer, comprobante, emisor, cliente, items):
    """Genera PDF formato ticket 80mm"""
    ticket_w = 80 * mm
    # Calcular alto dinámico
    ticket_h = (130 + len(items) * 14) * mm
    
    c = canvas.Canvas(buffer, pagesize=(ticket_w, ticket_h))
    ml = 3 * mm
    mr = ticket_w - 3 * mm
    y = ticket_h - 5 * mm
    
    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    
    # Emisor
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    c.drawCentredString(ticket_w / 2, y, emisor.razon_social or "")
    y -= 4 * mm
    
    c.setFont("Helvetica", 7)
    c.drawCentredString(ticket_w / 2, y, f"RUC: {emisor.ruc}")
    y -= 3.5 * mm
    
    if hasattr(emisor, 'direccion') and emisor.direccion:
        dir_text = emisor.direccion[:40]
        c.drawCentredString(ticket_w / 2, y, dir_text)
        y -= 3.5 * mm
    
    if hasattr(emisor, 'telefono') and emisor.telefono:
        c.drawCentredString(ticket_w / 2, y, f"Tel: {emisor.telefono}")
        y -= 3.5 * mm
    
    # Línea
    c.setStrokeColor(COLOR_GRIS)
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
    y -= 3.5 * mm
    
    # Cliente
    num_doc = comprobante.cliente_numero_documento or ""
    c.drawString(ml, y, f"Doc: {num_doc}")
    y -= 3.5 * mm
    
    nombre = comprobante.cliente_razon_social or ""
    if len(nombre) > 35:
        nombre = nombre[:32] + "..."
    c.drawString(ml, y, f"Cliente: {nombre}")
    y -= 3.5 * mm
    
    direccion = comprobante.cliente_direccion or ""
    if direccion:
        if len(direccion) > 35:
            direccion = direccion[:32] + "..."
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
        desc = (item.descripcion or "")
        cant = f"{float(item.cantidad):.0f}" if item.cantidad else "1"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)
        
        # Si descripción es larga, usar dos líneas
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
    igv = float(comprobante.monto_igv or 0)
    subtotal = total - igv
    
    c.setFont("Helvetica", 7)
    c.drawString(ml, y, "SUBTOTAL:")
    c.drawRightString(mr, y, f"S/ {subtotal:.2f}")
    y -= 3.5 * mm
    
    c.drawString(ml, y, "IGV 18%:")
    c.drawRightString(mr, y, f"S/ {igv:.2f}")
    y -= 4 * mm
    
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ml, y, "TOTAL:")
    c.drawRightString(mr, y, f"S/ {total:.2f}")
    y -= 5 * mm
    
    # Importe en letras
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    importe_letras = numero_a_letras(total)
    # Dividir si es largo
    if len(importe_letras) > 45:
        c.drawString(ml, y, importe_letras[:45])
        y -= 3 * mm
        c.drawString(ml, y, importe_letras[45:])
    else:
        c.drawString(ml, y, importe_letras)
    y -= 4 * mm
    
    # QR
    try:
        qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{igv:.2f}|{total:.2f}"
        qr_img = qrcode.make(qr_data, box_size=2, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        qr_size = 20 * mm
        c.drawImage(ImageReader(qr_buffer), (ticket_w - qr_size) / 2, y - qr_size, qr_size, qr_size)
        y -= qr_size + 3 * mm
    except:
        y -= 3 * mm
    
    # Footer
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(ticket_w / 2, y, "Representación impresa del CE")
    y -= 3 * mm
    c.drawCentredString(ticket_w / 2, y, "facturalo.pro")
    
    # Hash
    hash_cpe = getattr(comprobante, 'hash_cpe', None) or ""
    if hash_cpe:
        y -= 3 * mm
        c.setFont("Helvetica", 5)
        c.drawCentredString(ticket_w / 2, y, f"Hash: {hash_cpe}")
    
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes