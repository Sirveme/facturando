"""
Firma y empaquetado de la GRE (tipo 09).

Reutiliza:
  - build_despatch_advice_xml (xml_generator_gre)
  - firmar_xml (firma_digital) — XMLDSig en ExtensionContent, mismo certificado
  - extracción de DigestValue (mismo patrón que facturas en tasks/envio_sunat)

Nombre de archivo: {RUC}-09-{serie}-{numero}.xml  →  zip {RUC}-09-{serie}-{numero}.zip
"""

from io import BytesIO
import zipfile
import logging

from lxml import etree

from src.services.xml_generator_gre import build_despatch_advice_xml
from src.services.firma_digital import firmar_xml

logger = logging.getLogger(__name__)


def extraer_digest_value(signed_xml: bytes) -> str | None:
    """Extrae el DigestValue (resumen del CPE) del XML firmado."""
    try:
        doc = etree.fromstring(signed_xml)
        els = doc.xpath("//*[local-name()='DigestValue']")
        if els and els[0].text:
            return els[0].text.strip()
    except Exception as e:
        logger.warning("[GRE_PKG] No se pudo extraer DigestValue: %s", e)
    return None


def firmar_y_empaquetar_gre(guia, emisor: dict, pfx_bytes: bytes, password: str) -> dict:
    """Genera, firma y empaqueta la GRE.

    Args:
        guia: instancia GuiaRemision (con .items).
        emisor: dict con {'ruc', 'razon_social', ...} (patrón facturas).
        pfx_bytes: certificado PFX descifrado.
        password: contraseña del PFX descifrada.

    Returns:
        {
          "zip_name": str,
          "zip_bytes": bytes,
          "xml_name": str,
          "signed_xml": bytes,
          "digest_value": str | None,
        }
    """
    ruc = emisor.get('ruc', '')
    serie = getattr(guia, 'serie', 'T060')
    numero = getattr(guia, 'numero', 1)

    base_name = f"{ruc}-09-{serie}-{numero}"
    xml_name = f"{base_name}.xml"
    zip_name = f"{base_name}.zip"

    # 1. Generar XML sin firmar
    xml_bytes = build_despatch_advice_xml(guia, emisor)

    # 2. Firmar (XMLDSig en ExtensionContent, mismo módulo que facturas)
    signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)

    # 3. DigestValue (= hash_cpe)
    digest_value = extraer_digest_value(signed_xml)

    # 4. Empaquetar ZIP
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, signed_xml)
    zip_bytes = buf.getvalue()

    logger.info("[GRE_PKG] %s firmada y empaquetada (%d bytes zip, digest=%s)",
                zip_name, len(zip_bytes), digest_value)

    return {
        "zip_name": zip_name,
        "zip_bytes": zip_bytes,
        "xml_name": xml_name,
        "signed_xml": signed_xml,
        "digest_value": digest_value,
    }
