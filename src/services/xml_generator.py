from lxml import etree
from datetime import datetime
from decimal import Decimal
from src.schemas.schemas import ComprobanteCreate, LineaItem

NSMAP = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#"
}

def _mk(tag, text=None, ns='cbc', attrib=None):
    qname = etree.QName(NSMAP.get(ns), tag) if ns in NSMAP else etree.QName(NSMAP[None], tag)
    el = etree.Element(qname)
    if text is not None:
        el.text = text
    if attrib:
        for k, v in attrib.items():
            el.set(k, v)
    return el

def _mk_cac(tag):
    return etree.Element(etree.QName(NSMAP['cac'], tag))

def _mk_cbc(tag, text=None):
    el = etree.Element(etree.QName(NSMAP['cbc'], tag))
    if text is not None:
        el.text = text
    return el


def format_date_for_xml(fecha_str: str) -> str:
    # Expect dd/mm/YYYY or YYYY-MM-DD
    if '/' in fecha_str:
        d, m, y = fecha_str.split('/')
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return fecha_str


def build_invoice_xml(comprobante: ComprobanteCreate, emisor: dict) -> bytes:
    """Genera XML UBL 2.1 básico para factura (tipo 01).

    comprobante: ComprobanteCreate Pydantic model
    emisor: dict con keys: ruc, razon_social, nombre_comercial, direccion
    Returns bytes (UTF-8)
    """
    # Root Invoice
    invoice = etree.Element(etree.QName(NSMAP[None], 'Invoice'), nsmap=NSMAP)

    # UBLVersionID, CustomizationID
    invoice.append(_mk_cbc('UBLVersionID', '2.1'))
    invoice.append(_mk_cbc('CustomizationID', '2.0'))

    # ID = SERIE-NUMERO
    numero = f"{comprobante.numero or 1}"
    invoice.append(_mk_cbc('ID', f"{comprobante.serie}-{numero}"))

    # IssueDate
    issue_date = format_date_for_xml(comprobante.fecha_emision)
    invoice.append(_mk_cbc('IssueDate', issue_date))

    # IssueTime (optional)
    invoice.append(_mk_cbc('IssueTime', datetime.utcnow().strftime('%H:%M:%S')))

    # InvoiceTypeCode
    invoice.append(_mk_cbc('InvoiceTypeCode', comprobante.tipo_documento))

    # DocumentCurrencyCode
    invoice.append(_mk_cbc('DocumentCurrencyCode', comprobante.moneda or 'PEN'))

    # UBLExtensions placeholder for signature
    ubl_exts = etree.SubElement(invoice, etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    ext_content = etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))
    # ExtensionContent empty (signature goes here)

    # Supplier (AccountingSupplierParty)
    supplier = _mk_cac('AccountingSupplierParty')
    party = _mk_cac('Party')
    party_id = _mk_cbc('ID', emisor.get('ruc'))
    party_id.set('schemeID', '6')
    pid_wrapper = _mk_cac('PartyIdentification')
    pid_wrapper.append(party_id)
    party.append(pid_wrapper)

    party_name = _mk_cac('PartyName')
    party_name.append(_mk_cbc('Name', emisor.get('razon_social')))
    party.append(party_name)

    legal_entity = _mk_cac('PartyLegalEntity')
    legal_entity.append(_mk_cbc('RegistrationName', emisor.get('razon_social')))
    party.append(legal_entity)

    supplier.append(party)
    invoice.append(supplier)

    # Customer (AccountingCustomerParty) - minimal, using datos del comprobante if present
    customer = _mk_cac('AccountingCustomerParty')
    cparty = _mk_cac('Party')
    # For MVP, set dummy customer if not provided
    cust_id_val = getattr(comprobante, 'cliente_ruc', None) or '00000000'
    cparty_id_wrapper = _mk_cac('PartyIdentification')
    cparty_id = _mk_cbc('ID', cust_id_val)
    cparty_id.set('schemeID', '6')
    cparty_id_wrapper.append(cparty_id)
    cparty.append(cparty_id_wrapper)
    ccustomer_legal = _mk_cac('PartyLegalEntity')
    ccustomer_legal.append(_mk_cbc('RegistrationName', getattr(comprobante, 'cliente_nombre', 'CLIENTE')))
    cparty.append(ccustomer_legal)
    customer.append(cparty)
    invoice.append(customer)

    # TaxTotal
    total_amount = sum((i.cantidad * i.precio_unitario) for i in comprobante.items) if comprobante.items else Decimal('0.00')
    tax_total = _mk_cac('TaxTotal')
    tax_total.append(_mk_cbc('TaxAmount', f"{total_amount:.2f}"))
    invoice.append(tax_total)

    # LegalMonetaryTotal
    monetary = _mk_cac('LegalMonetaryTotal')
    line_ext = _mk_cbc('LineExtensionAmount', f"{total_amount:.2f}")
    monetary.append(line_ext)
    monetary.append(_mk_cbc('TaxInclusiveAmount', f"{total_amount:.2f}"))
    monetary.append(_mk_cbc('PayableAmount', f"{total_amount:.2f}"))
    invoice.append(monetary)

    # InvoiceLines
    for idx, item in enumerate(comprobante.items, start=1):
        line = _mk_cac('InvoiceLine')
        line.append(_mk_cbc('ID', str(idx)))
        qty = _mk_cbc('InvoicedQuantity', f"{item.cantidad}")
        qty.set('unitCode', item.unidad or 'NIU')
        line.append(qty)
        line.append(_mk_cbc('LineExtensionAmount', f"{item.monto_linea if hasattr(item, 'monto_linea') else (item.cantidad * item.precio_unitario):.2f}"))
        # Item
        item_el = _mk_cac('Item')
        item_el.append(_mk_cbc('Description', item.descripcion))
        line.append(item_el)
        # Price
        price = _mk_cac('Price')
        price.append(_mk_cbc('PriceAmount', f"{item.precio_unitario:.2f}"))
        line.append(price)
        invoice.append(line)

    xml_bytes = etree.tostring(invoice, xml_declaration=True, encoding='UTF-8', pretty_print=True)
    return xml_bytes


def validate_xml_against_xsd(xml_bytes: bytes, xsd_path: str) -> tuple[bool, str]:
    """Validate xml bytes against an XSD file. Returns (is_valid, message)"""
    xml_doc = etree.fromstring(xml_bytes)
    with open(xsd_path, 'rb') as f:
        xsd_doc = etree.parse(f)
    schema = etree.XMLSchema(xsd_doc)
    is_valid = schema.validate(xml_doc)
    if is_valid:
        return True, 'OK'
    else:
        # collect errors
        errors = '\n'.join([str(e) for e in schema.error_log])
        return False, errors
