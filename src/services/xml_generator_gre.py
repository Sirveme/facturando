"""
Generador de XML UBL 2.1 DespatchAdvice para Guía de Remisión Electrónica
Remitente (GRE, tipo 09) — SUNAT Perú, versión vigente.

Reutiliza los helpers y el patrón de UBLExtensions/Signature del generador de
facturas (xml_generator.py). NO duplica la lógica de firma.

Referencia: Manual GRE Remitente SUNAT (catálogos 18=modalidad, 20=motivo,
03=unidad de medida, 06=documento de identidad).
"""

from lxml import etree
from decimal import Decimal, ROUND_HALF_UP
import logging

from src.services.xml_generator import (
    _cbc,
    _cac,
    _build_ubl_extensions,
    _build_signature_ref,
    _format_date,
    _format_time,
)

logger = logging.getLogger(__name__)

NSMAP_DA = {
    None: "urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'ext': "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    'ds': "http://www.w3.org/2000/09/xmldsig#",
}

CAT_DOC_URI = "urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06"


def _peso(value) -> str:
    return f"{Decimal(str(value or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP):.3f}"


def _cantidad(value) -> str:
    return f"{Decimal(str(value or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP):.3f}"


def _build_party_doc(tag_party: str, tipo_doc: str, num_doc: str, razon_social: str):
    """Party con PartyIdentification (schemeID=tipo doc) + PartyLegalEntity."""
    party_wrap = _cac(tag_party)
    party = _cac('Party')

    pid = _cac('PartyIdentification')
    pid_id = _cbc('ID', num_doc or '')
    pid_id.set('schemeID', str(tipo_doc or '6'))
    pid_id.set('schemeName', 'Documento de Identidad')
    pid_id.set('schemeAgencyName', 'PE:SUNAT')
    pid_id.set('schemeURI', CAT_DOC_URI)
    pid.append(pid_id)
    party.append(pid)

    ple = _cac('PartyLegalEntity')
    ple.append(_cbc('RegistrationName', razon_social or ''))
    party.append(ple)

    party_wrap.append(party)
    return party_wrap


def _build_address(tag: str, ubigeo: str, direccion: str):
    """DeliveryAddress / DespatchAddress: ID=ubigeo + AddressLine/Line."""
    addr = _cac(tag)
    addr_id = _cbc('ID', ubigeo or '')
    addr_id.set('schemeAgencyName', 'PE:INEI')
    addr_id.set('schemeName', 'Ubigeos')
    addr.append(addr_id)
    addr_line = _cac('AddressLine')
    addr_line.append(_cbc('Line', direccion or ''))
    addr.append(addr_line)
    return addr


def _build_carrier_party(guia):
    """CarrierParty para transporte público (modalidad 01)."""
    return _build_party_doc(
        'CarrierParty',
        getattr(guia, 'transportista_tipo_doc', '6'),
        getattr(guia, 'transportista_num_doc', ''),
        getattr(guia, 'transportista_razon_social', ''),
    )


def _build_driver_person(guia):
    """DriverPerson para transporte privado (modalidad 02 sin M1L)."""
    dp = _cac('DriverPerson')
    did = _cbc('ID', getattr(guia, 'conductor_num_doc', '') or '')
    did.set('schemeID', str(getattr(guia, 'conductor_tipo_doc', '1') or '1'))
    did.set('schemeName', 'Documento de Identidad')
    did.set('schemeAgencyName', 'PE:SUNAT')
    did.set('schemeURI', CAT_DOC_URI)
    dp.append(did)

    nombres = (getattr(guia, 'conductor_nombres', '') or '').strip()
    partes = nombres.split()
    first_name = partes[0] if partes else nombres
    family_name = " ".join(partes[1:]) if len(partes) > 1 else nombres
    dp.append(_cbc('FirstName', first_name))
    dp.append(_cbc('FamilyName', family_name))
    dp.append(_cbc('JobTitle', 'Principal'))

    lic = _cac('IdentityDocumentReference')
    lic.append(_cbc('ID', getattr(guia, 'conductor_licencia', '') or ''))
    dp.append(lic)
    return dp


