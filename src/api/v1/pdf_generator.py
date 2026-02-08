"""
Generador de PDF para Comprobantes Electrónicos
Factura, Boleta, NC, ND - Formato SUNAT Perú
"""
import io
import qrcode
from datetime import datetime
from decimal import Decimal
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import Table, TableStyle


# === CONFIGURACIÓN ===
TIPOS_DOCUMENTO = {
    "01": "FACTURA ELECTRÓNICA",
    "03": "BOLETA DE VENTA ELECTRÓNICA",
    "07": "NOTA DE CRÉDITO ELECTRÓNICA",
    "08": "NOTA DE DÉBITO ELECTRÓNICA",
}

COLOR_PRIMARIO = HexColor("#1e40af")
COLOR_SECUNDARIO = HexColor("#3b82f6")
COLOR_GRIS = HexColor("#64748b")
COLOR_LINEA = HexColor("#e2e8f0")
COLOR_FONDO_HEADER = HexColor("#f1f5f9")


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
    ml = 20 * mm  # margen izquierdo
    mr = w - 20 * mm  # margen derecho
    y = h - 15 * mm  # posición vertical inicial
    
    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    
    # =============================================
    # HEADER: Datos del Emisor + Recuadro Documento
    # =============================================
    
    # --- Lado izquierdo: Emisor ---
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(COLOR_PRIMARIO)
    c.drawString(ml, y, emisor.razon_social or "")
    
    y -= 6 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_GRIS)
    
    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawString(ml, y, emisor.direccion)
        y -= 4 * mm
    
    if hasattr(emisor, 'ubigeo_desc') and emisor.ubigeo_desc:
        c.drawString(ml, y, emisor.ubigeo_desc)
        y -= 4 * mm
    
    if hasattr(emisor, 'telefono') and emisor.telefono:
        c.drawString(ml, y, f"Tel: {emisor.telefono}")
        y -= 4 * mm
    
    if hasattr(emisor, 'email') and emisor.email:
        c.drawString(ml, y, emisor.email)
    
    # --- Lado derecho: Recuadro tipo documento ---
    box_w = 70 * mm
    box_h = 28 * mm
    box_x = mr - box_w
    box_y = h - 15 * mm - box_h
    
    # Borde del recuadro
    c.setStrokeColor(COLOR_PRIMARIO)
    c.setLineWidth(1.5)
    c.roundRect(box_x, box_y, box_w, box_h, 3 * mm)
    
    # Texto dentro del recuadro
    c.setFillColor(COLOR_PRIMARIO)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 8 * mm, f"RUC: {emisor.ruc}")
    
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 14 * mm, tipo_nombre)
    
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_SECUNDARIO)
    c.drawCentredString(box_x + box_w / 2, box_y + box_h - 22 * mm, numero_formato)
    
    # =============================================
    # DATOS DEL CLIENTE
    # =============================================
    y = box_y - 8 * mm
    
    # Fondo gris claro
    c.setFillColor(COLOR_FONDO_HEADER)
    c.rect(ml, y - 18 * mm, mr - ml, 22 * mm, fill=1, stroke=0)
    
    c.setFillColor(black)
    y -= 2 * mm
    
    # Fila 1
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 3 * mm, y, "FECHA EMISIÓN:")
    c.setFont("Helvetica", 8)
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y") if comprobante.fecha_emision else ""
    c.drawString(ml + 35 * mm, y, fecha)
    
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 95 * mm, y, "MONEDA:")
    c.setFont("Helvetica", 8)
    c.drawString(ml + 115 * mm, y, comprobante.moneda or "PEN")
    
    # Fila 2
    y -= 5 * mm
    tipo_doc_cliente = {
        "0": "SIN DOC.", "1": "DNI", "4": "C.EXT.", "6": "RUC", "7": "PASAPORTE"
    }
    
    c.setFont("Helvetica-Bold", 7.5)
    doc_label = tipo_doc_cliente.get(
        comprobante.cliente_tipo_documento or (cliente.tipo_documento if cliente else ""),
        "DOC."
    )
    c.drawString(ml + 3 * mm, y, f"{doc_label}:")
    c.setFont("Helvetica", 8)
    num_doc = comprobante.cliente_numero_documento or (cliente.numero_documento if cliente else "")
    c.drawString(ml + 35 * mm, y, num_doc)
    
    # Fila 3
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(ml + 3 * mm, y, "CLIENTE:")
    c.setFont("Helvetica", 8)
    nombre_cliente = comprobante.cliente_razon_social or (cliente.razon_social if cliente else "")
    # Truncar si es muy largo
    if len(nombre_cliente) > 60:
        nombre_cliente = nombre_cliente[:57] + "..."
    c.drawString(ml + 35 * mm, y, nombre_cliente)
    
    # Fila 4 - dirección
    y -= 5 * mm
    direccion_cliente = comprobante.cliente_direccion or (cliente.direccion if cliente else "")
    if direccion_cliente:
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(ml + 3 * mm, y, "DIRECCIÓN:")
        c.setFont("Helvetica", 8)
        if len(direccion_cliente) > 60:
            direccion_cliente = direccion_cliente[:57] + "..."
        c.drawString(ml + 35 * mm, y, direccion_cliente)
    
    # =============================================
    # TABLA DE ITEMS
    # =============================================
    y -= 10 * mm
    
    # Headers
    col_widths = [12 * mm, 15 * mm, 75 * mm, 20 * mm, 25 * mm, 25 * mm]
    if formato == "A5":
        col_widths = [10 * mm, 12 * mm, 45 * mm, 15 * mm, 20 * mm, 20 * mm]
    
    table_data = [["#", "CANT.", "DESCRIPCIÓN", "P.UNIT.", "IGV", "TOTAL"]]
    
    for i, item in enumerate(items, 1):
        cantidad = f"{float(item.cantidad):.2f}" if item.cantidad else "1.00"
        precio = f"{float(item.precio_unitario):.2f}" if item.precio_unitario else "0.00"
        igv = f"{float(item.igv):.2f}" if item.igv else "0.00"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)
        
        desc = item.descripcion or ""
        if len(desc) > 50 and formato != "A5":
            desc = desc[:47] + "..."
        elif len(desc) > 30 and formato == "A5":
            desc = desc[:27] + "..."
        
        table_data.append([
            str(i),
            cantidad,
            desc,
            precio,
            igv,
            f"{total_item:.2f}"
        ])
    
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARIO),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),   # #
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),    # CANT
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),     # P.UNIT
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),     # IGV
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),     # TOTAL
        
        # Bordes
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLOR_PRIMARIO),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, COLOR_LINEA),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, COLOR_FONDO_HEADER]),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    
    table_w, table_h = table.wrap(mr - ml, y)
    table.drawOn(c, ml, y - table_h)
    y = y - table_h
    
    # =============================================
    # TOTALES
    # =============================================
    y -= 5 * mm
    
    totales_x = mr - 65 * mm
    label_x = totales_x
    valor_x = mr - 3 * mm
    
    op_gravada = float(comprobante.op_gravada or 0)
    op_exonerada = float(comprobante.op_exonerada or 0)
    op_inafecta = float(comprobante.op_inafecta or 0)
    igv = float(comprobante.monto_igv or 0)
    total = float(comprobante.monto_total or 0)
    
    def draw_total_line(label, valor, y_pos, bold=False):
        font = "Helvetica-Bold" if bold else "Helvetica"
        size = 9 if bold else 8
        c.setFont(font, size)
        c.setFillColor(black)
        c.drawString(label_x, y_pos, label)
        c.drawRightString(valor_x, y_pos, f"S/ {valor:,.2f}")
        return y_pos - 5 * mm
    
    if op_gravada > 0:
        y = draw_total_line("Op. Gravada:", op_gravada, y)
    if op_exonerada > 0:
        y = draw_total_line("Op. Exonerada:", op_exonerada, y)
    if op_inafecta > 0:
        y = draw_total_line("Op. Inafecta:", op_inafecta, y)
    if igv > 0:
        y = draw_total_line("IGV (18%):", igv, y)
    
    # Línea antes del total
    c.setStrokeColor(COLOR_PRIMARIO)
    c.setLineWidth(1)
    c.line(label_x, y + 2 * mm, valor_x, y + 2 * mm)
    
    y = draw_total_line("TOTAL:", total, y, bold=True)
    
    # =============================================
    # QR CODE (si hay hash)
    # =============================================
    if hasattr(comprobante, 'hash_cpe') and comprobante.hash_cpe:
        qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{igv:.2f}|{total:.2f}|{fecha}|{comprobante.cliente_tipo_documento}|{comprobante.cliente_numero_documento}|{comprobante.hash_cpe}"
    else:
        qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{igv:.2f}|{total:.2f}|{fecha}"
    
    try:
        qr_img = qrcode.make(qr_data, box_size=3, border=1)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        from reportlab.lib.utils import ImageReader
        qr_size = 25 * mm
        c.drawImage(ImageReader(qr_buffer), ml, y - qr_size + 5 * mm, qr_size, qr_size)
    except Exception:
        pass  # QR es opcional
    
    # =============================================
    # OBSERVACIONES
    # =============================================
    if comprobante.observaciones:
        obs_y = y - 30 * mm if hasattr(comprobante, 'hash_cpe') and comprobante.hash_cpe else y - 5 * mm
        c.setFont("Helvetica", 7)
        c.setFillColor(COLOR_GRIS)
        c.drawString(ml, obs_y, f"Obs: {comprobante.observaciones[:100]}")
    
    # =============================================
    # FOOTER
    # =============================================
    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(w / 2, 10 * mm, "Representación impresa del comprobante electrónico")
    c.drawCentredString(w / 2, 7 * mm, f"Generado por facturalo.pro | {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Hash
    if hasattr(comprobante, 'hash_cpe') and comprobante.hash_cpe:
        c.drawCentredString(w / 2, 4 * mm, f"Hash: {comprobante.hash_cpe}")
    
    # Estado SUNAT
    if comprobante.estado == "aceptado":
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(HexColor("#059669"))
        c.drawCentredString(w / 2, 13 * mm, "✓ ACEPTADO POR SUNAT")
    
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _generar_ticket(buffer, comprobante, emisor, cliente, items):
    """Genera PDF formato ticket 80mm"""
    ticket_w = 80 * mm
    # Calcular alto dinámico
    ticket_h = (120 + len(items) * 12) * mm
    
    c = canvas.Canvas(buffer, pagesize=(ticket_w, ticket_h))
    ml = 3 * mm
    mr = ticket_w - 3 * mm
    y = ticket_h - 5 * mm
    
    numero_formato = f"{comprobante.serie}-{comprobante.numero:08d}"
    tipo_nombre = TIPOS_DOCUMENTO.get(comprobante.tipo_documento, "COMPROBANTE")
    
    # Emisor
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(ticket_w / 2, y, emisor.razon_social or "")
    y -= 4 * mm
    
    c.setFont("Helvetica", 7)
    c.drawCentredString(ticket_w / 2, y, f"RUC: {emisor.ruc}")
    y -= 3.5 * mm
    
    if hasattr(emisor, 'direccion') and emisor.direccion:
        c.drawCentredString(ticket_w / 2, y, emisor.direccion[:40])
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
    
    # Fecha y cliente
    c.setFont("Helvetica", 7)
    fecha = comprobante.fecha_emision.strftime("%d/%m/%Y %H:%M") if comprobante.fecha_emision else ""
    c.drawString(ml, y, f"Fecha: {fecha}")
    y -= 3.5 * mm
    
    num_doc = comprobante.cliente_numero_documento or ""
    c.drawString(ml, y, f"Doc: {num_doc}")
    y -= 3.5 * mm
    
    nombre = comprobante.cliente_razon_social or ""
    if len(nombre) > 35:
        nombre = nombre[:32] + "..."
    c.drawString(ml, y, f"Cliente: {nombre}")
    y -= 4 * mm
    
    # Línea
    c.setDash(1, 2)
    c.line(ml, y, mr, y)
    c.setDash()
    y -= 4 * mm
    
    # Items
    c.setFont("Helvetica-Bold", 7)
    c.drawString(ml, y, "CANT")
    c.drawString(ml + 12 * mm, y, "DESCRIPCIÓN")
    c.drawRightString(mr, y, "TOTAL")
    y -= 3 * mm
    
    c.setFont("Helvetica", 7)
    for item in items:
        desc = (item.descripcion or "")[:25]
        cant = f"{float(item.cantidad):.0f}" if item.cantidad else "1"
        total_item = float(item.monto_linea or item.subtotal or 0) + float(item.igv or 0)
        
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
    
    # Footer
    c.setFont("Helvetica", 5.5)
    c.setFillColor(COLOR_GRIS)
    c.drawCentredString(ticket_w / 2, y, "Representación impresa del CE")
    y -= 3 * mm
    c.drawCentredString(ticket_w / 2, y, "facturalo.pro")
    
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes