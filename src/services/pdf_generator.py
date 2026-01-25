"""
Generador de PDF para comprobantes electrónicos
Usando ReportLab (100% Python, sin dependencias del sistema)
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfgen import canvas
from io import BytesIO
import qrcode
import base64
from datetime import datetime


def generar_pdf_comprobante(comprobante, emisor, lineas) -> bytes:
    """
    Genera PDF del comprobante electrónico
    
    Args:
        comprobante: Objeto Comprobante
        emisor: Objeto Emisor
        lineas: Lista de LineaDetalle
        
    Returns:
        bytes: Contenido del PDF
    """
    buffer = BytesIO()
    
    # Crear documento
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5*cm,
        leftMargin=1.5*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm
    )
    
    # Estilos
    styles = getSampleStyleSheet()
    
    # Estilos personalizados
    style_title = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=6
    )
    
    style_subtitle = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=3
    )
    
    style_normal = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9,
        spaceAfter=3
    )
    
    style_bold = ParagraphStyle(
        'CustomBold',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Helvetica-Bold'
    )
    
    style_right = ParagraphStyle(
        'Right',
        parent=styles['Normal'],
        fontSize=9,
        alignment=TA_RIGHT
    )
    
    # Elementos del documento
    elements = []
    
    # === ENCABEZADO EMISOR ===
    tipo_doc_nombre = "FACTURA ELECTRÓNICA" if comprobante.tipo_documento == '01' else "BOLETA DE VENTA ELECTRÓNICA"
    
    # Datos del emisor
    elements.append(Paragraph(f"<b>{emisor.razon_social}</b>", style_title))
    elements.append(Paragraph(f"RUC: {emisor.ruc}", style_subtitle))
    if emisor.direccion:
        elements.append(Paragraph(emisor.direccion, style_subtitle))
    if emisor.telefono:
        elements.append(Paragraph(f"Tel: {emisor.telefono}", style_subtitle))
    if emisor.email:
        elements.append(Paragraph(emisor.email, style_subtitle))
    
    elements.append(Spacer(1, 0.5*cm))
    
    # === TIPO DE DOCUMENTO Y NÚMERO ===
    numero_formateado = f"{comprobante.serie}-{str(comprobante.numero).zfill(8)}"
    
    doc_header_data = [
        [Paragraph(f"<b>{tipo_doc_nombre}</b>", style_title)],
        [Paragraph(f"<b>{numero_formateado}</b>", style_title)]
    ]
    
    doc_header_table = Table(doc_header_data, colWidths=[8*cm])
    doc_header_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#5E6AD2')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0F1FF')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    elements.append(doc_header_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === DATOS DEL COMPROBANTE ===
    fecha_emision = comprobante.fecha_emision.strftime('%d/%m/%Y') if comprobante.fecha_emision else ''
    
    info_data = [
        ['Fecha de Emisión:', fecha_emision, 'Moneda:', comprobante.moneda or 'PEN'],
        ['Tipo de Operación:', 'Venta Interna', 'Condición:', 'Contado'],
    ]
    
    info_table = Table(info_data, colWidths=[4*cm, 5*cm, 3*cm, 4*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*cm))
    
    # === DATOS DEL CLIENTE ===
    elements.append(Paragraph("<b>DATOS DEL CLIENTE</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    # Obtener datos del cliente (si existe)
    cliente_ruc = comprobante.cliente_ruc if hasattr(comprobante, 'cliente_ruc') and comprobante.cliente_ruc else '-'
    cliente_nombre = comprobante.cliente_razon_social if hasattr(comprobante, 'cliente_razon_social') and comprobante.cliente_razon_social else 'CLIENTE VARIOS'
    cliente_direccion = comprobante.cliente_direccion if hasattr(comprobante, 'cliente_direccion') and comprobante.cliente_direccion else '-'
    
    cliente_data = [
        ['RUC/DNI:', cliente_ruc],
        ['Razón Social:', cliente_nombre],
        ['Dirección:', cliente_direccion],
    ]
    
    cliente_table = Table(cliente_data, colWidths=[3*cm, 13*cm])
    cliente_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    elements.append(cliente_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === DETALLE DE ITEMS ===
    elements.append(Paragraph("<b>DETALLE</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    # Encabezados de tabla
    detalle_data = [
        ['#', 'Descripción', 'Cant.', 'Unidad', 'P. Unit.', 'Total']
    ]
    
    # Agregar líneas
    for i, linea in enumerate(lineas, 1):
        detalle_data.append([
            str(i),
            linea.descripcion or '-',
            f"{linea.cantidad:.2f}" if linea.cantidad else '1.00',
            linea.unidad_medida or 'NIU',
            f"S/ {linea.precio_unitario:.2f}" if linea.precio_unitario else 'S/ 0.00',
            f"S/ {linea.subtotal:.2f}" if linea.subtotal else 'S/ 0.00'
        ])
    
    # Si no hay líneas, agregar una fila vacía
    if not lineas:
        detalle_data.append(['1', 'Producto/Servicio', '1.00', 'NIU', f"S/ {comprobante.monto_base:.2f}", f"S/ {comprobante.monto_base:.2f}"])
    
    detalle_table = Table(detalle_data, colWidths=[1*cm, 8*cm, 1.5*cm, 1.5*cm, 2*cm, 2*cm])
    detalle_table.setStyle(TableStyle([
        # Encabezado
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5E6AD2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Cuerpo
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # #
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Cant
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # Unidad
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),  # Precios
        
        # Bordes
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#5E6AD2')),
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#EEEEEE')),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(detalle_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === TOTALES ===
    monto_base = comprobante.monto_base or 0
    monto_igv = comprobante.monto_igv or 0
    monto_total = comprobante.monto_total or 0
    
    totales_data = [
        ['', 'Op. Gravada:', f"S/ {monto_base:.2f}"],
        ['', 'IGV (18%):', f"S/ {monto_igv:.2f}"],
        ['', 'TOTAL:', f"S/ {monto_total:.2f}"],
    ]
    
    totales_table = Table(totales_data, colWidths=[10*cm, 3*cm, 3*cm])
    totales_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (1, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (1, -1), (-1, -1), 11),
        ('LINEABOVE', (1, -1), (-1, -1), 1, colors.HexColor('#5E6AD2')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    
    elements.append(totales_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === CÓDIGO QR ===
    try:
        qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{monto_igv:.2f}|{monto_total:.2f}|{fecha_emision}|||"
        
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        # Tabla con QR y hash
        qr_section_data = [
            [Image(qr_buffer, width=2.5*cm, height=2.5*cm), 
             Paragraph(f"<b>Hash:</b><br/>{comprobante.hash_cpe[:20] if comprobante.hash_cpe else 'N/A'}...", style_normal)]
        ]
        
        qr_table = Table(qr_section_data, colWidths=[3*cm, 13*cm])
        qr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        elements.append(qr_table)
    except Exception as e:
        print(f"Error generando QR: {e}")
    
    elements.append(Spacer(1, 0.3*cm))
    
    # === PIE DE PÁGINA ===
    elements.append(Paragraph(
        "Representación impresa de la Factura Electrónica. Consulte en: https://facturalo.pro",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER, textColor=colors.gray)
    ))
    
    # Construir PDF
    doc.build(elements)
    
    buffer.seek(0)
    return buffer.getvalue()


def generar_pdf_simple(comprobante, emisor) -> bytes:
    """
    Genera un PDF simple sin dependencias de líneas detalle
    Útil para testing o cuando no hay líneas
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Título
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width/2, height - 2*cm, emisor.razon_social)
    
    c.setFont("Helvetica", 10)
    c.drawCentredString(width/2, height - 2.5*cm, f"RUC: {emisor.ruc}")
    
    # Tipo documento
    tipo_doc = "FACTURA ELECTRÓNICA" if comprobante.tipo_documento == '01' else "BOLETA ELECTRÓNICA"
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width/2, height - 4*cm, tipo_doc)
    
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width/2, height - 4.8*cm, f"{comprobante.serie}-{str(comprobante.numero).zfill(8)}")
    
    # Datos
    c.setFont("Helvetica", 10)
    y = height - 6*cm
    
    c.drawString(2*cm, y, f"Fecha: {comprobante.fecha_emision.strftime('%d/%m/%Y')}")
    y -= 0.6*cm
    c.drawString(2*cm, y, f"Moneda: {comprobante.moneda or 'PEN'}")
    
    # Totales
    y -= 2*cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2*cm, y, "TOTALES:")
    
    c.setFont("Helvetica", 10)
    y -= 0.6*cm
    c.drawString(2*cm, y, f"Subtotal: S/ {comprobante.monto_base:.2f}")
    y -= 0.5*cm
    c.drawString(2*cm, y, f"IGV (18%): S/ {comprobante.monto_igv:.2f}")
    y -= 0.5*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, f"TOTAL: S/ {comprobante.monto_total:.2f}")
    
    c.save()
    buffer.seek(0)
    return buffer.getvalue()