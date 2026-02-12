"""
Generador de XML UBL 2.1 para Comprobantes Electrónicos - SUNAT Perú
Compatible con producción SUNAT.

Soporta:
- Factura (01)
- Boleta de Venta (03)
- Nota de Crédito (07)
- Nota de Débito (08)

Cumple con:
- UBL 2.1 / Customization 2.0
- Estructura completa: TaxTotal, TaxSubtotal, TaxCategory, TaxScheme
- currencyID en todos los montos
- Datos reales del cliente
- IssueTime en hora Perú (UTC-5)
- Placeholder para firma digital (UBLExtensions)
"""

from lxml import etree
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# Zona horaria Perú
PERU_TZ = timezone(timedelta(hours=-5))

# Namespaces UBL 2.1
NSMAP = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
}

NSMAP_NC = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
}

NSMAP_ND = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
}

# Códigos de tipo de afectación IGV (catálogo 07)
TIPO_IGV = {
    '10': {'nombre': 'Gravado - Operación Onerosa', 'tributo': '1000', 'codigo_tipo': 'VAT'},
    '20': {'nombre': 'Exonerado - Operación Onerosa', 'tributo': '9997', 'codigo_tipo': 'EXO'},
    '30': {'nombre': 'Inafecto - Operación Onerosa', 'tributo': '9998', 'codigo_tipo': 'FRE'},
    '40': {'nombre': 'Exportación', 'tributo': '9995', 'codigo_tipo': 'EXP'},
}

# Catálogo tributos SUNAT
TRIBUTOS = {
    '1000': {'id': '1000', 'nombre': 'IGV', 'codigo': 'VAT'},
    '9997': {'id': '9997', 'nombre': 'EXO', 'codigo': 'VAT'},
    '9998': {'id': '9998', 'nombre': 'INA', 'codigo': 'FRE'},
    '9995': {'id': '9995', 'nombre': 'EXP', 'codigo': 'FRE'},
}

# Tipo documento identidad (catálogo 06)
TIPO_DOC_IDENTIDAD = {
    '0': '0',  # Sin documento
    '1': '1',  # DNI
    '4': '4',  # Carnet de extranjería
    '6': '6',  # RUC
    '7': '7',  # Pasaporte
    'A': 'A',  # Cédula diplomática
}


def _d(value) -> Decimal:
    """Convierte a Decimal con 2 decimales"""
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _cbc(tag, text=None, attrib=None):
    """Crea elemento cbc:Tag"""
    el = etree.Element(etree.QName(NSMAP['cbc'], tag))
    if text is not None:
        el.text = str(text)
    if attrib:
        for k, v in attrib.items():
            el.set(k, str(v))
    return el


def _cac(tag):
    """Crea elemento cac:Tag"""
    return etree.Element(etree.QName(NSMAP['cac'], tag))


def _amount(tag, value, currency='PEN'):
    """Crea elemento monto con currencyID"""
    el = _cbc(tag, f"{_d(value):.2f}")
    el.set('currencyID', currency)
    return el


def _format_date(fecha) -> str:
    """Formatea fecha a YYYY-MM-DD"""
    if isinstance(fecha, str):
        if '/' in fecha:
            d, m, y = fecha.split('/')
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        return fecha
    if isinstance(fecha, datetime):
        return fecha.strftime('%Y-%m-%d')
    if hasattr(fecha, 'strftime'):
        return fecha.strftime('%Y-%m-%d')
    return str(fecha)


def _format_time(fecha) -> str:
    """Formatea hora a HH:MM:SS"""
    if isinstance(fecha, datetime):
        return fecha.strftime('%H:%M:%S')
    # Si es string con hora
    if isinstance(fecha, str) and ':' in fecha:
        return fecha
    # Default: hora Perú actual
    return datetime.now(tz=PERU_TZ).strftime('%H:%M:%S')


def build_invoice_xml(comprobante, emisor: dict) -> bytes:
    """
    Genera XML UBL 2.1 completo para comprobante electrónico.

    Args:
        comprobante: ComprobanteCreate (Pydantic) o objeto con atributos equivalentes
        emisor: dict con keys: ruc, razon_social, nombre_comercial, direccion,
                ubigeo, departamento, provincia, distrito

    Returns:
        bytes del XML (UTF-8)
    """
    tipo_doc = getattr(comprobante, 'tipo_documento', '01')

    if tipo_doc == '07':
        return _build_credit_note_xml(comprobante, emisor)
    elif tipo_doc == '08':
        return _build_debit_note_xml(comprobante, emisor)

    # Factura (01) o Boleta (03)
    return _build_factura_boleta_xml(comprobante, emisor)


