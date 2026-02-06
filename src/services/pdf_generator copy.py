from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from io import BytesIO
from pathlib import Path
from datetime import datetime
from decimal import Decimal

from src.services.qr_generator import generar_qr_sunat


def generar_pdf_factura(
    emisor_ruc: str,
    emisor_razon_social: str,
    emisor_direccion: str,
    tipo_comprobante: str,
    serie: str,
    numero: int,
    fecha_emision: datetime,
    cliente_ruc: str,
    cliente_razon_social: str,
    cliente_direccion: str,
    items: list,
    subtotal: Decimal,
    igv: Decimal,
    total: Decimal,
    moneda: str = "PEN",
    hash_cpe: str = "",
    estado: str = "aceptado",
    emisor_logo: str = "",
    emisor_telefono: str = "",
    emisor_email: str = "",
    emisor_web: str = "",
    emisor_lema: str = "",
    emisor_establecimiento_anexo: str = "",
    es_agente_retencion: bool = False,
    es_agente_percepcion: bool = False,
    observaciones: str = "",
    color_primario: str = "#2c3e50",
    color_secundario: str = "#e74c3c"
) -> bytes:
    """Genera PDF de factura electrónica con WeasyPrint optimizado"""
    
    # Configurar Jinja2
    templates_path = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_path)))
    template = env.get_template("comprobantes/factura.html")
    
    # Generar código QR
    qr_base64 = generar_qr_sunat(
        emisor_ruc=emisor_ruc,
        tipo_comprobante=tipo_comprobante,
        serie=serie,
        numero=numero,
        fecha_emision=fecha_emision.strftime("%Y-%m-%d"),
        monto_total=float(total),
        igv=float(igv),
        cliente_documento=cliente_ruc,
        cliente_tipo_doc="6" if len(cliente_ruc) == 11 else "1"
    )
    
    # Determinar nombre del tipo de documento
    tipo_doc_nombre = "FACTURA ELECTRÓNICA" if tipo_comprobante == "01" else "BOLETA ELECTRÓNICA"
    cliente_tipo_doc = "RUC" if len(cliente_ruc) == 11 else "DNI"
    
    # Calcular totales por tipo de afectación
    op_gravadas = Decimal('0.00')
    op_exoneradas = Decimal('0.00')
    op_inafectas = Decimal('0.00')
    
    for item in items:
        tipo_afect = item.get('tipo_afectacion', '10')
        item_total = Decimal(str(item.get('cantidad', 0))) * Decimal(str(item.get('precio_unitario', 0)))
        
        if tipo_afect == '10':
            op_gravadas += item_total
        elif tipo_afect == '20':
            op_exoneradas += item_total
        elif tipo_afect == '30':
            op_inafectas += item_total
    
    # Preparar items
    items_preparados = [
        {
            "orden": item.get("orden", idx + 1),
            "descripcion": item.get("descripcion", ""),
            "cantidad": item.get("cantidad", 0),
            "unidad": item.get("unidad", "NIU"),
            "precio_unitario": f"{float(item.get('precio_unitario', 0)):.2f}",
            "total": f"{float(item.get('cantidad', 0)) * float(item.get('precio_unitario', 0)):.2f}",
            "tipo_afectacion": item.get("tipo_afectacion", "10"),
            "es_bonificacion": item.get("es_bonificacion", False)
        }
        for idx, item in enumerate(items)
    ]
    
    # Context para template
    context = {
        "emisor_ruc": emisor_ruc,
        "emisor_razon_social": emisor_razon_social,
        "emisor_direccion": emisor_direccion,
        "emisor_logo": emisor_logo,
        "emisor_telefono": emisor_telefono,
        "emisor_email": emisor_email,
        "emisor_web": emisor_web,
        "emisor_lema": emisor_lema,
        "emisor_establecimiento_anexo": emisor_establecimiento_anexo,
        "es_agente_retencion": es_agente_retencion,
        "es_agente_percepcion": es_agente_percepcion,
        "color_primario": color_primario,
        "color_secundario": color_secundario,
        "tipo_doc_nombre": tipo_doc_nombre,
        "serie": serie,
        "numero": str(numero).zfill(8),
        "fecha_emision": fecha_emision.strftime("%d/%m/%Y"),
        "cliente_ruc": cliente_ruc,
        "cliente_razon_social": cliente_razon_social,
        "cliente_direccion": cliente_direccion,
        "cliente_tipo_doc": cliente_tipo_doc,
        "moneda": "S/" if moneda == "PEN" else moneda,
        "items": items_preparados,
        "subtotal": f"{float(subtotal):.2f}",
        "igv": f"{float(igv):.2f}",
        "total": f"{float(total):.2f}",
        "op_gravadas": f"{float(op_gravadas):.2f}",
        "op_exoneradas": f"{float(op_exoneradas):.2f}",
        "op_inafectas": f"{float(op_inafectas):.2f}",
        "observaciones": observaciones,
        "qr_code": qr_base64,
        "hash_cpe": hash_cpe or "N/A",
        "estado": estado
    }
    
    # Renderizar HTML
    html_content = template.render(**context)
    
    # Convertir a PDF con WeasyPrint (optimizado)
    pdf_file = BytesIO()
    HTML(string=html_content, base_url=str(templates_path)).write_pdf(
        pdf_file,
        optimize_size=('fonts', 'images')  # Optimización
    )
    
    pdf_file.seek(0)
    return pdf_file.getvalue()


def generar_pdf_comprobante(comprobante_data: dict) -> bytes:
    """Wrapper conveniente"""
    return generar_pdf_factura(
        emisor_ruc=comprobante_data["emisor_ruc"],
        emisor_razon_social=comprobante_data["emisor_razon_social"],
        emisor_direccion=comprobante_data["emisor_direccion"],
        tipo_comprobante=comprobante_data["tipo_comprobante"],
        serie=comprobante_data["serie"],
        numero=comprobante_data["numero"],
        fecha_emision=comprobante_data["fecha_emision"],
        cliente_ruc=comprobante_data["cliente_ruc"],
        cliente_razon_social=comprobante_data["cliente_razon_social"],
        cliente_direccion=comprobante_data["cliente_direccion"],
        items=comprobante_data["items"],
        subtotal=comprobante_data["subtotal"],
        igv=comprobante_data["igv"],
        total=comprobante_data["total"],
        moneda=comprobante_data.get("moneda", "PEN"),
        hash_cpe=comprobante_data.get("hash_cpe", ""),
        estado=comprobante_data.get("estado", "aceptado"),
        emisor_logo=comprobante_data.get("emisor_logo", ""),
        emisor_telefono=comprobante_data.get("emisor_telefono", ""),
        emisor_email=comprobante_data.get("emisor_email", ""),
        emisor_web=comprobante_data.get("emisor_web", ""),
        emisor_lema=comprobante_data.get("emisor_lema", ""),
        emisor_establecimiento_anexo=comprobante_data.get("emisor_establecimiento_anexo", ""),
        es_agente_retencion=comprobante_data.get("es_agente_retencion", False),
        es_agente_percepcion=comprobante_data.get("es_agente_percepcion", False),
        observaciones=comprobante_data.get("observaciones", ""),
        color_primario=comprobante_data.get("color_primario", "#2c3e50"),
        color_secundario=comprobante_data.get("color_secundario", "#e74c3c")
    )