def _build_shipment_stage(guia):
    stage = _cac('ShipmentStage')

    modalidad = getattr(guia, 'modalidad_traslado', '02')
    mode = _cbc('TransportModeCode', modalidad)
    mode.set('listAgencyName', 'PE:SUNAT')
    mode.set('listName', 'Modalidad de traslado')
    mode.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo18')
    stage.append(mode)

    transit = _cac('TransitPeriod')
    transit.append(_cbc('StartDate', _format_date(getattr(guia, 'fecha_inicio_traslado', None))))
    stage.append(transit)

    m1l = bool(getattr(guia, 'indicador_vehiculo_m1l', False))

    # Modalidad 01 = público → CarrierParty (transportista)
    if modalidad == '01':
        stage.append(_build_carrier_party(guia))

    # Modalidad 02 = privado y NO M1L → vehículo + conductor
    elif modalidad == '02' and not m1l:
        placa = getattr(guia, 'vehiculo_placa', None)
        if placa:
            tm = _cac('TransportMeans')
            road = _cac('RoadTransport')
            road.append(_cbc('LicensePlateID', placa))
            tm.append(road)
            stage.append(tm)
        stage.append(_build_driver_person(guia))

    return stage


def _build_despatch_line(item):
    orden = getattr(item, 'orden', 1)
    line = _cac('DespatchLine')
    line.append(_cbc('ID', str(orden)))

    qty = _cbc('DeliveredQuantity', _cantidad(getattr(item, 'cantidad', 1)))
    qty.set('unitCode', getattr(item, 'unidad_medida', 'NIU') or 'NIU')
    line.append(qty)

    olr = _cac('OrderLineReference')
    olr.append(_cbc('LineID', str(orden)))
    line.append(olr)

    item_el = _cac('Item')
    item_el.append(_cbc('Description', getattr(item, 'descripcion', '') or ''))
    codigo = getattr(item, 'codigo', None)
    if codigo:
        sii = _cac('SellersItemIdentification')
        sii.append(_cbc('ID', codigo))
        item_el.append(sii)
    line.append(item_el)
    return line