def _build_factura_boleta_xml(comprobante, emisor: dict) -> bytes:
    """Genera XML para Factura o Boleta"""
    tipo_doc = getattr(comprobante, 'tipo_documento', '01')
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'F001')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])

    # Root
    invoice = etree.Element(etree.QName(NSMAP[None], 'Invoice'), nsmap=NSMAP)

    # === UBLExtensions (placeholder para firma) ===
    ubl_exts = etree.SubElement(invoice, etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))

    # === Cabecera ===
    invoice.append(_cbc('UBLVersionID', '2.1'))
    invoice.append(_cbc('CustomizationID', '2.0'))
    invoice.append(_cbc('ID', f"{serie}-{numero}"))
    invoice.append(_cbc('IssueDate', _format_date(fecha_emision)))
    invoice.append(_cbc('IssueTime', _format_time(fecha_emision)))

    # InvoiceTypeCode con listID
    type_code = _cbc('InvoiceTypeCode', tipo_doc)
    type_code.set('listID', '0101')  # Catálogo 51: Venta interna
    invoice.append(type_code)

    invoice.append(_cbc('DocumentCurrencyCode', moneda))

    # === Signature reference ===
    sig = _cac('Signature')
    sig.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party = _cac('SignatoryParty')
    sig_party_id = _cac('PartyIdentification')
    sig_party_id.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party.append(sig_party_id)
    sig_party_name = _cac('PartyName')
    sig_party_name.append(_cbc('Name', emisor.get('razon_social', '')))
    sig_party.append(sig_party_name)
    sig.append(sig_party)
    dig_sig = _cac('DigitalSignatureAttachment')
    ext_ref = _cac('ExternalReference')
    ext_ref.append(_cbc('URI', f"#{emisor.get('ruc', '')}-SIGN"))
    dig_sig.append(ext_ref)
    sig.append(dig_sig)
    invoice.append(sig)

    # === Emisor (AccountingSupplierParty) ===
    invoice.append(_build_supplier(emisor))

    # === Cliente (AccountingCustomerParty) ===
    invoice.append(_build_customer(comprobante))

    # === Calcular totales por tipo de IGV ===
    totales = _calcular_totales(items, moneda)

    # === TaxTotal ===
    invoice.append(_build_tax_total(totales, moneda))

    # === LegalMonetaryTotal ===
    invoice.append(_build_monetary_total(totales, moneda))

    # === InvoiceLines ===
    for idx, item in enumerate(items, start=1):
        invoice.append(_build_invoice_line(idx, item, moneda))

    xml_bytes = etree.tostring(invoice, xml_declaration=True, encoding='UTF-8', pretty_print=True)
    return xml_bytes


def _build_credit_note_xml(comprobante, emisor: dict) -> bytes:
    """Genera XML para Nota de Crédito"""
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'FC01')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])
    motivo = getattr(comprobante, 'motivo_nota', '01')
    doc_ref_tipo = getattr(comprobante, 'doc_referencia_tipo', '01')
    doc_ref_numero = getattr(comprobante, 'doc_referencia_numero', '')

    root = etree.Element(etree.QName(NSMAP_NC[None], 'CreditNote'), nsmap=NSMAP_NC)

    # UBLExtensions
    ubl_exts = etree.SubElement(root, etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))

    root.append(_cbc('UBLVersionID', '2.1'))
    root.append(_cbc('CustomizationID', '2.0'))
    root.append(_cbc('ID', f"{serie}-{numero}"))
    root.append(_cbc('IssueDate', _format_date(fecha_emision)))
    root.append(_cbc('IssueTime', _format_time(fecha_emision)))
    root.append(_cbc('DocumentCurrencyCode', moneda))

    # DiscrepancyResponse (motivo de la NC)
    discrepancy = _cac('DiscrepancyResponse')
    discrepancy.append(_cbc('ReferenceID', doc_ref_numero))
    discrepancy.append(_cbc('ResponseCode', motivo))
    discrepancy.append(_cbc('Description', _motivo_nc_descripcion(motivo)))
    root.append(discrepancy)

    # BillingReference (documento de referencia)
    billing_ref = _cac('BillingReference')
    invoice_doc_ref = _cac('InvoiceDocumentReference')
    invoice_doc_ref.append(_cbc('ID', doc_ref_numero))
    doc_type = _cbc('DocumentTypeCode', doc_ref_tipo)
    doc_type.set('listName', 'Tipo de Documento')
    doc_type.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01')
    invoice_doc_ref.append(doc_type)
    billing_ref.append(invoice_doc_ref)
    root.append(billing_ref)

    # Signature
    sig = _cac('Signature')
    sig.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party = _cac('SignatoryParty')
    sig_pid = _cac('PartyIdentification')
    sig_pid.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party.append(sig_pid)
    sig_pn = _cac('PartyName')
    sig_pn.append(_cbc('Name', emisor.get('razon_social', '')))
    sig_party.append(sig_pn)
    sig.append(sig_party)
    dsa = _cac('DigitalSignatureAttachment')
    er = _cac('ExternalReference')
    er.append(_cbc('URI', f"#{emisor.get('ruc', '')}-SIGN"))
    dsa.append(er)
    sig.append(dsa)
    root.append(sig)

    # Supplier & Customer
    root.append(_build_supplier(emisor))
    root.append(_build_customer(comprobante))

    # Totales
    totales = _calcular_totales(items, moneda)
    root.append(_build_tax_total(totales, moneda))
    root.append(_build_monetary_total(totales, moneda, tag='RequestedMonetaryTotal'))

    # CreditNoteLines
    for idx, item in enumerate(items, start=1):
        root.append(_build_invoice_line(idx, item, moneda, line_tag='CreditNoteLine',
                                        qty_tag='CreditedQuantity'))

    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True)


