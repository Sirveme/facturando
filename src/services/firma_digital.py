"""
Firma Digital XMLDSig para comprobantes electrónicos SUNAT.
Compatible con signxml 2.x y 3.x.

IMPORTANTE: No usar pretty_print después de firmar,
y la firma debe quedar en ExtensionContent sin moverla post-firma.
"""

from lxml import etree
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.primitives import serialization
import logging

logger = logging.getLogger(__name__)

# ── Detectar API de signxml ──
try:
    from signxml import XMLSigner, SignatureMethod, SignatureConstructionMethod, DigestAlgorithm
    _USE_ENUMS = True
    logger.info("signxml: usando API con enums (v3.x)")
except ImportError:
    from signxml import XMLSigner
    _USE_ENUMS = False
    logger.info("signxml: usando API con strings (v2.x)")

# Namespaces
NS_EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"


def _extract_key_cert_from_pfx(pfx_bytes: bytes, password: str):
    """Extrae clave privada y certificado PEM de un archivo PFX/P12."""
    pwd = password.encode() if password else None
    pk, cert, _ = load_key_and_certificates(pfx_bytes, pwd)
    if pk is None or cert is None:
        raise ValueError("No se pudo extraer clave o certificado del PFX")
    private_pem = pk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return private_pem, cert_pem


def firmar_xml(xml_bytes: bytes, certificado_pfx: bytes, password: str) -> bytes:
    """Firma XML UBL 2.1 con RSA-SHA256 para SUNAT.

    Estrategia:
    1. Parsear XML sin espacios en blanco extra
    2. Quitar el placeholder ExtensionContent vacío
    3. Firmar con enveloped signature (firma va al root)
    4. Mover firma a UBLExtensions/ExtensionContent
    5. Serializar SIN pretty_print para preservar el digest

    Args:
        xml_bytes: XML sin firmar (bytes UTF-8)
        certificado_pfx: Contenido del archivo .pfx/.p12
        password: Contraseña del certificado

    Returns:
        XML firmado como bytes UTF-8
    """
    # 1. Parsear XML quitando whitespace extra para canonicalización limpia
    parser = etree.XMLParser(remove_blank_text=True)
    doc = etree.fromstring(xml_bytes, parser=parser)

    # 2. Extraer clave y certificado
    priv_pem, cert_pem = _extract_key_cert_from_pfx(certificado_pfx, password)

    # 3. Buscar y vaciar ExtensionContent (quitar placeholder)
    #    Guardamos referencia al UBLExtension padre
    ext_content = doc.find(".//{%s}ExtensionContent" % NS_EXT)
    ubl_extension = None

    if ext_content is not None:
        ubl_extension = ext_content.getparent()
        # Limpiar cualquier contenido previo
        for child in list(ext_content):
            ext_content.remove(child)
    else:
        # Crear estructura UBLExtensions si no existe
        ubl_exts = doc.find("{%s}UBLExtensions" % NS_EXT)
        if ubl_exts is None:
            ubl_exts = etree.SubElement(doc, etree.QName(NS_EXT, "UBLExtensions"))
            doc.insert(0, ubl_exts)
        ubl_extension = etree.SubElement(ubl_exts, etree.QName(NS_EXT, "UBLExtension"))
        ext_content = etree.SubElement(ubl_extension, etree.QName(NS_EXT, "ExtensionContent"))

    # 4. Configurar XMLSigner
    c14n = "http://www.w3.org/2001/10/xml-exc-c14n#"

    if _USE_ENUMS:
        signer = XMLSigner(
            method=SignatureConstructionMethod.enveloped,
            signature_algorithm=SignatureMethod.RSA_SHA256,
            digest_algorithm=DigestAlgorithm.SHA256,
            c14n_algorithm=c14n,
        )
    else:
        signer = XMLSigner(
            method="enveloped",
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm=c14n,
        )

    # 5. Firmar el documento completo
    #    signxml coloca la firma como último hijo del root
    signed_root = signer.sign(doc, key=priv_pem, cert=cert_pem)

    # 6. Mover firma a ExtensionContent
    #    IMPORTANTE: Después de mover, NO reformatear el XML
    sig_elem = signed_root.find("{%s}Signature" % NS_DS)
    if sig_elem is None:
        # Buscar en cualquier nivel (por si signxml lo puso en otro lugar)
        sig_elem = signed_root.find(".//{%s}Signature" % NS_DS)

    ext_content = signed_root.find(".//{%s}ExtensionContent" % NS_EXT)

    if sig_elem is not None and ext_content is not None:
        parent = sig_elem.getparent()
        if parent is not None and parent.tag != etree.QName(NS_EXT, "ExtensionContent"):
            # Guardar el tail/text para no alterar whitespace
            sig_elem.tail = None
            parent.remove(sig_elem)
            ext_content.append(sig_elem)
            logger.info("Firma XMLDSig movida a ExtensionContent")
        else:
            logger.info("Firma ya está en ExtensionContent")
    else:
        logger.warning(
            "No se pudo reubicar firma: sig=%s, ext=%s",
            sig_elem is not None,
            ext_content is not None,
        )

    # 7. Serializar SIN pretty_print para no alterar el contenido firmado
    signed_xml = etree.tostring(
        signed_root, xml_declaration=True, encoding="UTF-8"
    )

    logger.info("XML firmado correctamente (%d bytes)", len(signed_xml))
    return signed_xml