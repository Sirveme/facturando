"""
Generador de XML UBL SummaryDocuments-1.1 para Resumen Diario de Boletas (RC).
SUNAT — Catálogo 19 (StatusCode 1=Adicionar, 2=Modificar, 3=Anular).

Formato del ID: RC-YYYYMMDD-N (N = correlativo del día).
"""
from lxml import etree
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger(__name__)

PERU_TZ = timezone(timedelta(hours=-5))

NSMAP = {
    None: "urn:sunat:names:specification:ubl:peru:schema:xsd:SummaryDocuments-1",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'sac': "urn:sunat:names:specification:ubl:peru:schema:xsd:SunatAggregateComponents-1",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
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


def _sac(tag):
    return etree.Element(etree.QName(NSMAP['sac'], tag))


def _amount(tag, value, currency='PEN', ns='cbc'):
    if ns == 'sac':
        el = etree.Element(etree.QName(NSMAP['sac'], tag))
    else:
        el = _cbc(tag, None)
    el.text = f"{_d(value):.2f}"
    el.set('currencyID', currency)
    return el


def _format_date(fecha) -> str:
    if isinstance(fecha, str):
        return fecha
    if hasattr(fecha, 'strftime'):
        return fecha.strftime('%Y-%m-%d')
    return str(fecha)


def _build_ubl_extensions():
    ubl_exts = etree.Element(etree.QName(NSMAP['ext'], 'UBLExtensions'))
    ubl_ext = etree.SubElement(ubl_exts, etree.QName(NSMAP['ext'], 'UBLExtension'))
    etree.SubElement(ubl_ext, etree.QName(NSMAP['ext'], 'ExtensionContent'))
    return ubl_exts


def _build_signature_ref(emisor_ruc: str, emisor_razon: str):
    sig = _cac('Signature')
    sig.append(_cbc('ID', emisor_ruc))
    sig_party = _cac('SignatoryParty')
    pid = _cac('PartyIdentification')
    pid.append(_cbc('ID', emisor_ruc))
    sig_party.append(pid)
    pn = _cac('PartyName')
    pn.append(_cbc('Name', emisor_razon))
    sig_party.append(pn)
    sig.append(sig_party)
    dsa = _cac('DigitalSignatureAttachment')
    er = _cac('ExternalReference')
    er.append(_cbc('URI', f"#{emisor_ruc}-SIGN"))
    dsa.append(er)
    sig.append(dsa)
    return sig


def _build_supplier(emisor_ruc: str, emisor_razon: str):
    asp = _cac('AccountingSupplierParty')
    asp.append(_cbc('CustomerAssignedAccountID', emisor_ruc))
    asp.append(_cbc('AdditionalAccountID', '6'))  # 6 = RUC
    party = _cac('Party')
    pn = _cac('PartyLegalEntity')
    pn.append(_cbc('RegistrationName', emisor_razon))
    party.append(pn)
    asp.append(party)
    return asp


def _build_summary_line(orden: int, boleta: dict, moneda: str = 'PEN'):
    """Construye una línea SummaryDocumentsLine.

    boleta esperado:
        serie, numero (str o int), tipo_documento (default '03'),
        cliente_tipo_doc (default '1'), cliente_numero_doc,
        total, igv, base_imponible (gravado), exonerado, inafecto
    """
    line = _sac('SummaryDocumentsLine')

    line.append(_cbc('LineID', str(orden)))
    line.append(_cbc('DocumentTypeCode', boleta.get('tipo_documento', '03')))

    serie = boleta.get('serie', '')
    numero = boleta.get('numero', '')
    if isinstance(numero, int):
        numero_fmt = str(numero)
    else:
        numero_fmt = str(numero)
    doc_id = f"{serie}-{numero_fmt}"
    line.append(_cbc('ID', doc_id))

    # Cliente (tipo y número de documento)
    cli_tipo = boleta.get('cliente_tipo_doc') or '1'
    cli_num = boleta.get('cliente_numero_doc') or ''
    if cli_num:
        ac = _cac('AccountingCustomerParty')
        ac.append(_cbc('CustomerAssignedAccountID', cli_num))
        ac.append(_cbc('AdditionalAccountID', cli_tipo))
        line.append(ac)

    # Status (1=Adicionar)
    status = _cac('Status')
    status.append(_cbc('ConditionCode', boleta.get('status_code', '1')))
    line.append(status)

    # TotalAmount = importe total cobrado
    line.append(_amount('TotalAmount', boleta.get('total', 0), moneda, ns='sac'))

    # BillingPayment Subtotal por categoría:
    #   01 = total operaciones gravadas
    #   02 = total operaciones exoneradas
    #   03 = total operaciones inafectas
    #   05 = total operaciones gratuitas
    base_gravada = _d(boleta.get('base_imponible', 0))
    exonerado = _d(boleta.get('exonerado', 0))
    inafecto = _d(boleta.get('inafecto', 0))

    if base_gravada > 0:
        bp = _sac('BillingPayment')
        bp.append(_amount('PaidAmount', base_gravada, moneda))
        bp.append(_cbc('InstructionID', '01'))
        line.append(bp)
    if exonerado > 0:
        bp = _sac('BillingPayment')
        bp.append(_amount('PaidAmount', exonerado, moneda))
        bp.append(_cbc('InstructionID', '02'))
        line.append(bp)
    if inafecto > 0:
        bp = _sac('BillingPayment')
        bp.append(_amount('PaidAmount', inafecto, moneda))
        bp.append(_cbc('InstructionID', '03'))
        line.append(bp)

    # IGV TaxTotal
    igv = _d(boleta.get('igv', 0))
    tax_total = _cac('TaxTotal')
    tax_total.append(_amount('TaxAmount', igv, moneda))
    tax_subtotal = _cac('TaxSubtotal')
    tax_subtotal.append(_amount('TaxAmount', igv, moneda))
    tax_cat = _cac('TaxCategory')
    tax_scheme = _cac('TaxScheme')
    tax_scheme.append(_cbc('ID', '1000'))
    tax_scheme.append(_cbc('Name', 'IGV'))
    tax_scheme.append(_cbc('TaxTypeCode', 'VAT'))
    tax_cat.append(tax_scheme)
    tax_subtotal.append(tax_cat)
    tax_total.append(tax_subtotal)
    line.append(tax_total)

    return line


def build_summary_xml(
    emisor_ruc: str,
    emisor_razon_social: str,
    emisor_ubigeo: str,
    fecha_referencia,
    correlativo: int,
    boletas: list,
    moneda: str = 'PEN',
) -> bytes:
    """Genera XML UBL SummaryDocuments-1.1 sin firmar.

    Args:
        emisor_ruc: RUC del emisor (11 dígitos).
        emisor_razon_social: Razón social.
        emisor_ubigeo: Ubigeo de 6 dígitos (no usado en SummaryDocuments pero recibido por compatibilidad).
        fecha_referencia: Fecha de las boletas (date o str YYYY-MM-DD).
        correlativo: 1, 2, 3... del día.
        boletas: lista de dicts con datos de cada boleta.
        moneda: 'PEN' por defecto.

    Returns:
        Bytes UTF-8 con el XML listo para firmar.
    """
    fecha_ref_str = _format_date(fecha_referencia)
    fecha_ref_compact = fecha_ref_str.replace('-', '')

    # IssueDate = hoy (fecha de generación del resumen, no la de las boletas)
    fecha_hoy = datetime.now(tz=PERU_TZ).strftime('%Y-%m-%d')

    summary_id = f"RC-{fecha_ref_compact}-{str(correlativo).zfill(5)}"

    root = etree.Element(
        etree.QName(NSMAP[None], 'SummaryDocuments'),
        nsmap=NSMAP,
    )

    # UBLExtensions (placeholder para firma)
    root.append(_build_ubl_extensions())

    root.append(_cbc('UBLVersionID', '2.0'))
    root.append(_cbc('CustomizationID', '1.1'))
    root.append(_cbc('ID', summary_id))
    root.append(_cbc('ReferenceDate', fecha_ref_str))
    root.append(_cbc('IssueDate', fecha_hoy))

    # Signature (referencia a la firma que ira en UBLExtensions)
    root.append(_build_signature_ref(emisor_ruc, emisor_razon_social))

    # AccountingSupplierParty
    root.append(_build_supplier(emisor_ruc, emisor_razon_social))

    # Líneas
    for idx, boleta in enumerate(boletas, start=1):
        root.append(_build_summary_line(idx, boleta, moneda=moneda))

    xml_bytes = etree.tostring(
        root, xml_declaration=True, encoding='UTF-8', standalone=False
    )
    logger.info("XML SummaryDocuments generado: id=%s, lineas=%d, %d bytes",
                summary_id, len(boletas), len(xml_bytes))
    return xml_bytes