def _build_debit_note_xml(comprobante, emisor: dict) -> bytes:
    """Genera XML para Nota de Débito"""
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'FD01')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])
    motivo = getattr(comprobante, 'motivo_nota', '01')
    doc_ref_tipo = getattr(comprobante, 'doc_referencia_tipo', '01')
    doc_ref_numero = getattr(comprobante, 'doc_referencia_numero', '')

    root = etree.Element(etree.QName(NSMAP_ND[None], 'DebitNote'), nsmap=NSMAP_ND)

    # UBLExtensions
    ubl_exts = etree.SubElement(root, etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))

    root.append(_cbc('UBLVersionID', '2.1'))
    root.append(_cbc('CustomizationID', '2.0'))
    root.append(_cbc('ID', f"{serie}-{numero}"))
    root.append(_cbc('IssueDate', _format_date(fecha_emision)))
    root.append(_cbc('IssueTime', _format_time(fecha_emision)))
    root.append(_cbc('DocumentCurrencyCode', moneda))

    # DiscrepancyResponse
    discrepancy = _cac('DiscrepancyResponse')
    discrepancy.append(_cbc('ReferenceID', doc_ref_numero))
    discrepancy.append(_cbc('ResponseCode', motivo))
    discrepancy.append(_cbc('Description', _motivo_nd_descripcion(motivo)))
    root.append(discrepancy)

    # BillingReference
    billing_ref = _cac('BillingReference')
    invoice_doc_ref = _cac('InvoiceDocumentReference')
    invoice_doc_ref.append(_cbc('ID', doc_ref_numero))
    doc_type = _cbc('DocumentTypeCode', doc_ref_tipo)
    invoice_doc_ref.append(doc_type)
    billing_ref.append(invoice_doc_ref)
    root.append(billing_ref)

    # Signature
    sig = _cac('Signature')
    sig.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party = _cac('SignatoryParty')
    sig_pid = _cac('PartyIdentification')
    sig_pid.append(_cbc('ID', emisor.get('ruc', '')))
    sig_party.append(sig_pid)
    sig_pn = _cac('PartyName')
    sig_pn.append(_cbc('Name', emisor.get('razon_social', '')))
    sig_party.append(sig_pn)
    sig.append(sig_party)
    dsa = _cac('DigitalSignatureAttachment')
    er = _cac('ExternalReference')
    er.append(_cbc('URI', f"#{emisor.get('ruc', '')}-SIGN"))
    dsa.append(er)
    sig.append(dsa)
    root.append(sig)

    # Supplier & Customer
    root.append(_build_supplier(emisor))
    root.append(_build_customer(comprobante))

    # Totales
    totales = _calcular_totales(items, moneda)
    root.append(_build_tax_total(totales, moneda))
    root.append(_build_monetary_total(totales, moneda, tag='RequestedMonetaryTotal'))

    # DebitNoteLines
    for idx, item in enumerate(items, start=1):
        root.append(_build_invoice_line(idx, item, moneda, line_tag='DebitNoteLine',
                                        qty_tag='DebitedQuantity'))

    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True)


