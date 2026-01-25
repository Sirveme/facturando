# v3 - ReportLab - Acepta dict como único argumento
"""
Generador de PDF para comprobantes electrónicos
Usando ReportLab (100% Python, sin dependencias del sistema)
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from io import BytesIO
import qrcode
from datetime import datetime


def generar_pdf_comprobante(comprobante_data: dict) -> bytes:
    """
    Genera PDF del comprobante electrónico
    
    Args:
        comprobante_data: dict con todos los datos del comprobante
        
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
    
    # Extraer datos del dict
    emisor_ruc = comprobante_data.get('emisor_ruc', '')
    emisor_razon_social = comprobante_data.get('emisor_razon_social', 'EMPRESA')
    emisor_direccion = comprobante_data.get('emisor_direccion', '')
    emisor_telefono = comprobante_data.get('emisor_telefono', '')
    emisor_email = comprobante_data.get('emisor_email', '')
    
    tipo_doc = comprobante_data.get('tipo_comprobante', '01')
    serie = comprobante_data.get('serie', 'F001')
    numero = comprobante_data.get('numero', 1)
    fecha_emision = comprobante_data.get('fecha_emision')
    moneda = comprobante_data.get('moneda', 'PEN')
    
    cliente_ruc = comprobante_data.get('cliente_ruc', '-')
    cliente_razon_social = comprobante_data.get('cliente_razon_social', 'CLIENTE VARIOS')
    cliente_direccion = comprobante_data.get('cliente_direccion', '-')
    
    items = comprobante_data.get('items', [])
    
    subtotal = float(comprobante_data.get('subtotal', 0) or 0)
    igv = float(comprobante_data.get('igv', 0) or 0)
    total = float(comprobante_data.get('total', 0) or 0)
    
    hash_cpe = comprobante_data.get('hash_cpe', '')
    
    # Elementos del documento
    elements = []
    
    # === ENCABEZADO EMISOR ===
    tipo_doc_nombre = "FACTURA ELECTRÓNICA" if tipo_doc == '01' else "BOLETA DE VENTA ELECTRÓNICA"
    
    elements.append(Paragraph(f"<b>{emisor_razon_social}</b>", style_title))
    elements.append(Paragraph(f"RUC: {emisor_ruc}", style_subtitle))
    
    if emisor_direccion:
        elements.append(Paragraph(emisor_direccion, style_subtitle))
    if emisor_telefono:
        elements.append(Paragraph(f"Tel: {emisor_telefono}", style_subtitle))
    if emisor_email:
        elements.append(Paragraph(emisor_email, style_subtitle))
    
    elements.append(Spacer(1, 0.5*cm))
    
    # === TIPO DE DOCUMENTO Y NÚMERO ===
    numero_formateado = f"{serie}-{str(numero).zfill(8)}"
    
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
    if isinstance(fecha_emision, str):
        fecha_str = fecha_emision
    elif fecha_emision:
        fecha_str = fecha_emision.strftime('%d/%m/%Y')
    else:
        fecha_str = datetime.now().strftime('%d/%m/%Y')
    
    info_data = [
        ['Fecha de Emisión:', fecha_str, 'Moneda:', moneda],
    ]
    
    info_table = Table(info_data, colWidths=[4*cm, 5*cm, 3*cm, 4*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*cm))
    
    # === DATOS DEL CLIENTE ===
    elements.append(Paragraph("<b>DATOS DEL CLIENTE</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    cliente_data = [
        ['RUC/DNI:', cliente_ruc],
        ['Razón Social:', cliente_razon_social],
        ['Dirección:', cliente_direccion],
    ]
    
    cliente_table = Table(cliente_data, colWidths=[3*cm, 13*cm])
    cliente_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    elements.append(cliente_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === DETALLE DE ITEMS ===
    elements.append(Paragraph("<b>DETALLE</b>", style_bold))
    elements.append(Spacer(1, 0.2*cm))
    
    detalle_data = [['#', 'Descripción', 'Cant.', 'Unidad', 'P. Unit.', 'Total']]
    
    if items:
        for i, item in enumerate(items, 1):
            cantidad = float(item.get('cantidad', 1))
            precio = float(item.get('precio_unitario', 0))
            item_total = cantidad * precio
            
            detalle_data.append([
                str(i),
                item.get('descripcion', '-'),
                f"{cantidad:.2f}",
                item.get('unidad', 'NIU'),
                f"S/ {precio:.2f}",
                f"S/ {item_total:.2f}"
            ])
    else:
        detalle_data.append(['1', 'Producto/Servicio', '1.00', 'NIU', f"S/ {subtotal:.2f}", f"S/ {subtotal:.2f}"])
    
    detalle_table = Table(detalle_data, colWidths=[1*cm, 8*cm, 1.5*cm, 1.5*cm, 2*cm, 2*cm])
    detalle_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5E6AD2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#5E6AD2')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(detalle_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === TOTALES ===
    totales_data = [
        ['', 'Op. Gravada:', f"S/ {subtotal:.2f}"],
        ['', 'IGV (18%):', f"S/ {igv:.2f}"],
        ['', 'TOTAL:', f"S/ {total:.2f}"],
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
    ]))
    
    elements.append(totales_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # === CÓDIGO QR ===
    try:
        qr_data = f"{emisor_ruc}|{tipo_doc}|{serie}|{numero}|{igv:.2f}|{total:.2f}|{fecha_str}|||"
        
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        qr_section_data = [
            [Image(qr_buffer, width=2.5*cm, height=2.5*cm), 
             Paragraph(f"<b>Hash:</b><br/>{hash_cpe[:20] if hash_cpe else 'N/A'}...", style_normal)]
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


# Alias para compatibilidad
def generar_pdf_factura(comprobante_data: dict) -> bytes:
    """Alias para compatibilidad"""
    return generar_pdf_comprobante(comprobante_data)