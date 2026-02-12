"""
Generador de XML UBL 2.1 para Comprobantes Electrónicos - SUNAT Perú
Compatible con producción SUNAT.

Soporta: Factura (01), Boleta (03), Nota de Crédito (07), Nota de Débito (08)

Incluye:
- PaymentTerms (Contado/Crédito) - obligatorio RS 000193-2020/SUNAT
- InvoiceTypeCode con atributos catálogo 01 y 51
- Elementos de dirección condicionales (no emite vacíos)
- Logging de diagnóstico para trazabilidad
"""

from lxml import etree
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))

NSMAP = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
}

NSMAP_NC = dict(NSMAP)
NSMAP_NC[None] = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"

NSMAP_ND = dict(NSMAP)
NSMAP_ND[None] = "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2"

TIPO_IGV = {
    '10': {'tributo': '1000'},
    '20': {'tributo': '9997'},
    '30': {'tributo': '9998'},
    '40': {'tributo': '9995'},
}

TRIBUTOS = {
    '1000': {'id': '1000', 'nombre': 'IGV', 'codigo': 'VAT'},
    '9997': {'id': '9997', 'nombre': 'EXO', 'codigo': 'VAT'},
    '9998': {'id': '9998', 'nombre': 'INA', 'codigo': 'FRE'},
    '9995': {'id': '9995', 'nombre': 'EXP', 'codigo': 'FRE'},
}


def _d(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _cbc(tag, text=None):
    el = etree.Element(etree.QName(NSMAP['cbc'], tag))
    if text is not None:
        el.text = str(text)
    return el


def _cac(tag):
    return etree.Element(etree.QName(NSMAP['cac'], tag))


def _amount(tag, value, currency='PEN'):
    el = _cbc(tag, f"{_d(value):.2f}")
    el.set('currencyID', currency)
    return el


def _format_date(fecha) -> str:
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
    if isinstance(fecha, datetime):
        return fecha.strftime('%H:%M:%S')
    if isinstance(fecha, str) and ':' in fecha:
        return fecha
    return datetime.now(tz=PERU_TZ).strftime('%H:%M:%S')


def _build_ubl_extensions():
    ubl_exts = etree.Element(etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))
    return ubl_exts


def _build_signature_ref(emisor: dict):
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
    return sig


# =============================================
# FACTURA / BOLETA
# =============================================

def build_invoice_xml(comprobante, emisor: dict) -> bytes:
    tipo_doc = getattr(comprobante, 'tipo_documento', '01')
    logger.info(f"[XML_GEN] build_invoice_xml tipo={tipo_doc}")
    print(f"[XML_GEN] build_invoice_xml tipo={tipo_doc}")

    if tipo_doc == '07':
        return _build_credit_note_xml(comprobante, emisor)
    elif tipo_doc == '08':
        return _build_debit_note_xml(comprobante, emisor)
    return _build_factura_boleta_xml(comprobante, emisor)