def build_despatch_advice_xml(guia, emisor: dict) -> bytes:
    """Genera el XML UBL 2.1 DespatchAdvice (GRE tipo 09) sin firmar.

    Args:
        guia: instancia GuiaRemision (con .items).
        emisor: dict con al menos {'ruc', 'razon_social'} (patrón facturas).

    Returns:
        XML como bytes (sin firmar; la firma va en ExtensionContent vacío).
    """
    serie = getattr(guia, 'serie', 'T060')
    numero = getattr(guia, 'numero', 1)
    items = getattr(guia, 'items', []) or []

    logger.info("[GRE_XML] DespatchAdvice %s-%s motivo=%s modalidad=%s items=%d",
                serie, numero, getattr(guia, 'motivo_traslado', None),
                getattr(guia, 'modalidad_traslado', None), len(items))

    root = etree.Element(etree.QName(NSMAP_DA[None], 'DespatchAdvice'), nsmap=NSMAP_DA)

    # 1. UBLExtensions (ExtensionContent vacío para la firma)
    root.append(_build_ubl_extensions())

    # 2. Cabecera
    root.append(_cbc('UBLVersionID', '2.1'))
    root.append(_cbc('CustomizationID', '2.0'))
    root.append(_cbc('ID', f"{serie}-{numero}"))
    root.append(_cbc('IssueDate', _format_date(getattr(guia, 'fecha_emision', None))))
    root.append(_cbc('IssueTime', _format_time(getattr(guia, 'fecha_emision', None))))
    root.append(_cbc('DespatchAdviceTypeCode', '09'))

    # 3. Signature reference (mismo patrón facturas)
    root.append(_build_signature_ref(emisor))

    # 4. DespatchSupplierParty (emisor / remitente)
    root.append(_build_party_doc('DespatchSupplierParty', '6',
                                 emisor.get('ruc', ''), emisor.get('razon_social', '')))

    # 5. DeliveryCustomerParty (destinatario)
    root.append(_build_party_doc('DeliveryCustomerParty',
                                 getattr(guia, 'dest_tipo_doc', '6'),
                                 getattr(guia, 'dest_num_doc', ''),
                                 getattr(guia, 'dest_razon_social', '')))

    # 6. Shipment
    shipment = _cac('Shipment')
    shipment.append(_cbc('ID', 'SUNAT_Envio'))

    motivo = getattr(guia, 'motivo_traslado', '01')
    handling = _cbc('HandlingCode', motivo)
    handling.set('listAgencyName', 'PE:SUNAT')
    handling.set('listName', 'Motivo de traslado')
    handling.set('listURI', 'urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo20')
    shipment.append(handling)

    descripcion_motivo = getattr(guia, 'descripcion_motivo', None)
    if motivo == '13' and descripcion_motivo:
        shipment.append(_cbc('HandlingInstructions', descripcion_motivo))

    gw = _cbc('GrossWeightMeasure', _peso(getattr(guia, 'peso_bruto_total', 0)))
    gw.set('unitCode', getattr(guia, 'unidad_peso', 'KGM') or 'KGM')
    shipment.append(gw)

    bultos = getattr(guia, 'numero_bultos', None)
    if bultos is not None:
        shipment.append(_cbc('TotalTransportHandlingUnitQuantity', str(bultos)))

    if bool(getattr(guia, 'indicador_vehiculo_m1l', False)):
        shipment.append(_cbc('SpecialInstructions',
                             'SUNAT_Envio_IndicadorTrasladoVehiculoM1L'))

    shipment.append(_build_shipment_stage(guia))

    # Delivery: dirección de llegada + Despatch/dirección de partida
    delivery = _cac('Delivery')
    delivery.append(_build_address('DeliveryAddress',
                                   getattr(guia, 'llegada_ubigeo', ''),
                                   getattr(guia, 'llegada_direccion', '')))
    despatch = _cac('Despatch')
    despatch.append(_build_address('DespatchAddress',
                                   getattr(guia, 'partida_ubigeo', ''),
                                   getattr(guia, 'partida_direccion', '')))
    delivery.append(despatch)
    shipment.append(delivery)

    root.append(shipment)

    # 7. AdditionalDocumentReference (factura vinculada) — SIN CAMBIOS (aceptado por SUNAT)
    comprobante = getattr(guia, 'comprobante', None)
    if comprobante is not None:
        adr = _cac('AdditionalDocumentReference')
        adr.append(_cbc('ID', f"{comprobante.serie}-{comprobante.numero}"))
        adr.append(_cbc('DocumentTypeCode', '01'))
        root.append(adr)

    # 7b. AdditionalDocumentReference por cada documento relacionado (ADITIVO).
    #     Acceso defensivo: si la tabla aún no existe (SQL pendiente en PGAdmin),
    #     no debe romper la emisión de la GRE.
    try:
        docs_rel = list(getattr(guia, 'docs_relacionados', None) or [])
    except Exception:
        docs_rel = []
    for doc in docs_rel:
        numero = (getattr(doc, 'numero', '') or '').strip()
        tipo = (getattr(doc, 'tipo_doc', '') or '').strip()
        if not numero or not tipo:
            continue
        adr = _cac('AdditionalDocumentReference')
        adr.append(_cbc('ID', numero))
        adr.append(_cbc('DocumentTypeCode', tipo))
        ruc_emisor_doc = (getattr(doc, 'emisor_doc_ruc', None) or '').strip()
        if ruc_emisor_doc:
            issuer = _cac('IssuerParty')
            pid = _cac('PartyIdentification')
            pid_id = _cbc('ID', ruc_emisor_doc)
            pid_id.set('schemeID', '6')
            pid_id.set('schemeName', 'Documento de Identidad')
            pid_id.set('schemeAgencyName', 'PE:SUNAT')
            pid_id.set('schemeURI', CAT_DOC_URI)
            pid.append(pid_id)
            issuer.append(pid)
            adr.append(issuer)
        root.append(adr)

    # 8. DespatchLine por item
    for item in items:
        root.append(_build_despatch_line(item))

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
    logger.info("[GRE_XML] XML DespatchAdvice generado OK (%d bytes)", len(xml_bytes))
    return xml_bytes
