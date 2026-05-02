"""
Cliente SOAP para envío de comprobantes a SUNAT Beta/Producción.

- Beta: zeep (WSDL compatible)
- Producción: SOAP raw con requests (WSDL de producción incompatible con zeep)
- Caché de cliente SOAP para Beta
- Retry automático para errores transitorios
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

# URLs SUNAT — Resumen Diario / Comunicación de Baja (otros CPE)
SUNAT_PROD_SUMMARY_URL = "https://e-factura.sunat.gob.pe/ol-ti-itemision-otroscpe-gem/billService"
SUNAT_BETA_SUMMARY_URL = "https://e-beta.sunat.gob.pe/ol-ti-itemision-otroscpe-gem-beta/billService"

# Caché global del cliente SOAP (solo para Beta)
_cached_client = None
_cached_wsdl_url = None


def _get_or_create_client(wsdl_url: str, wsse, force_new: bool = False):
    """Obtiene cliente SOAP cacheado o crea uno nuevo (solo Beta)."""
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


def _send_raw_soap(endpoint_url: str, username: str, password: str,
                   zip_name: str, content_b64: str) -> bytes:
    """Envío SOAP raw sin zeep — para producción donde el WSDL es incompatible."""
    import requests

    soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ser="http://service.sunat.gob.pe"
                  xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header>
    <wsse:Security>
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password>{password}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <ser:sendBill>
      <fileName>{zip_name}</fileName>
      <contentFile>{content_b64}</contentFile>
    </ser:sendBill>
  </soapenv:Body>
</soapenv:Envelope>"""

    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'urn:sendBill',
    }

    logger.info("[RAW_SOAP] Enviando a %s", endpoint_url)
    print(f"[RAW_SOAP] Enviando a {endpoint_url}")

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)

    response = session.post(endpoint_url, data=soap_envelope.encode('utf-8'),
                            headers=headers, timeout=60)

    logger.info("[RAW_SOAP] Status: %d, Body len: %d", response.status_code, len(response.content))
    print(f"[RAW_SOAP] Status: {response.status_code}, Body: {len(response.content)} bytes")

    if response.status_code != 200:
        # Intentar extraer mensaje de error del SOAP fault
        try:
            fault_doc = etree.fromstring(response.content)
            faults = fault_doc.xpath("//*[local-name()='faultstring']")
            if faults and faults[0].text:
                raise Exception(f"SUNAT SOAP Fault: {faults[0].text}")
        except etree.XMLSyntaxError:
            pass
        raise Exception(f"SUNAT HTTP {response.status_code}: {response.text[:500]}")

    # Parsear respuesta SOAP para extraer applicationResponse
    resp_doc = etree.fromstring(response.content)

    app_resp_els = resp_doc.xpath("//*[local-name()='applicationResponse']")
    if app_resp_els and app_resp_els[0].text:
        app_resp_b64 = app_resp_els[0].text.strip()
        logger.info("[RAW_SOAP] applicationResponse encontrado, len=%d", len(app_resp_b64))
        return base64.b64decode(app_resp_b64)

    body_els = resp_doc.xpath("//*[local-name()='Body']")
    if body_els:
        return etree.tostring(body_els[0], encoding='utf-8')

    raise Exception("No se encontró applicationResponse en la respuesta SOAP")


def _extract_meta_from_xml(xml_bytes: bytes) -> dict:
    """Extrae serie, numero y tipo_comprobante del XML UBL."""
    parser = etree.XMLParser(recover=True)
    doc = etree.fromstring(xml_bytes, parser=parser)

    serie, numero = "", ""
    ids = doc.xpath("//*[local-name()='ID']")
    if ids and ids[0].text:
        text = ids[0].text.strip()
        if "-" in text:
            parts = text.split("-", 1)
            serie, numero = parts[0], parts[1]
        else:
            serie = text

    tipo = "01"
    for tag in ["InvoiceTypeCode", "CreditNoteTypeCode", "DebitNoteTypeCode"]:
        els = doc.xpath("//*[local-name()='%s']" % tag)
        el = els[0] if els else None
        if el is not None and el.text:
            tipo = el.text.strip()
            break

    if tipo == "01" and serie:
        prefix2 = serie[:2].upper()
        prefix1 = serie[0].upper()
        if prefix2 == "FC" or prefix2 == "BC":
            tipo = "07"
        elif prefix2 == "FD" or prefix2 == "BD":
            tipo = "08"
        elif prefix1 == "B":
            tipo = "03"

    return {"serie": serie, "numero": numero, "tipo": tipo}