def _build_factura_boleta_xml(comprobante, emisor: dict) -> bytes:
    tipo_doc = getattr(comprobante, 'tipo_documento', '01')
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'F001')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])

    logger.info(f"[XML_GEN] Factura/Boleta {serie}-{numero}, moneda={moneda}, items={len(items)}")
    print(f"[XML_GEN] Factura/Boleta {serie}-{numero}, moneda={moneda}, items={len(items)}")

    invoice = etree.Element(etree.QName(NSMAP[None], 'Invoice'), nsmap=NSMAP)

    # 1. UBLExtensions
    invoice.append(_build_ubl_extensions())
    logger.info("[XML_GEN] ✓ UBLExtensions")

    # 2. Cabecera
    invoice.append(_cbc('UBLVersionID', '2.1'))
    invoice.append(_cbc('CustomizationID', '2.0'))
    invoice.append(_cbc('ID', f"{serie}-{numero}"))
    invoice.append(_cbc('IssueDate', _format_date(fecha_emision)))
    invoice.append(_cbc('IssueTime', _format_time(fecha_emision)))

    # 3. InvoiceTypeCode - Catálogo 01 + Catálogo 51
    type_code = _cbc('InvoiceTypeCode', tipo_doc)
    type_code.set('listID', '0101')  # Catálogo 51: Venta interna
    type_code.set('listAgencyName', 'PE:SUNAT')
    type_code.set('listName', 'Tipo de Documento')
    type_code.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01')
    type_code.set('name', 'Tipo de Operacion')
    type_code.set('listSchemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo51')
    invoice.append(type_code)
    logger.info(f"[XML_GEN] ✓ InvoiceTypeCode={tipo_doc} listID=0101")

    invoice.append(_cbc('DocumentCurrencyCode', moneda))

    # 4. Signature reference
    invoice.append(_build_signature_ref(emisor))
    logger.info("[XML_GEN] ✓ Signature reference")

    # 5. Supplier
    invoice.append(_build_supplier(emisor))
    logger.info("[XML_GEN] ✓ AccountingSupplierParty")

    # 6. Customer
    invoice.append(_build_customer(comprobante))
    logger.info("[XML_GEN] ✓ AccountingCustomerParty")

    # 7. PaymentTerms - OBLIGATORIO desde RS 000193-2020/SUNAT
    #    Sin esto: error 3244 "tipo de transaccion"
    forma_pago = getattr(comprobante, 'forma_pago', 'Contado') or 'Contado'
    invoice.append(_build_payment_terms(comprobante, moneda, forma_pago))
    logger.info(f"[XML_GEN] ✓ PaymentTerms forma_pago={forma_pago}")

    # 8. Totales
    totales = _calcular_totales(items, moneda)
    invoice.append(_build_tax_total(totales, moneda))
    logger.info(f"[XML_GEN] ✓ TaxTotal igv={totales['igv_total']}")

    invoice.append(_build_monetary_total(totales, moneda))
    logger.info(f"[XML_GEN] ✓ LegalMonetaryTotal total={totales['total']}")

    # 9. Lines
    for idx, item in enumerate(items, start=1):
        invoice.append(_build_invoice_line(idx, item, moneda))
    logger.info(f"[XML_GEN] ✓ {len(items)} InvoiceLine(s)")

    xml_bytes = etree.tostring(invoice, xml_declaration=True, encoding='UTF-8')
    logger.info(f"[XML_GEN] XML generado OK ({len(xml_bytes)} bytes)")
    print(f"[XML_GEN] XML generado OK ({len(xml_bytes)} bytes)")
    return xml_bytes


# =============================================
# PAYMENT TERMS (Forma de Pago)
# Obligatorio desde RS 000193-2020/SUNAT
# =============================================

def _build_payment_terms(comprobante, moneda='PEN', forma_pago='Contado'):
    """Construye PaymentTerms.

    Para Contado:
        <cac:PaymentTerms>
            <cbc:ID>FormaPago</cbc:ID>
            <cbc:PaymentMeansID>Contado</cbc:PaymentMeansID>
        </cac:PaymentTerms>

    Para Crédito:
        <cac:PaymentTerms>
            <cbc:ID>FormaPago</cbc:ID>
            <cbc:PaymentMeansID>Credito</cbc:PaymentMeansID>
            <cbc:Amount currencyID="PEN">total</cbc:Amount>
        </cac:PaymentTerms>
        + cuotas adicionales
    """
    pt = _cac('PaymentTerms')
    pt.append(_cbc('ID', 'FormaPago'))
    pt.append(_cbc('PaymentMeansID', forma_pago))

    if forma_pago == 'Credito':
        # Para crédito, agregar el monto total pendiente
        totales = _calcular_totales(getattr(comprobante, 'items', []), moneda)
        pt.append(_amount('Amount', totales['total'], moneda))

    return pt


# =============================================
# NOTA DE CRÉDITO
# =============================================