# =============================================
# BLOQUES REUTILIZABLES
# =============================================

def _build_supplier(emisor: dict):
    """Construye AccountingSupplierParty"""
    supplier = _cac('AccountingSupplierParty')
    party = _cac('Party')

    # PartyIdentification
    pid = _cac('PartyIdentification')
    pid_id = _cbc('ID', emisor.get('ruc', ''))
    pid_id.set('schemeID', '6')  # RUC
    pid_id.set('schemeName', 'Documento de Identidad')
    pid_id.set('schemeAgencyName', 'PE:SUNAT')
    pid_id.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')
    pid.append(pid_id)
    party.append(pid)

    # PartyName
    pn = _cac('PartyName')
    pn.append(_cbc('Name', emisor.get('nombre_comercial', '') or emisor.get('razon_social', '')))
    party.append(pn)

    # PartyLegalEntity
    ple = _cac('PartyLegalEntity')
    ple.append(_cbc('RegistrationName', emisor.get('razon_social', '')))

    # Dirección del emisor
    addr = _cac('RegistrationAddress')
    addr.append(_cbc('ID', emisor.get('ubigeo', '160101')))
    addr.append(_cbc('AddressTypeCode', '0000'))

    # Orden UBL requerido por SUNAT:
    addr.append(_cbc('CitySubdivisionName', '-'))
    addr.append(_cbc('CityName', emisor.get('provincia', '')))
    addr.append(_cbc('CountrySubentity', emisor.get('departamento', '')))
    addr.append(_cbc('District', emisor.get('distrito', '')))

    addr_line = _cac('AddressLine')
    addr_line.append(_cbc('Line', emisor.get('direccion', '')))
    addr.append(addr_line)

    country = _cac('Country')
    country.append(_cbc('IdentificationCode', 'PE'))
    addr.append(country)

    ple.append(addr)
    party.append(ple)
    supplier.append(party)

    return supplier


def _build_customer(comprobante):
    """Construye AccountingCustomerParty desde datos del comprobante"""
    # Intentar obtener datos del cliente
    cliente_tipo_doc = (getattr(comprobante, 'cliente_tipo_doc', None) or
                        getattr(comprobante, 'cliente_tipo_documento', None) or '6')
    cliente_num_doc = (getattr(comprobante, 'cliente_numero_doc', None) or
                       getattr(comprobante, 'cliente_numero_documento', None) or
                       getattr(comprobante, 'cliente_ruc', None) or '')
    cliente_nombre = (getattr(comprobante, 'cliente_razon_social', None) or
                      getattr(comprobante, 'cliente_nombre', None) or '')
    cliente_direccion = (getattr(comprobante, 'cliente_direccion', None) or '')

    customer = _cac('AccountingCustomerParty')
    party = _cac('Party')

    # PartyIdentification
    pid = _cac('PartyIdentification')
    pid_id = _cbc('ID', cliente_num_doc)
    pid_id.set('schemeID', str(cliente_tipo_doc))
    pid_id.set('schemeName', 'Documento de Identidad')
    pid_id.set('schemeAgencyName', 'PE:SUNAT')
    pid_id.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')
    pid.append(pid_id)
    party.append(pid)

    # PartyLegalEntity
    ple = _cac('PartyLegalEntity')
    ple.append(_cbc('RegistrationName', cliente_nombre))

    if cliente_direccion:
        addr = _cac('RegistrationAddress')
        addr_line = _cac('AddressLine')
        addr_line.append(_cbc('Line', cliente_direccion))
        addr.append(addr_line)
        ple.append(addr)

    party.append(ple)
    customer.append(party)

    return customer