def _parse_cdr(cdr_bytes: bytes) -> dict:
    """Parsea CDR de SUNAT extrayendo código y descripción."""
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

    codigo = find_text(["ResponseCode", "responseCode", "Code", "codigo", "Codigo"])
    descripcion = find_text(["Description", "description", "Descripcion", "descripcion", "Mensaje", "Message"])

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

    # Username SUNAT
    username = f"{emisor_ruc}{sol_usuario}" if sol_usuario else emisor_ruc
    logger.info("WSSE UsernameToken prepared: Username: %s", username)
    print(f"WSSE UsernameToken prepared - Username: {username}")

    # =============================================
    # PRODUCCIÓN: Envío SOAP raw (WSDL incompatible con zeep)
    # =============================================
    if use_production:
        logger.info("[PROD] Usando envío SOAP raw a %s", SUNAT_PROD_URL)
        print(f"[PROD] Enviando SOAP raw a {SUNAT_PROD_URL}")

        last_error = None
        for attempt in range(3):
            try:
                resp_bytes = _send_raw_soap(
                    SUNAT_PROD_URL, username, sol_password,
                    zip_name, content_b64
                )
                cdr_bytes = _try_unzip(resp_bytes)
                parsed = _parse_cdr(cdr_bytes)
                logger.info("CDR: codigo=%s, descripcion=%s", parsed["codigo"], parsed["descripcion"])
                return parsed

            except Exception as e:
                last_error = e
                logger.warning("[PROD] Intento %d/3 falló: %s", attempt + 1, str(e))
                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    logger.info("Esperando %ds antes de reintentar...", wait)
                    time.sleep(wait)

        return {
            "codigo": None,
            "descripcion": str(last_error),
            "cdr_xml": str(last_error).encode("utf-8"),
        }

    # =============================================
    # BETA: Envío con zeep (WSDL compatible)
    # =============================================
    from zeep.wsse.username import UsernameToken
    from zeep.plugins import HistoryPlugin

    wsse = UsernameToken(username, sol_password, use_digest=False) if sol_password else None
    wsdl_url = SUNAT_BETA_WSDL

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

            logger.info("[SOAP] Tipo de respuesta: %s", type(resp))
            print(f"[SOAP] Respuesta tipo: {type(resp)}, valor: {str(resp)[:200]}")

            app_resp = None
            if hasattr(resp, "applicationResponse"):
                app_resp = resp.applicationResponse
            elif isinstance(resp, dict) and "applicationResponse" in resp:
                app_resp = resp["applicationResponse"]
            elif isinstance(resp, bytes):
                app_resp = base64.b64encode(resp).decode('ascii')
                logger.info("[SOAP] Respuesta directa en bytes")

            if app_resp is not None:
                logger.info("[SOAP] applicationResponse len=%d", len(str(app_resp)))
                resp_bytes = base64.b64decode(app_resp)
            else:
                resp_bytes = _extract_from_history(history)

            cdr_bytes = _try_unzip(resp_bytes)
            parsed = _parse_cdr(cdr_bytes)
            logger.info("CDR: codigo=%s, descripcion=%s", parsed["codigo"], parsed["descripcion"])
            return parsed

        except Exception as e:
            last_error = e
            err_text = str(e)
            logger.warning("Intento %d/3 falló: %s", attempt + 1, err_text)

            if "401" in err_text or "Unauthorized" in err_text or "ConnectionError" in err_text:
                global _cached_client
                _cached_client = None
                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    time.sleep(wait)
                    continue

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
            logger.debug("SOAP Request: %s",
                etree.tostring(history.last_sent["envelope"], pretty_print=True).decode())
        if history.last_received:
            logger.debug("SOAP Response: %s",
                etree.tostring(history.last_received["envelope"], pretty_print=True).decode())
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


# =====================================================================
# RESUMEN DIARIO (sendSummary / getStatus) — SOAP raw, beta y producción
# =====================================================================

def _send_raw_summary(endpoint_url: str, username: str, password: str,
                      zip_name: str, content_b64: str) -> str:
    """Envía sendSummary y retorna el ticket que devuelve SUNAT."""
    import requests

    soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ser="http://service.sunat.gob.pe"
                  xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header>
    <wsse:Security>
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password>{password}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <ser:sendSummary>
      <fileName>{zip_name}</fileName>
      <contentFile>{content_b64}</contentFile>
    </ser:sendSummary>
  </soapenv:Body>