def _build_credit_note_xml(comprobante, emisor: dict) -> bytes:
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'FC01')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])
    motivo = getattr(comprobante, 'motivo_nota', '01')
    doc_ref_tipo = getattr(comprobante, 'doc_referencia_tipo', '01')
    doc_ref_numero = getattr(comprobante, 'doc_referencia_numero', '')

    logger.info(f"[XML_GEN] NC {serie}-{numero} ref={doc_ref_numero} motivo={motivo}")

    root = etree.Element(etree.QName(NSMAP_NC[None], 'CreditNote'), nsmap=NSMAP_NC)

    root.append(_build_ubl_extensions())
    root.append(_cbc('UBLVersionID', '2.1'))
    root.append(_cbc('CustomizationID', '2.0'))
    root.append(_cbc('ID', f"{serie}-{numero}"))
    root.append(_cbc('IssueDate', _format_date(fecha_emision)))
    root.append(_cbc('IssueTime', _format_time(fecha_emision)))
    root.append(_cbc('DocumentCurrencyCode', moneda))

    discrepancy = _cac('DiscrepancyResponse')
    discrepancy.append(_cbc('ReferenceID', doc_ref_numero))
    discrepancy.append(_cbc('ResponseCode', motivo))
    discrepancy.append(_cbc('Description', _motivo_nc_descripcion(motivo)))
    root.append(discrepancy)

    billing_ref = _cac('BillingReference')
    invoice_doc_ref = _cac('InvoiceDocumentReference')
    invoice_doc_ref.append(_cbc('ID', doc_ref_numero))
    doc_type = _cbc('DocumentTypeCode', doc_ref_tipo)
    doc_type.set('listName', 'Tipo de Documento')
    doc_type.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01')
    invoice_doc_ref.append(doc_type)
    billing_ref.append(invoice_doc_ref)
    root.append(billing_ref)

    root.append(_build_signature_ref(emisor))
    root.append(_build_supplier(emisor))
    root.append(_build_customer(comprobante))

    totales = _calcular_totales(items, moneda)
    root.append(_build_tax_total(totales, moneda))
    root.append(_build_monetary_total(totales, moneda, tag='RequestedMonetaryTotal'))

    for idx, item in enumerate(items, start=1):
        root.append(_build_invoice_line(idx, item, moneda, line_tag='CreditNoteLine',
                                        qty_tag='CreditedQuantity'))

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
    logger.info(f"[XML_GEN] NC XML generado OK ({len(xml_bytes)} bytes)")
    return xml_bytes


# =============================================
# NOTA DE DÉBITO
# =============================================

def _build_debit_note_xml(comprobante, emisor: dict) -> bytes:
    moneda = getattr(comprobante, 'moneda', 'PEN') or 'PEN'
    serie = getattr(comprobante, 'serie', 'FD01')
    numero = getattr(comprobante, 'numero', 1)
    fecha_emision = getattr(comprobante, 'fecha_emision', None)
    items = getattr(comprobante, 'items', [])
    motivo = getattr(comprobante, 'motivo_nota', '01')
    doc_ref_tipo = getattr(comprobante, 'doc_referencia_tipo', '01')
    doc_ref_numero = getattr(comprobante, 'doc_referencia_numero', '')

    logger.info(f"[XML_GEN] ND {serie}-{numero} ref={doc_ref_numero} motivo={motivo}")

    root = etree.Element(etree.QName(NSMAP_ND[None], 'DebitNote'), nsmap=NSMAP_ND)

    root.append(_build_ubl_extensions())
    root.append(_cbc('UBLVersionID', '2.1'))
    root.append(_cbc('CustomizationID', '2.0'))
    root.append(_cbc('ID', f"{serie}-{numero}"))
    root.append(_cbc('IssueDate', _format_date(fecha_emision)))
    root.append(_cbc('IssueTime', _format_time(fecha_emision)))
    root.append(_cbc('DocumentCurrencyCode', moneda))

    discrepancy = _cac('DiscrepancyResponse')
    discrepancy.append(_cbc('ReferenceID', doc_ref_numero))
    discrepancy.append(_cbc('ResponseCode', motivo))
    discrepancy.append(_cbc('Description', _motivo_nd_descripcion(motivo)))
    root.append(discrepancy)

    billing_ref = _cac('BillingReference')
    invoice_doc_ref = _cac('InvoiceDocumentReference')
    invoice_doc_ref.append(_cbc('ID', doc_ref_numero))
    doc_type = _cbc('DocumentTypeCode', doc_ref_tipo)
    invoice_doc_ref.append(doc_type)
    billing_ref.append(invoice_doc_ref)
    root.append(billing_ref)

    root.append(_build_signature_ref(emisor))
    root.append(_build_supplier(emisor))
    root.append(_build_customer(comprobante))

    totales = _calcular_totales(items, moneda)
    root.append(_build_tax_total(totales, moneda))
    root.append(_build_monetary_total(totales, moneda, tag='RequestedMonetaryTotal'))

    for idx, item in enumerate(items, start=1):
        root.append(_build_invoice_line(idx, item, moneda, line_tag='DebitNoteLine',
                                        qty_tag='DebitedQuantity'))

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
    logger.info(f"[XML_GEN] ND XML generado OK ({len(xml_bytes)} bytes)")
    return xml_bytes


