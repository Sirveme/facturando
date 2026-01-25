from io import BytesIO
import base64
import zipfile
from lxml import etree
import logging

logger = logging.getLogger(__name__)

SUNAT_BETA_WSDL = 'https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService?wsdl'


def _extract_id_from_xml(xml_bytes: bytes) -> tuple[str, str]:
    # returns (serie, numero) by finding the first ID element with text like SERIE-NUMERO
    parser = etree.XMLParser(recover=True)
    doc = etree.fromstring(xml_bytes, parser=parser)
    ids = doc.xpath("//*[local-name()='ID']")
    if not ids or ids[0].text is None:
        return ('', '')
    text = ids[0].text.strip()
    if '-' in text:
        parts = text.split('-', 1)
        return parts[0], parts[1]
    return (text, '')


def _parse_cdr(cdr_bytes: bytes) -> dict:
    # Try to parse common tags used in CDRs. Return dict with codigo, descripcion and raw cdr
    try:
        doc = etree.fromstring(cdr_bytes)
    except Exception:
        return {'codigo': None, 'descripcion': None, 'cdr_xml': cdr_bytes}
    # attempt multiple tag names
    def find_text(names):
        for n in names:
            el = doc.find('.//{*}%s' % n)
            if el is not None and el.text:
                return el.text.strip()
        return None
    codigo = find_text(['codigo', 'Codigo', 'ResponseCode', 'responseCode', 'Code'])
    descripcion = find_text(['descripcion', 'Descripcion', 'Description', 'Mensaje', 'Message'])
    return {'codigo': codigo, 'descripcion': descripcion, 'cdr_xml': cdr_bytes}


def enviar_comprobante(xml_firmado: bytes, emisor_ruc: str, sol_usuario: str | None = None, sol_password: str | None = None) -> dict:
    """Envía comprobante firmado a SUNAT Beta y retorna CDR parseado.

    Returns: {'codigo': str|None, 'descripcion': str|None, 'cdr_xml': bytes}
    """
    # Build ZIP with XML
    serie, numero = _extract_id_from_xml(xml_firmado)
    xml_name = f"{emisor_ruc}-01-{serie}-{numero}.xml" if serie or numero else f"{emisor_ruc}-01.xml"
    zip_name = f"{emisor_ruc}-01-{serie}-{numero}.zip" if serie or numero else f"{emisor_ruc}-01.zip"

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, xml_firmado)
    zipped = buf.getvalue()
    content_b64 = base64.b64encode(zipped).decode('ascii')

    # Lazy import zeep to keep module lightweight and mockable
    try:
        from zeep import Client
        from zeep.exceptions import Fault
    except Exception as e:
        raise RuntimeError('zeep is required to send to SUNAT') from e

    # Call service and capture response; be tolerant if applicationResponse missing
    try:
        # optionally use zeep history plugin and WS-Security UsernameToken when credentials provided
        try:
            from zeep.plugins import HistoryPlugin
            history = HistoryPlugin()
            plugins = [history]
        except Exception:
            history = None
            plugins = None

        # prepare WS-Security if credentials provided
        wsse = None
        username_for_log = None
        if sol_usuario and sol_password:
            try:
                from zeep.wsse.username import UsernameToken
                username = f"{emisor_ruc}{sol_usuario}"
                username_for_log = username
                wsse = UsernameToken(username, sol_password, use_digest=False)
                logger.info(f"WSSE UsernameToken prepared: Username: {username_for_log} Password: {sol_password}")
                print(f"WSSE UsernameToken prepared - Username: {username_for_log} Password: {sol_password}")
            except Exception:
                wsse = None
                logger.exception("Failed to prepare WSSE UsernameToken")

        # create client with optional plugins and wsse
        if plugins is not None and wsse is not None:
            client = Client(wsdl=SUNAT_BETA_WSDL, plugins=plugins, wsse=wsse)
        elif plugins is not None:
            client = Client(wsdl=SUNAT_BETA_WSDL, plugins=plugins)
        elif wsse is not None:
            client = Client(wsdl=SUNAT_BETA_WSDL, wsse=wsse)
        else:
            client = Client(wsdl=SUNAT_BETA_WSDL)

        resp = client.service.sendBill(fileName=zip_name, contentFile=content_b64)
        # Print SOAP envelopes captured by zeep HistoryPlugin
        try:
            if 'history' in locals() and history is not None:
                try:
                    print("SOAP Request:", history.last_sent)
                except Exception:
                    print("SOAP Request: <failed to read history.last_sent>")
                try:
                    print("SOAP Response:", history.last_received)
                except Exception:
                    print("SOAP Response: <failed to read history.last_received>")
            else:
                print("SOAP Request: <no history available>")
                print("SOAP Response: <no history available>")
        except Exception:
            logger.exception("Error printing SOAP history")
    except Exception as e:
        # If zeep Fault or other SOAP error, capture its text and return as parsed failure
        try:
            err_text = str(e)
            resp_bytes = err_text.encode('utf-8')
            parsed = _parse_cdr(resp_bytes)
            # Ensure descripcion contains the exception text
            parsed['descripcion'] = parsed.get('descripcion') or err_text
            return parsed
        except Exception:
            raise RuntimeError('Error sending to SUNAT') from e

    # Extract applicationResponse if present, otherwise try to serialize resp object
    app_resp = None
    if hasattr(resp, 'applicationResponse'):
        app_resp = resp.applicationResponse
    elif isinstance(resp, dict) and 'applicationResponse' in resp:
        app_resp = resp['applicationResponse']

    if app_resp is not None:
        # decode base64
        resp_bytes = base64.b64decode(app_resp)
    else:
        # fallback: try to get textual/raw response from zeep history or repr(resp)
        resp_bytes = None
        try:
            # try history last_received (if history plugin used)
            if 'history' in locals() and history.last_received is not None:
                # history.last_received is an object with envelope; convert to string
                envelope = getattr(history.last_received, 'envelope', None)
                if envelope is not None:
                    resp_bytes = etree.tostring(envelope, encoding='utf-8')
        except Exception:
            resp_bytes = None
        if resp_bytes is None:
            resp_bytes = repr(resp).encode('utf-8')

    # Attempt to unzip if it's a zip, otherwise treat as raw xml or text
    try:
        b = BytesIO(resp_bytes)
        with zipfile.ZipFile(b) as zf:
            # find first xml file
            names = [n for n in zf.namelist() if n.lower().endswith('.xml')]
            if names:
                cdr_bytes = zf.read(names[0])
            else:
                cdr_bytes = zf.read(zf.namelist()[0])
    except Exception:
        # not a zip, assume raw xml/text
        cdr_bytes = resp_bytes

    parsed = _parse_cdr(cdr_bytes)
    return parsed