</soapenv:Envelope>"""

    print(f"[SUMMARY-SOAP] Envelope completo:\n{soap_envelope[:1000]}")

    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': '"urn:sendSummary"',
    }

    logger.info("[RAW_SUMMARY] Enviando a %s", endpoint_url)
    print(f"[RAW_SUMMARY] Enviando a {endpoint_url}")

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)

    response = session.post(endpoint_url, data=soap_envelope.encode('utf-8'),
                            headers=headers, timeout=60)

    logger.info("[RAW_SUMMARY] Status: %d, Body len: %d", response.status_code, len(response.content))
    print(f"[RAW_SUMMARY] Status: {response.status_code}, Body: {len(response.content)} bytes")

    if response.status_code != 200:
        try:
            fault_doc = etree.fromstring(response.content)
            faults = fault_doc.xpath("//*[local-name()='faultstring']")
            if faults and faults[0].text:
                raise Exception(f"SUNAT SOAP Fault: {faults[0].text}")
        except etree.XMLSyntaxError:
            pass
        raise Exception(f"SUNAT HTTP {response.status_code}: {response.text[:500]}")

    # Preview del body para diagnóstico
    try:
        body_preview = response.content.decode('utf-8', errors='replace')
    except Exception:
        body_preview = str(response.content)
    logger.info("[RAW_SUMMARY] Body completo:\n%s", body_preview)
    print(f"[RAW_SUMMARY] Body completo ({len(response.content)} bytes):\n{body_preview}")

    try:
        resp_doc = etree.fromstring(response.content)
    except Exception as e:
        logger.error("[RAW_SUMMARY] No se pudo parsear XML: %s", e)
        print(f"[RAW_SUMMARY] ❌ No se pudo parsear XML: {e}")
        raise Exception(f"sendSummary respondió cuerpo no-XML: {body_preview[:500]}")

    ticket_els = resp_doc.xpath("//*[local-name()='ticket']")
    if ticket_els and ticket_els[0].text:
        ticket = ticket_els[0].text.strip()
        logger.info("[RAW_SUMMARY] ticket=%s", ticket)
        return ticket

    # Extraer SOAP fault si lo hay (SUNAT a veces lo manda con HTTP 200)
    fault_strs = resp_doc.xpath("//*[local-name()='faultstring']")
    fault_codes = resp_doc.xpath("//*[local-name()='faultcode']")
    fault_msg = fault_strs[0].text.strip() if fault_strs and fault_strs[0].text else None
    fault_code = fault_codes[0].text.strip() if fault_codes and fault_codes[0].text else None

    if fault_msg or fault_code:
        msg = f"SUNAT SOAP Fault [{fault_code}]: {fault_msg}"
        logger.error("[RAW_SUMMARY] %s", msg)
        print(f"[RAW_SUMMARY] ❌ {msg}")
        raise Exception(msg)

    # Listar todos los tags presentes para debug
    all_tags = sorted(set(
        el.tag.split('}')[-1] if '}' in el.tag else el.tag
        for el in resp_doc.iter()
    ))
    logger.error("[RAW_SUMMARY] Tags en respuesta: %s", all_tags)
    print(f"[RAW_SUMMARY] Tags en respuesta: {all_tags}")

    raise Exception(
        f"No se encontró <ticket> ni <faultstring> en la respuesta de sendSummary. "
        f"Tags presentes: {all_tags}. Body: {body_preview[:500]}"
    )


def _send_raw_get_status(endpoint_url: str, username: str, password: str,
                         ticket: str) -> bytes:
    """Llama a getStatus(ticket). Si SUNAT ya tiene CDR, retorna los bytes del CDR XML.
    Si el ticket aún está en proceso, lanza Exception con el statusCode."""
    import requests

    soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ser="http://service.sunat.gob.pe"
                  xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header>
    <wsse:Security>
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password>{password}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <ser:getStatus>
      <ticket>{ticket}</ticket>
    </ser:getStatus>
  </soapenv:Body>
</soapenv:Envelope>"""

    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': '"urn:getStatus"',
    }

    logger.info("[RAW_GETSTATUS] ticket=%s endpoint=%s", ticket, endpoint_url)
    print(f"[RAW_GETSTATUS] ticket={ticket}")

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)

    response = session.post(endpoint_url, data=soap_envelope.encode('utf-8'),
                            headers=headers, timeout=60)

    logger.info("[RAW_GETSTATUS] Status: %d, Body len: %d", response.status_code, len(response.content))

    if response.status_code != 200:
        try:
            fault_doc = etree.fromstring(response.content)
            faults = fault_doc.xpath("//*[local-name()='faultstring']")
            if faults and faults[0].text:
                raise Exception(f"SUNAT SOAP Fault: {faults[0].text}")
        except etree.XMLSyntaxError:
            pass
        raise Exception(f"SUNAT HTTP {response.status_code}: {response.text[:500]}")

    resp_doc = etree.fromstring(response.content)

    # statusCode: 0 = procesado y aceptado (CDR adjunto)
    #             98 = en proceso (reintentar)
    #             99 = procesado con errores (CDR adjunto con rechazo)
    status_els = resp_doc.xpath("//*[local-name()='statusCode']")
    status_code = status_els[0].text.strip() if status_els and status_els[0].text else None
    logger.info("[RAW_GETSTATUS] statusCode=%s", status_code)

    if status_code == '98':
        raise Exception(f"TICKET_PENDING: ticket {ticket} aun en proceso (statusCode=98)")

    content_els = resp_doc.xpath("//*[local-name()='content']")
    if content_els and content_els[0].text:
        content_b64 = content_els[0].text.strip()
        return base64.b64decode(content_b64)

    # Diagnóstico: loguear body si no hay <content>
    try:
        body_preview = response.content.decode('utf-8', errors='replace')
    except Exception:
        body_preview = str(response.content)
    logger.error("[RAW_GETSTATUS] Sin <content>; body:\n%s", body_preview)
    print(f"[RAW_GETSTATUS] ❌ Sin <content>; body ({len(response.content)} bytes):\n{body_preview}")

    fault_strs = resp_doc.xpath("//*[local-name()='faultstring']")
    if fault_strs and fault_strs[0].text:
        raise Exception(f"SUNAT SOAP Fault en getStatus: {fault_strs[0].text.strip()}")

    raise Exception(f"getStatus sin <content>; statusCode={status_code}; body={body_preview[:500]}")


