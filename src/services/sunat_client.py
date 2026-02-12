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

# Caché global del cliente SOAP
_cached_client = None
_cached_wsdl_url = None


def _get_or_create_client(wsdl_url: str, wsse, force_new: bool = False):
    """Obtiene cliente SOAP cacheado o crea uno nuevo."""
    global _cached_client, _cached_wsdl_url

    if _cached_client is not None and _cached_wsdl_url == wsdl_url and not force_new:
        _cached_client.wsse = wsse
        logger.info("Reusando cliente SOAP cacheado")
        return _cached_client

    logger.info("Creando nuevo cliente SOAP para %s", wsdl_url)

    try:
        from zeep import Client
        from zeep.transports import Transport
        import requests
    except ImportError as e:
        raise RuntimeError("zeep es requerido: pip install zeep") from e

    session = requests.Session()
    session.headers.update({
        'Content-Type': 'text/xml; charset=utf-8',
        'Accept': 'text/xml, application/xml',
    })

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
    """
    parser = etree.XMLParser(recover=True)
    doc = etree.fromstring(xml_bytes, parser=parser)

    # Extraer serie-numero del elemento ID
    serie, numero = "", ""
    # Usar xpath() en lugar de find() porque local-name() es XPath, no ElementPath
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
        # IMPORTANTE: usar xpath(), NO find() - lxml find() no soporta local-name()
        els = doc.xpath("//*[local-name()='%s']" % tag)
        el = els[0] if els else None
        if el is not None and el.text:
            tipo = el.text.strip()
            break

    # Inferir tipo por serie si no se encontró tag específico
    if tipo == "01" and serie:
        prefix = serie[0].upper()
        if prefix == "B":
            tipo = "03"

    return {"serie": serie, "numero": numero, "tipo": tipo}


def _parse_cdr(cdr_bytes: bytes) -> dict:
    """Parsea CDR de SUNAT extrayendo código y descripción."""
    # Log diagnóstico: ver qué recibimos
    try:
        preview = cdr_bytes[:500].decode('utf-8', errors='replace')
    except Exception:
        preview = str(cdr_bytes[:500])
    logger.info("[CDR_PARSE] Raw CDR preview (%d bytes): %s", len(cdr_bytes), preview)
    print(f"[CDR_PARSE] Raw CDR ({len(cdr_bytes)} bytes): {preview}")

    try:
        doc = etree.fromstring(cdr_bytes)
    except Exception as e:
        logger.error("[CDR_PARSE] No se pudo parsear XML: %s", e)
        print(f"[CDR_PARSE] ❌ No es XML válido: {e}")
        return {"codigo": None, "descripcion": None, "cdr_xml": cdr_bytes}

    # Log todos los tags del CDR para diagnóstico
    all_tags = [el.tag.split('}')[-1] if '}' in el.tag else el.tag for el in doc.iter()]
    logger.info("[CDR_PARSE] Tags en CDR: %s", all_tags[:30])
    print(f"[CDR_PARSE] Tags: {all_tags[:30]}")

    def find_text(names):
        for n in names:
            els = doc.xpath(".//*[local-name()='%s']" % n)
            if els and els[0].text:
                logger.info("[CDR_PARSE] Encontrado %s = %s", n, els[0].text.strip())
                return els[0].text.strip()
        return None

    codigo = find_text(
        ["ResponseCode", "responseCode", "Code", "codigo", "Codigo"]
    )
    descripcion = find_text(
        ["Description", "description", "Descripcion", "descripcion", "Mensaje", "Message"]
    )

    logger.info("[CDR_PARSE] Resultado: codigo=%s, descripcion=%s", codigo, descripcion)
    print(f"[CDR_PARSE] Resultado: codigo={codigo}, descripcion={descripcion}")
    return {"codigo": codigo, "descripcion": descripcion, "cdr_xml": cdr_bytes}


def enviar_comprobante(
    xml_firmado: bytes,
    emisor_ruc: str,
    sol_usuario: str | None = None,
    sol_password: str | None = None,
    use_production: bool = False,
) -> dict:
    """Envía comprobante firmado a SUNAT Beta/Producción y retorna CDR parseado."""
    from zeep.wsse.username import UsernameToken
    from zeep.plugins import HistoryPlugin

    # Extraer metadata del XML
    meta = _extract_meta_from_xml(xml_firmado)
    serie = meta["serie"]
    numero = meta["numero"]
    tipo = meta["tipo"]

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
            force_new = (attempt > 0)
            client = _get_or_create_client(wsdl_url, wsse, force_new=force_new)

            history = HistoryPlugin()
            client.plugins = [history]

            resp = client.service.sendBill(
                fileName=zip_name,
                contentFile=content_b64
            )

            _log_soap_history(history)

            # Log tipo de respuesta
            logger.info("[SOAP] Tipo de respuesta: %s", type(resp))
            print(f"[SOAP] Respuesta tipo: {type(resp)}, valor: {str(resp)[:200]}")

            # Extraer applicationResponse
            app_resp = None
            if hasattr(resp, "applicationResponse"):
                app_resp = resp.applicationResponse
                logger.info("[SOAP] applicationResponse encontrado (hasattr)")
            elif isinstance(resp, dict) and "applicationResponse" in resp:
                app_resp = resp["applicationResponse"]
                logger.info("[SOAP] applicationResponse encontrado (dict)")
            elif isinstance(resp, bytes):
                # Respuesta directa en bytes (algunos endpoints)
                app_resp = base64.b64encode(resp).decode('ascii')
                logger.info("[SOAP] Respuesta directa en bytes")
            else:
                logger.warning("[SOAP] No se encontró applicationResponse. resp=%s", str(resp)[:300])
                print(f"[SOAP] ⚠️ Sin applicationResponse. resp={str(resp)[:300]}")

            if app_resp is not None:
                logger.info("[SOAP] applicationResponse len=%d", len(str(app_resp)))
                resp_bytes = base64.b64decode(app_resp)
                print(f"[SOAP] Decoded response: {len(resp_bytes)} bytes")
            else:
                resp_bytes = _extract_from_history(history)
                print(f"[SOAP] Fallback a history: {len(resp_bytes)} bytes")

            cdr_bytes = _try_unzip(resp_bytes)

            parsed = _parse_cdr(cdr_bytes)
            logger.info("CDR: codigo=%s, descripcion=%s", parsed["codigo"], parsed["descripcion"])
            return parsed

        except Exception as e:
            last_error = e
            err_text = str(e)
            logger.warning("Intento %d/3 falló: %s", attempt + 1, err_text)

            # Si es 401 o error de conexión, invalidar caché y reintentar
            if "401" in err_text or "Unauthorized" in err_text or "ConnectionError" in err_text:
                global _cached_client
                _cached_client = None
                logger.info("Caché de cliente SOAP invalidado")

                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    logger.info("Esperando %ds antes de reintentar...", wait)
                    print(f"⏳ Reintentando en {wait}s (intento {attempt + 2}/3)...")
                    time.sleep(wait)
                    continue

            # Error no recuperable - retornar
            return {
                "codigo": None,
                "descripcion": err_text,
                "cdr_xml": err_text.encode("utf-8"),
            }

    return {
        "codigo": None,
        "descripcion": str(last_error),
        "cdr_xml": str(last_error).encode("utf-8"),
    }


def _log_soap_history(history):
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
    try:
        if history.last_received is not None:
            envelope = getattr(history.last_received, "envelope", None)
            if envelope is not None:
                return etree.tostring(envelope, encoding="utf-8")
    except Exception:
        pass
    return b"<e>No applicationResponse received</e>"


def _try_unzip(data: bytes) -> bytes:
    try:
        b = BytesIO(data)
        with zipfile.ZipFile(b) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if names:
                return zf.read(names[0])
            return zf.read(zf.namelist()[0])
    except Exception:
        return data