def _calcular_totales(items, moneda='PEN') -> dict:
    """
    Calcula totales agrupados por tipo de afectación IGV.

    Returns:
        {
            'gravado': Decimal,
            'exonerado': Decimal,
            'inafecto': Decimal,
            'exportacion': Decimal,
            'igv_total': Decimal,
            'subtotal': Decimal,
            'total': Decimal,
        }
    """
    gravado = Decimal('0.00')
    exonerado = Decimal('0.00')
    inafecto = Decimal('0.00')
    exportacion = Decimal('0.00')
    igv_total = Decimal('0.00')

    for item in items:
        cantidad = _d(getattr(item, 'cantidad', 1))
        precio = _d(getattr(item, 'precio_unitario', 0))
        tipo_igv = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')
        monto_linea = (cantidad * precio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if tipo_igv == '10':  # Gravado
            gravado += monto_linea
            igv_item = (monto_linea * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            igv_total += igv_item
        elif tipo_igv == '20':  # Exonerado
            exonerado += monto_linea
        elif tipo_igv == '30':  # Inafecto
            inafecto += monto_linea
        elif tipo_igv == '40':  # Exportación
            exportacion += monto_linea

    subtotal = gravado + exonerado + inafecto + exportacion
    total = subtotal + igv_total

    return {
        'gravado': gravado,
        'exonerado': exonerado,
        'inafecto': inafecto,
        'exportacion': exportacion,
        'igv_total': igv_total,
        'subtotal': subtotal,
        'total': total,
    }


def _build_tax_total(totales: dict, moneda='PEN'):
    """Construye TaxTotal con TaxSubtotal por cada tipo de tributo"""
    tax_total = _cac('TaxTotal')
    tax_total.append(_amount('TaxAmount', totales['igv_total'], moneda))

    # IGV (si hay gravado)
    if totales['gravado'] > 0:
        tax_total.append(_build_tax_subtotal(totales['gravado'], totales['igv_total'],
                                              '1000', 'IGV', 'VAT', moneda))

    # Exonerado
    if totales['exonerado'] > 0:
        tax_total.append(_build_tax_subtotal(totales['exonerado'], Decimal('0.00'),
                                              '9997', 'EXO', 'VAT', moneda))

    # Inafecto
    if totales['inafecto'] > 0:
        tax_total.append(_build_tax_subtotal(totales['inafecto'], Decimal('0.00'),
                                              '9998', 'INA', 'FRE', moneda))

    # Exportación
    if totales['exportacion'] > 0:
        tax_total.append(_build_tax_subtotal(totales['exportacion'], Decimal('0.00'),
                                              '9995', 'EXP', 'FRE', moneda))

    return tax_total


def _build_tax_subtotal(base, tax_amount, tributo_id, tributo_nombre, tributo_code, moneda='PEN'):
    """Construye un TaxSubtotal individual"""
    ts = _cac('TaxSubtotal')
    ts.append(_amount('TaxableAmount', base, moneda))
    ts.append(_amount('TaxAmount', tax_amount, moneda))

    tc = _cac('TaxCategory')
    tc.append(_cbc('ID', tributo_id))

    # Porcentaje
    if tributo_id == '1000':
        tc.append(_cbc('Percent', '18.00'))
    else:
        tc.append(_cbc('Percent', '0.00'))

    tax_scheme = _cac('TaxScheme')
    tax_scheme.append(_cbc('ID', tributo_id))
    tax_scheme.append(_cbc('Name', tributo_nombre))
    tax_scheme.append(_cbc('TaxTypeCode', tributo_code))
    tc.append(tax_scheme)

    ts.append(tc)
    return ts


def _build_monetary_total(totales: dict, moneda='PEN', tag='LegalMonetaryTotal'):
    """Construye LegalMonetaryTotal o RequestedMonetaryTotal"""
    monetary = _cac(tag)
    monetary.append(_amount('LineExtensionAmount', totales['subtotal'], moneda))
    monetary.append(_amount('TaxInclusiveAmount', totales['total'], moneda))
    monetary.append(_amount('PayableAmount', totales['total'], moneda))
    return monetary


def _build_invoice_line(idx, item, moneda='PEN', line_tag='InvoiceLine',
                        qty_tag='InvoicedQuantity'):
    """Construye una línea de detalle del comprobante"""
    cantidad = _d(getattr(item, 'cantidad', 1))
    precio = _d(getattr(item, 'precio_unitario', 0))
    descripcion = getattr(item, 'descripcion', '')
    unidad = getattr(item, 'unidad', None) or getattr(item, 'unidad_medida', 'NIU') or 'NIU'
    tipo_igv = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')

    monto_linea = (cantidad * precio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Calcular IGV del item
    if tipo_igv == '10':  # Gravado
        igv_item = (monto_linea * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        precio_con_igv = precio + (precio * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        igv_item = Decimal('0.00')
        precio_con_igv = precio

    line = _cac(line_tag)
    line.append(_cbc('ID', str(idx)))

    # Cantidad
    qty = _cbc(qty_tag, f"{cantidad:.2f}")
    qty.set('unitCode', unidad)
    qty.set('unitCodeListID', 'UN/ECE rec 20')
    qty.set('unitCodeListAgencyName', 'United Nations Economic Commission for Europe')
    line.append(qty)

    # LineExtensionAmount (valor venta sin IGV)
    line.append(_amount('LineExtensionAmount', monto_linea, moneda))

    # PricingReference (precio con IGV para SUNAT)
    pricing = _cac('PricingReference')
    alt_price = _cac('AlternativeConditionPrice')
    alt_price.append(_amount('PriceAmount', precio_con_igv, moneda))
    price_type = _cbc('PriceTypeCode', '01')  # Precio unitario con IGV
    price_type.set('listName', 'Tipo de Precio')
    price_type.set('listAgencyName', 'PE:SUNAT')
    price_type.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo16')
    alt_price.append(price_type)
    pricing.append(alt_price)
    line.append(pricing)

    # TaxTotal del item
    item_tax = _cac('TaxTotal')
    item_tax.append(_amount('TaxAmount', igv_item, moneda))

    item_ts = _cac('TaxSubtotal')
    item_ts.append(_amount('TaxableAmount', monto_linea, moneda))
    item_ts.append(_amount('TaxAmount', igv_item, moneda))

    item_tc = _cac('TaxCategory')
    item_tc.append(_cbc('ID', tipo_igv))

    # Porcentaje
    if tipo_igv == '10':
        item_tc.append(_cbc('Percent', '18.00'))
    else:
        item_tc.append(_cbc('Percent', '0.00'))

    # TaxExemptionReasonCode (catálogo 07)
    exemption = _cbc('TaxExemptionReasonCode', tipo_igv)
    exemption.set('listAgencyName', 'PE:SUNAT')
    exemption.set('listName', 'Tipo de Afectación del IGV')
    exemption.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo07')
    item_tc.append(exemption)

    # TaxScheme del item
    igv_info = TIPO_IGV.get(tipo_igv, TIPO_IGV['10'])
    tributo = TRIBUTOS.get(igv_info['tributo'], TRIBUTOS['1000'])
    item_scheme = _cac('TaxScheme')
    item_scheme.append(_cbc('ID', tributo['id']))
    item_scheme.append(_cbc('Name', tributo['nombre']))
    item_scheme.append(_cbc('TaxTypeCode', tributo['codigo']))
    item_tc.append(item_scheme)

    item_ts.append(item_tc)
    item_tax.append(item_ts)
    line.append(item_tax)

    # Item
    item_el = _cac('Item')
    item_el.append(_cbc('Description', descripcion))
    line.append(item_el)

    # Price (precio sin IGV)
    price_el = _cac('Price')
    price_el.append(_amount('PriceAmount', precio, moneda))
    line.append(price_el)

    return line


# =============================================
# CATÁLOGOS DE MOTIVOS
# =============================================

def _motivo_nc_descripcion(codigo):
    """Catálogo 09: Motivos de Nota de Crédito"""
    motivos = {
        '01': 'Anulación de la operación',
        '02': 'Anulación por error en el RUC',
        '03': 'Corrección por error en la descripción',
        '04': 'Descuento global',
        '05': 'Descuento por ítem',
        '06': 'Devolución total',
        '07': 'Devolución por ítem',
        '08': 'Bonificación',
        '09': 'Disminución en el valor',
        '10': 'Otros conceptos',
        '11': 'Ajuste de operaciones de exportación',
        '12': 'Ajuste afectos al IVAP',
        '13': 'Ajuste – Loss of natural disasters',
    }
    return motivos.get(codigo, 'Otros conceptos')


def _motivo_nd_descripcion(codigo):
    """Catálogo 10: Motivos de Nota de Débito"""
    motivos = {
        '01': 'Intereses por mora',
        '02': 'Aumento en el valor',
        '03': 'Penalidades/otros conceptos',
        '10': 'Ajuste de operaciones de exportación',
        '11': 'Ajuste afectos al IVAP',
    }
    return motivos.get(codigo, 'Otros conceptos')


# =============================================
# VALIDACIÓN BÁSICA
# =============================================

def validate_xml_against_xsd(xml_bytes: bytes, xsd_path: str) -> tuple:
    """Valida XML contra un esquema XSD"""
    try:
        xml_doc = etree.fromstring(xml_bytes)
        with open(xsd_path, 'rb') as f:
            xsd_doc = etree.parse(f)
        schema = etree.XMLSchema(xsd_doc)
        is_valid = schema.validate(xml_doc)
        if is_valid:
            return True, 'OK'
        errors = '\n'.join([str(e) for e in schema.error_log])
        return False, errors
    except Exception as e:
        return False, str(e)