def enviar_resumen_diario(
    xml_firmado: bytes,
    emisor_ruc: str,
    fecha: str,
    correlativo: int,
    sol_usuario: str,
    sol_password: str,
    use_production: bool = False,
) -> dict:
    """Envía Resumen Diario de Boletas (RC) a SUNAT.

    Args:
        xml_firmado: XML SummaryDocuments-1.1 firmado.
        emisor_ruc: RUC del emisor.
        fecha: 'YYYY-MM-DD' — fecha de las boletas (ReferenceDate).
        correlativo: 1, 2, 3... del día.
        sol_usuario, sol_password: credenciales SOL.
        use_production: True para producción, False para beta.

    Returns:
        { ticket, zip_name }
    """
    fecha_compact = fecha.replace('-', '')
    base_name = f"{emisor_ruc}-RC-{fecha_compact}-{str(correlativo).zfill(5)}"
    xml_name = f"{base_name}.xml"
    zip_name = f"{base_name}.zip"

    logger.info("Preparando envío Resumen Diario: %s", zip_name)

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_name, xml_firmado)
    zipped = buf.getvalue()
    content_b64 = base64.b64encode(zipped).decode("ascii")

    username = f"{emisor_ruc}{sol_usuario}" if sol_usuario else emisor_ruc
    endpoint_url = SUNAT_PROD_SUMMARY_URL if use_production else SUNAT_BETA_SUMMARY_URL

    logger.info("[SUMMARY] Endpoint: %s, username=%s", endpoint_url, username)
    print(f"[SUMMARY] Enviando {zip_name} a {endpoint_url}")

    last_error = None
    for attempt in range(3):
        try:
            ticket = _send_raw_summary(
                endpoint_url, username, sol_password,
                zip_name, content_b64,
            )
            return {"ticket": ticket, "zip_name": zip_name}
        except Exception as e:
            last_error = e
            logger.warning("[SUMMARY] Intento %d/3 falló: %s", attempt + 1, str(e))
            if attempt < 2:
                wait = 3 * (attempt + 1)
                time.sleep(wait)

    raise Exception(f"sendSummary falló tras 3 intentos: {last_error}")


def consultar_ticket_resumen(
    ticket: str,
    emisor_ruc: str,
    sol_usuario: str,
    sol_password: str,
    use_production: bool = False,
) -> dict:
    """Consulta el estado de un ticket de Resumen Diario.

    Returns:
        Dict con estructura igual a la de sendBill:
            { codigo, descripcion, cdr_xml }
        Si el ticket aún está en proceso, retorna:
            { codigo: None, descripcion: 'PENDING', cdr_xml: None, pending: True }
    """
    username = f"{emisor_ruc}{sol_usuario}" if sol_usuario else emisor_ruc
    endpoint_url = SUNAT_PROD_SUMMARY_URL if use_production else SUNAT_BETA_SUMMARY_URL

    try:
        resp_bytes = _send_raw_get_status(endpoint_url, username, sol_password, ticket)
    except Exception as e:
        if str(e).startswith("TICKET_PENDING"):
            return {"codigo": None, "descripcion": "PENDING", "cdr_xml": None, "pending": True}
        raise

    cdr_bytes = _try_unzip(resp_bytes)
    parsed = _parse_cdr(cdr_bytes)
    parsed["pending"] = False
    return parsed