# =============================================
# BLOQUES REUTILIZABLES
# =============================================

def _build_supplier(emisor: dict):
    """Construye AccountingSupplierParty.
    NO emite CityName/CountrySubentity/District si están vacíos.
    """
    supplier = _cac('AccountingSupplierParty')
    party = _cac('Party')

    pid = _cac('PartyIdentification')
    pid_id = _cbc('ID', emisor.get('ruc', ''))
    pid_id.set('schemeID', '6')
    pid_id.set('schemeName', 'Documento de Identidad')
    pid_id.set('schemeAgencyName', 'PE:SUNAT')
    pid_id.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')
    pid.append(pid_id)
    party.append(pid)

    pn = _cac('PartyName')
    pn.append(_cbc('Name', emisor.get('nombre_comercial', '') or emisor.get('razon_social', '')))
    party.append(pn)

    ple = _cac('PartyLegalEntity')
    ple.append(_cbc('RegistrationName', emisor.get('razon_social', '')))

    addr = _cac('RegistrationAddress')

    # Orden UBL 2.1 estricto
    addr.append(_cbc('ID', emisor.get('ubigeo', '') or '150101'))
    addr.append(_cbc('AddressTypeCode', '0000'))
    addr.append(_cbc('CitySubdivisionName', emisor.get('urbanizacion', '-') or '-'))

    # Solo si tienen valor (SUNAT rechaza elementos vacíos)
    provincia = (emisor.get('provincia', '') or '').strip()
    departamento = (emisor.get('departamento', '') or '').strip()
    distrito = (emisor.get('distrito', '') or '').strip()

    if provincia:
        addr.append(_cbc('CityName', provincia))
    if departamento:
        addr.append(_cbc('CountrySubentity', departamento))
    if distrito:
        addr.append(_cbc('District', distrito))

    addr_line = _cac('AddressLine')
    addr_line.append(_cbc('Line', emisor.get('direccion', '') or '-'))
    addr.append(addr_line)

    country = _cac('Country')
    country.append(_cbc('IdentificationCode', 'PE'))
    addr.append(country)

    # Log diagnóstico de dirección
    logger.info("[XML_GEN] Emisor dirección: ubigeo=%s, prov=%s, dept=%s, dist=%s",
                emisor.get('ubigeo'), provincia or '(vacío)', departamento or '(vacío)',
                distrito or '(vacío)')

    ple.append(addr)
    party.append(ple)
    supplier.append(party)
    return supplier


