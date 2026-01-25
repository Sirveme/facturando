import qrcode
from io import BytesIO
import base64

def generar_qr_sunat(
    emisor_ruc: str,
    tipo_comprobante: str,
    serie: str,
    numero: int,
    fecha_emision: str,
    monto_total: float,
    igv: float,
    cliente_documento: str = "",
    cliente_tipo_doc: str = "1"
) -> str:
    """
    Genera código QR según especificación SUNAT.
    
    Formato del texto QR:
    RUC_EMISOR|TIPO_DOC|SERIE|NUMERO|IGV|TOTAL|FECHA|TIPO_DOC_CLIENTE|NUM_DOC_CLIENTE|
    
    Retorna: string base64 de la imagen QR
    """
    
    # Construir texto según formato SUNAT
    texto_qr = (
        f"{emisor_ruc}|"
        f"{tipo_comprobante}|"
        f"{serie}|"
        f"{numero}|"
        f"{igv:.2f}|"
        f"{monto_total:.2f}|"
        f"{fecha_emision}|"
        f"{cliente_tipo_doc}|"
        f"{cliente_documento}|"
    )
    
    # Generar QR
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(texto_qr)
    qr.make(fit=True)
    
    # Crear imagen
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convertir a base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return f"data:image/png;base64,{img_str}"


def generar_qr_bytes(
    emisor_ruc: str,
    tipo_comprobante: str,
    serie: str,
    numero: int,
    fecha_emision: str,
    monto_total: float,
    igv: float,
    cliente_documento: str = "",
    cliente_tipo_doc: str = "1"
) -> bytes:
    """
    Genera código QR y retorna bytes directamente.
    Útil para incrustar en PDF.
    """
    
    texto_qr = (
        f"{emisor_ruc}|"
        f"{tipo_comprobante}|"
        f"{serie}|"
        f"{numero}|"
        f"{igv:.2f}|"
        f"{monto_total:.2f}|"
        f"{fecha_emision}|"
        f"{cliente_tipo_doc}|"
        f"{cliente_documento}|"
    )
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(texto_qr)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return buffered.getvalue()