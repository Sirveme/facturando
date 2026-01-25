from lxml import etree
try:
    # Prefer enums if available in signxml
    from signxml import XMLSigner, SignatureMethod, SignatureConstructionMethod, DigestAlgorithm
    has_enums = True
except Exception:
    from signxml import XMLSigner
    SignatureMethod = None
    SignatureConstructionMethod = None
    DigestAlgorithm = None
    has_enums = False
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.primitives import serialization


def _extract_key_cert_from_pfx(pfx_bytes: bytes, password: str):
    # returns (private_key_pem_bytes, cert_pem_bytes)
    pk, cert, add_certs = load_key_and_certificates(pfx_bytes, password.encode() if password else None)
    if pk is None or cert is None:
        raise ValueError('No se pudo extraer clave o certificado del PFX')
    private_pem = pk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return private_pem, cert_pem


def firmar_xml(xml_bytes: bytes, certificado_pfx: bytes, password: str) -> bytes:
    """Firma XML (ubicación UBLExtensions/ext:ExtensionContent).

    - Usa RSA-SHA256 y canonicalización exclusiva (C14N)
    - Devuelve XML firmado como bytes UTF-8
    """
    # Parse xml
    parser = etree.XMLParser(remove_blank_text=True)
    doc = etree.fromstring(xml_bytes, parser=parser)

    # Extract key and cert
    priv_pem, cert_pem = _extract_key_cert_from_pfx(certificado_pfx, password)

    # Sign entire document (enveloped)
    # Prefer enums for algorithms if available (signxml enums map to full URIs)
    if has_enums and SignatureMethod is not None and SignatureConstructionMethod is not None and DigestAlgorithm is not None:
        sig_alg = SignatureMethod.RSA_SHA256
        sig_construction = SignatureConstructionMethod.enveloped
        digest_alg = DigestAlgorithm.SHA256
    else:
        # use shorthands accepted by signxml
        sig_alg = "rsa-sha256"
        sig_construction = "enveloped"
        digest_alg = "sha256"
    c14n = "http://www.w3.org/2001/10/xml-exc-c14n#"

    # Prepare ExtensionContent placeholder so signature is created inside it
    ds_ns = "http://www.w3.org/2000/09/xmldsig#"
    ext_ns = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
    ext_content = doc.find('.//{%s}ExtensionContent' % ext_ns)
    if ext_content is None:
        # create path: UBLExtensions/UBLExtension/ExtensionContent
        ubl_exts = etree.SubElement(doc, etree.QName(ext_ns, 'UBLExtensions'))
        ubl_ext = etree.SubElement(ubl_exts, etree.QName(ext_ns, 'UBLExtension'))
        ext_content = etree.SubElement(ubl_ext, etree.QName(ext_ns, 'ExtensionContent'))

    signer = XMLSigner(
        method=sig_construction,
        signature_algorithm=sig_alg,
        digest_algorithm=digest_alg,
        c14n_algorithm=c14n
    )
    signed_root = signer.sign(doc, key=priv_pem, cert=cert_pem)

    # Debug: check signature element in signed_root
    try:
        sig_elem = signed_root.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
        print("¿Firma encontrada después de sign()?:", sig_elem is not None)
        if sig_elem is not None:
            parent = sig_elem.getparent()
            print("Firma está en:", parent.tag if parent is not None else "ROOT")
        all_sigs = signed_root.findall('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
        print("Total firmas encontradas:", len(all_sigs))
    except Exception:
        print("Signature debug: <failed>")

    # signed_root should already contain the Signature; move it to ExtensionContent if signxml placed it elsewhere
    try:
        sig_elem = signed_root.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
        ext_content = signed_root.find('.//{%s}ExtensionContent' % ext_ns)
        if sig_elem is not None and ext_content is not None:
            parent = sig_elem.getparent()
            if parent is not None:
                parent.remove(sig_elem)
            ext_content.append(sig_elem)
            print("Firma movida a ExtensionContent")
        else:
            if sig_elem is None:
                print("No se encontró elemento Signature para mover")
            if ext_content is None:
                print("No se encontró ExtensionContent para colocar la firma")
    except Exception:
        print("Error moviendo la firma: <failed>")

    # produce bytes and log signature info for debugging
    try:
        ext_content_check = signed_root.find('.//{%s}ExtensionContent' % ext_ns)
        sig_in_ext = None
        if ext_content_check is not None:
            sig_in_ext = ext_content_check.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
        print("¿Firma en ExtensionContent después de mover?:", (sig_in_ext is not None))
    except Exception:
        print("ExtensionContent check failed")
    signed_xml = etree.tostring(signed_root, xml_declaration=True, encoding='UTF-8', pretty_print=True)
    try:
        print("XML firmado (primeros 2000 chars):", signed_xml[:2000].decode('utf-8'))
    except Exception:
        print("XML firmado: <failed to decode>")
    # Search for SignatureMethod Algorithm attribute
    try:
        import re
        m = re.search(r'<[^>]*SignatureMethod[^>]*Algorithm="([^"]*)"', signed_xml.decode('utf-8'))
        print("SignatureMethod Algorithm:", m.group(1) if m else "NOT FOUND")
    except Exception:
        print("SignatureMethod Algorithm: <search failed>")

    return signed_xml