def _build_customer(comprobante):
    """Construye AccountingCustomerParty. No emite dirección vacía."""
    cliente_tipo_doc = (getattr(comprobante, 'cliente_tipo_doc', None) or
                        getattr(comprobante, 'cliente_tipo_documento', None) or '6')
    cliente_num_doc = (getattr(comprobante, 'cliente_numero_doc', None) or
                       getattr(comprobante, 'cliente_numero_documento', None) or
                       getattr(comprobante, 'cliente_ruc', None) or '')
    cliente_nombre = (getattr(comprobante, 'cliente_razon_social', None) or
                      getattr(comprobante, 'cliente_nombre', None) or '')
    cliente_direccion = (getattr(comprobante, 'cliente_direccion', None) or '').strip()

    logger.info(f"[XML_GEN] Cliente: tipo={cliente_tipo_doc}, doc={cliente_num_doc}, "
                f"nombre={cliente_nombre[:30]}, dir={cliente_direccion[:30] if cliente_direccion else '(vacío)'}")

    customer = _cac('AccountingCustomerParty')
    party = _cac('Party')

    pid = _cac('PartyIdentification')
    pid_id = _cbc('ID', cliente_num_doc)
    pid_id.set('schemeID', str(cliente_tipo_doc))
    pid_id.set('schemeName', 'Documento de Identidad')
    pid_id.set('schemeAgencyName', 'PE:SUNAT')
    pid_id.set('schemeURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')
    pid.append(pid_id)
    party.append(pid)

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


# =============================================
# CÁLCULOS
# =============================================

