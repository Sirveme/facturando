"""
Cliente SOAP para envío de comprobantes a SUNAT Beta/Producción.

Mejoras:
- Caché de cliente SOAP (evita re-descargar WSDL en cada envío)
- Transport con Session para manejar auth en descarga de WSDL/schemas
- Retry automático para errores transitorios de SUNAT Beta
"""

from io import BytesIO
import base64
import zipfile
from lxml import etree
import logging
import time

logger = logging.getLogger(__name__)

# URLs SUNAT
SUNAT_BETA_WSDL = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService?wsdl"
SUNAT_BETA_URL = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
SUNAT_PROD_WSDL = "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService?wsdl"
SUNAT_PROD_URL = "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"

# Caché global del cliente SOAP (evita re-descargar WSDL en cada envío)
_cached_client = None
_cached_wsdl_url = None


def _get_or_create_client(wsdl_url: str, wsse, force_new: bool = False):
    """Obtiene cliente SOAP cacheado o crea uno nuevo.

    El WSDL de SUNAT rara vez cambia, así que cacheamos el cliente
    para evitar re-descargarlo en cada envío. Esto también evita
    el error 401 en schemas importados (?ns1.wsdl).
    """
    global _cached_client, _cached_wsdl_url

    if _cached_client is not None and _cached_wsdl_url == wsdl_url and not force_new:
        # Reusar cliente existente, solo actualizar credenciales WSSE
        _cached_client.wsse = wsse
        logger.info("Reusando cliente SOAP cacheado")
        return _cached_client

    logger.info("Creando nuevo cliente SOAP para %s", wsdl_url)

    try:
        from zeep import Client
        from zeep.transports import Transport
        from zeep.plugins import HistoryPlugin
        import requests
    except ImportError as e:
        raise RuntimeError("zeep es requerido: pip install zeep") from e

    # Session con headers y timeouts adecuados
    session = requests.Session()
    session.headers.update({
        'Content-Type': 'text/xml; charset=utf-8',
        'Accept': 'text/xml, application/xml',
    })
    # Retry adapter para requests HTTP (descarga de WSDL/schemas)
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[401, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    transport = Transport(session=session, timeout=60, operation_timeout=60)

    client = Client(wsdl=wsdl_url, transport=transport, wsse=wsse)

    _cached_client = client
    _cached_wsdl_url = wsdl_url
    logger.info("Cliente SOAP creado y cacheado exitosamente")

    return client


def _extract_meta_from_xml(xml_bytes: bytes) -> dict:
    """Extrae serie, numero y tipo_comprobante del XML UBL.

    Returns:
        {'serie': str, 'numero': str, 'tipo': str}
        tipo: '01'=factura, '03'=boleta, '07'=NC, '08'=ND
    """
    parser = etree.XMLParser(recover=True)
    doc = etree.fromstring(xml_bytes, parser=parser)

    # Extraer serie-numero del elemento ID
    serie, numero = "", ""
    ids = doc.xpath("//*[local-name()='ID']")
    if ids and ids[0].text:
        text = ids[0].text.strip()
        if "-" in text:
            parts = text.split("-", 1)
            serie, numero = parts[0], parts[1]
        else:
            serie = text

    # Extraer tipo de comprobante
    tipo = "01"
    for tag in ["InvoiceTypeCode", "CreditNoteTypeCode", "DebitNoteTypeCode"]:
        el = doc.find(".//*[local-name()='%s']" % tag)  # noqa: UP031
        if el is not None and el.text:
            tipo = el.text.strip()
            break

    # Inferir tipo por serie si no se encontró tag
    if tipo == "01" and serie:
        prefix = serie[0].upper()
        if prefix == "B":
            tipo = "03"

    return {"serie": serie, "numero": numero, "tipo": tipo}


def _parse_cdr(cdr_bytes: bytes) -> dict:
    """Parsea CDR de SUNAT extrayendo código y descripción."""
    try:
        doc = etree.fromstring(cdr_bytes)
    except Exception:
        return {"codigo": None, "descripcion": None, "cdr_xml": cdr_bytes}

    def find_text(names):
        for n in names:
            el = doc.find(".//{*}%s" % n)
            if el is not None and el.text:
                return el.text.strip()
        return None

    codigo = find_text(
        ["codigo", "Codigo", "ResponseCode", "responseCode", "Code"]
    )
    descripcion = find_text(
        ["descripcion", "Descripcion", "Description", "Mensaje", "Message"]
    )
    return {"codigo": codigo, "descripcion": descripcion, "cdr_xml": cdr_bytes}


def enviar_comprobante(
    xml_firmado: bytes,
    emisor_ruc: str,
    sol_usuario: str | None = None,
    sol_password: str | None = None,
    use_production: bool = False,
) -> dict:
    """Envía comprobante firmado a SUNAT Beta/Producción y retorna CDR parseado.

    Args:
        xml_firmado: XML firmado (bytes)
        emisor_ruc: RUC del emisor
        sol_usuario: Usuario SOL (sin RUC, ej: "MODDATOS")
        sol_password: Clave SOL
        use_production: Si True, usa endpoint de producción

    Returns:
        {'codigo': str|None, 'descripcion': str|None, 'cdr_xml': bytes}
    """
    from zeep.wsse.username import UsernameToken
    from zeep.plugins import HistoryPlugin

    # Extraer metadata del XML para armar nombre correcto del ZIP
    meta = _extract_meta_from_xml(xml_firmado)
    serie = meta["serie"]
    numero = meta["numero"]
    tipo = meta["tipo"]

    # Nombre según estándar SUNAT: {RUC}-{TIPO}-{SERIE}-{NUMERO}
    base_name = f"{emisor_ruc}-{tipo}-{serie}-{numero}"
    xml_name = f"{base_name}.xml"
    zip_name = f"{base_name}.zip"

    logger.info("Preparando envío: %s", zip_name)

    # Crear ZIP con el XML
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, xml_firmado)
    zipped = buf.getvalue()
    content_b64 = base64.b64encode(zipped).decode("ascii")

    # Preparar WS-Security
    wsse = None
    if sol_usuario and sol_password:
        username = f"{emisor_ruc}{sol_usuario}"
        wsse = UsernameToken(username, sol_password, use_digest=False)
        logger.info("WSSE UsernameToken prepared: Username: %s Password: %s", username, sol_password)
        print(f"WSSE UsernameToken prepared - Username: {username} Password: {sol_password}")

    # Seleccionar endpoint
    wsdl_url = SUNAT_PROD_WSDL if use_production else SUNAT_BETA_WSDL

    # Intentar con cliente cacheado, si falla crear uno nuevo
    last_error = None
    for attempt in range(3):
        try:
            force_new = (attempt > 0)  # Forzar nuevo cliente en reintentos
            client = _get_or_create_client(wsdl_url, wsse, force_new=force_new)

            history = HistoryPlugin()
            client.plugins = [history]

            resp = client.service.sendBill(
                fileName=zip_name,
                contentFile=content_b64
            )

            # Log SOAP para debug
            _log_soap_history(history)

            # Extraer applicationResponse
            app_resp = None
            if hasattr(resp, "applicationResponse"):
                app_resp = resp.applicationResponse
            elif isinstance(resp, dict) and "applicationResponse" in resp:
                app_resp = resp["applicationResponse"]

            if app_resp is not None:
                resp_bytes = base64.b64decode(app_resp)
            else:
                resp_bytes = _extract_from_history(history)

            # Descomprimir ZIP de respuesta (CDR viene como ZIP)
            cdr_bytes = _try_unzip(resp_bytes)

            parsed = _parse_cdr(cdr_bytes)
            logger.info("CDR: codigo=%s, descripcion=%s", parsed["codigo"], parsed["descripcion"])
            return parsed

        except Exception as e:
            last_error = e
            err_text = str(e)
            logger.warning(
                "Intento %d/3 falló: %s", attempt + 1, err_text
            )

            # Si es 401 o error de conexión, invalidar caché y reintentar
            if "401" in err_text or "Unauthorized" in err_text or "ConnectionError" in err_text:
                global _cached_client
                _cached_client = None
                logger.info("Caché de cliente SOAP invalidado por error de auth/conexión")

                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    logger.info("Esperando %ds antes de reintentar...", wait)
                    print(f"⏳ Reintentando en {wait}s (intento {attempt + 2}/3)...")
                    time.sleep(wait)
                    continue

            # Si es error SOAP de SUNAT (no de red), no reintentar
            # Retornar el error como CDR para que envio_sunat.py lo procese
            return {
                "codigo": None,
                "descripcion": err_text,
                "cdr_xml": err_text.encode("utf-8"),
            }

    # Si agotamos todos los intentos
    return {
        "codigo": None,
        "descripcion": str(last_error),
        "cdr_xml": str(last_error).encode("utf-8"),
    }


def _log_soap_history(history):
    """Log SOAP request/response para debugging."""
    try:
        if history.last_sent:
            logger.debug(
                "SOAP Request: %s",
                etree.tostring(history.last_sent["envelope"], pretty_print=True).decode(),
            )
        if history.last_received:
            logger.debug(
                "SOAP Response: %s",
                etree.tostring(history.last_received["envelope"], pretty_print=True).decode(),
            )
    except Exception:
        pass


def _extract_from_history(history) -> bytes:
    """Intenta extraer respuesta del historial SOAP de zeep."""
    try:
        if history.last_received is not None:
            envelope = getattr(history.last_received, "envelope", None)
            if envelope is not None:
                return etree.tostring(envelope, encoding="utf-8")
    except Exception:
        pass
    return b"<error>No applicationResponse received</error>"


def _try_unzip(data: bytes) -> bytes:
    """Si data es un ZIP, extrae el primer XML. Si no, retorna tal cual."""
    try:
        b = BytesIO(data)
        with zipfile.ZipFile(b) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if names:
                return zf.read(names[0])
            return zf.read(zf.namelist()[0])
    except Exception:
        return data