def _calcular_totales(items, moneda='PEN') -> dict:
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

        if tipo_igv == '10':
            gravado += monto_linea
            igv_total += (monto_linea * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif tipo_igv == '20':
            exonerado += monto_linea
        elif tipo_igv == '30':
            inafecto += monto_linea
        elif tipo_igv == '40':
            exportacion += monto_linea

    subtotal = gravado + exonerado + inafecto + exportacion
    total = subtotal + igv_total

    return {
        'gravado': gravado, 'exonerado': exonerado,
        'inafecto': inafecto, 'exportacion': exportacion,
        'igv_total': igv_total, 'subtotal': subtotal, 'total': total,
    }


def _build_tax_total(totales: dict, moneda='PEN'):
    tax_total = _cac('TaxTotal')
    tax_total.append(_amount('TaxAmount', totales['igv_total'], moneda))

    if totales['gravado'] > 0:
        tax_total.append(_build_tax_subtotal(totales['gravado'], totales['igv_total'],
                                              '1000', 'IGV', 'VAT', moneda))
    if totales['exonerado'] > 0:
        tax_total.append(_build_tax_subtotal(totales['exonerado'], Decimal('0.00'),
                                              '9997', 'EXO', 'VAT', moneda))
    if totales['inafecto'] > 0:
        tax_total.append(_build_tax_subtotal(totales['inafecto'], Decimal('0.00'),
                                              '9998', 'INA', 'FRE', moneda))
    if totales['exportacion'] > 0:
        tax_total.append(_build_tax_subtotal(totales['exportacion'], Decimal('0.00'),
                                              '9995', 'EXP', 'FRE', moneda))
    return tax_total


def _build_tax_subtotal(base, tax_amount, tributo_id, tributo_nombre, tributo_code, moneda='PEN'):
    ts = _cac('TaxSubtotal')
    ts.append(_amount('TaxableAmount', base, moneda))
    ts.append(_amount('TaxAmount', tax_amount, moneda))

    tc = _cac('TaxCategory')
    tc.append(_cbc('ID', tributo_id))
    tc.append(_cbc('Percent', '18.00' if tributo_id == '1000' else '0.00'))

    tax_scheme = _cac('TaxScheme')
    tax_scheme.append(_cbc('ID', tributo_id))
    tax_scheme.append(_cbc('Name', tributo_nombre))
    tax_scheme.append(_cbc('TaxTypeCode', tributo_code))
    tc.append(tax_scheme)

    ts.append(tc)
    return ts


def _build_monetary_total(totales: dict, moneda='PEN', tag='LegalMonetaryTotal'):
    monetary = _cac(tag)
    monetary.append(_amount('LineExtensionAmount', totales['subtotal'], moneda))
    monetary.append(_amount('TaxInclusiveAmount', totales['total'], moneda))
    monetary.append(_amount('PayableAmount', totales['total'], moneda))
    return monetary


def _build_invoice_line(idx, item, moneda='PEN', line_tag='InvoiceLine',
                        qty_tag='InvoicedQuantity'):
    cantidad = _d(getattr(item, 'cantidad', 1))
    precio = _d(getattr(item, 'precio_unitario', 0))
    descripcion = getattr(item, 'descripcion', '')
    unidad = getattr(item, 'unidad', None) or getattr(item, 'unidad_medida', 'NIU') or 'NIU'
    tipo_igv = str(getattr(item, 'tipo_afectacion_igv', '10') or '10')

    monto_linea = (cantidad * precio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if tipo_igv == '10':
        igv_item = (monto_linea * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        precio_con_igv = precio + (precio * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        igv_item = Decimal('0.00')
        precio_con_igv = precio

    line = _cac(line_tag)
    line.append(_cbc('ID', str(idx)))

    qty = _cbc(qty_tag, f"{cantidad:.2f}")
    qty.set('unitCode', unidad)
    qty.set('unitCodeListID', 'UN/ECE rec 20')
    qty.set('unitCodeListAgencyName', 'United Nations Economic Commission for Europe')
    line.append(qty)

    line.append(_amount('LineExtensionAmount', monto_linea, moneda))

    pricing = _cac('PricingReference')
    alt_price = _cac('AlternativeConditionPrice')
    alt_price.append(_amount('PriceAmount', precio_con_igv, moneda))
    price_type = _cbc('PriceTypeCode', '01')
    price_type.set('listName', 'Tipo de Precio')
    price_type.set('listAgencyName', 'PE:SUNAT')
    price_type.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo16')
    alt_price.append(price_type)
    pricing.append(alt_price)
    line.append(pricing)

    item_tax = _cac('TaxTotal')
    item_tax.append(_amount('TaxAmount', igv_item, moneda))

    item_ts = _cac('TaxSubtotal')
    item_ts.append(_amount('TaxableAmount', monto_linea, moneda))
    item_ts.append(_amount('TaxAmount', igv_item, moneda))

    item_tc = _cac('TaxCategory')
    item_tc.append(_cbc('ID', tipo_igv))
    item_tc.append(_cbc('Percent', '18.00' if tipo_igv == '10' else '0.00'))

    exemption = _cbc('TaxExemptionReasonCode', tipo_igv)
    exemption.set('listAgencyName', 'PE:SUNAT')
    exemption.set('listName', 'Tipo de Afectación del IGV')
    exemption.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo07')
    item_tc.append(exemption)

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

    item_el = _cac('Item')
    item_el.append(_cbc('Description', descripcion))
    line.append(item_el)

    price_el = _cac('Price')
    price_el.append(_amount('PriceAmount', precio, moneda))
    line.append(price_el)

    return line


# =============================================
# CATÁLOGOS
# =============================================

def _motivo_nc_descripcion(codigo):
    motivos = {
        '01': 'Anulación de la operación', '02': 'Anulación por error en el RUC',
        '03': 'Corrección por error en la descripción', '04': 'Descuento global',
        '05': 'Descuento por ítem', '06': 'Devolución total',
        '07': 'Devolución por ítem', '08': 'Bonificación',
        '09': 'Disminución en el valor', '10': 'Otros conceptos',
    }
    return motivos.get(codigo, 'Otros conceptos')


def _motivo_nd_descripcion(codigo):
    motivos = {
        '01': 'Intereses por mora', '02': 'Aumento en el valor',
        '03': 'Penalidades/otros conceptos',
    }
    return motivos.get(codigo, 'Otros conceptos')