"""
Tarea Celery para envío de comprobantes a SUNAT.
Usa el nuevo xml_generator.py con estructura UBL 2.1 completa.
"""
from src.tasks.celery_app import celery_app
from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, Certificado, RespuestaSunat, LogEnvio, ResumenDiario
from src.core.config import settings
from src.services.xml_generator import build_invoice_xml
from src.services.firma_digital import firmar_xml
from src.services.sunat_client import enviar_comprobante, consultar_ticket_resumen, consultar_estado_cdr
from src.services.notificaciones_sunat import (
    clasificar_error_sunat,
    clasificar_error_a2,
    decidir_reintento,
    gate_reenvio,
    notificar_reintento_temporal,
    notificar_resuelto,
    notificar_fallo_definitivo,
)
from cryptography.fernet import Fernet
import traceback
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
PERU_TZ = timezone(timedelta(hours=-5))

# A2 — Reintento automático en SEGUNDO PLANO (Celery). Backoff en SEGUNDOS (30s → 2min → 5min),
# máximo MAX_REINTENTOS. La verificación anti-duplicado (getStatusCdr) se hace al inicio del task
# antes de cada reenvío. NO bloquea al usuario.
BACKOFF_SEGUNDOS = [30, 120, 300]
MAX_REINTENTOS = 3

# A2 — Gate anti-duplicado por getStatusCdr: PAUSADO. getStatusCdr (billConsultService) NO existe
# en SUNAT beta y NO cubre boletas (solo facturas/NC/ND), así que no se puede validar ni sirve para
# boletas. El reintento sigue siendo seguro sin él: reusa el MISMO correlativo y SUNAT deduplica
# (reenviar algo ya registrado devuelve 1033 → se marca aceptado; NUNCA crea otro documento).
# PENDIENTE: rediseñar (getStatusCdr solo-prod + alternativa para boletas) y reactivar con True.
A2_ANTIDUP_GETSTATUSCDR_ACTIVO = False


def _sol_plain(emisor):
    """Desencripta la clave SOL (para getStatusCdr). None si el emisor no la tiene."""
    if not getattr(emisor, 'sol_password', None):
        return None
    try:
        f = Fernet(settings.encryption_key.encode())
        return f.decrypt(emisor.sol_password.encode()).decode()
    except Exception:
        return emisor.sol_password


def _emisor_tiene_aceptados(db, emisor_id, excluir_id=None):
    """True si el emisor ya tiene algún comprobante aceptado (historial ⇒ el permiso SOL existe).
    Usado para desambiguar los faults de perfil (Client.01xx)."""
    q = db.query(Comprobante).filter(
        Comprobante.emisor_id == emisor_id,
        Comprobante.estado.in_(('aceptado', 'aceptado_con_observaciones')),
    )
    if excluir_id:
        q = q.filter(Comprobante.id != excluir_id)
    return bool(db.query(q.exists()).scalar())


def _guardar_cdr_desde_getstatus(comp, db, est, aceptado):
    """Guarda el CDR real obtenido por getStatusCdr y fija el estado del comprobante."""
    try:
        db.add(RespuestaSunat(
            comprobante_id=comp.id,
            codigo_cdr=str(est.get('codigo') or ''),
            descripcion=est.get('descripcion') or '',
            cdr_xml=est.get('cdr_xml'),
        ))
    except Exception:
        pass
    cod = str(est.get('codigo') or '')
    if aceptado:
        comp.estado = 'aceptado_con_observaciones' if cod.startswith('2') else 'aceptado'
    else:
        comp.estado = 'rechazado'
    comp.procesando_desde = None
    comp.descripcion_respuesta = (est.get('descripcion') or 'Estado obtenido de SUNAT (getStatusCdr)')[:500]
    db.commit()


def _anti_duplicado_detener(comp, emisor, db):
    """GARANTÍA ANTI-DUPLICADO. A partir del 2º intento consulta getStatusCdr ANTES de reenviar.
    Devuelve True = DETENER (ya resuelto en SUNAT, o incierto → no reenviar).
    Devuelve False = seguro (re)enviar. Solo reenvía cuando SUNAT confirma 'no_existe'."""
    if (comp.intentos_envio or 0) < 1:
        return False  # 1er intento: nunca se envió → no hay riesgo de duplicar

    est = consultar_estado_cdr(
        emisor.ruc, comp.tipo_documento, comp.serie, comp.numero,
        sol_usuario=emisor.sol_usuario, sol_password=_sol_plain(emisor),
        use_production=getattr(emisor, 'produccion', False),
    )
    decision = gate_reenvio(est.get('estado'), comp.intentos_envio or 0)
    logger.info("A2 anti-dup %s-%s estado_sunat=%s decision=%s",
                comp.serie, comp.numero, est.get('estado'), decision)

    if decision == 'detenido_aceptado':
        _guardar_cdr_desde_getstatus(comp, db, est, aceptado=True)
        print(f"🛡️ ANTI-DUP {comp.serie}-{comp.numero}: SUNAT YA lo tiene ACEPTADO — NO se reenvía")
        return True
    if decision == 'detenido_rechazado':
        _guardar_cdr_desde_getstatus(comp, db, est, aceptado=False)
        print(f"🛡️ ANTI-DUP {comp.serie}-{comp.numero}: SUNAT lo tiene RECHAZADO — NO se reenvía")
        return True
    if decision == 'incierto':
        # No se pudo verificar → NO reenviar (conservador). Reprogramar acotado; si se agota, revisión.
        comp.intentos_envio = (comp.intentos_envio or 0) + 1
        if comp.intentos_envio < MAX_REINTENTOS:
            seg = BACKOFF_SEGUNDOS[min(comp.intentos_envio, len(BACKOFF_SEGUNDOS) - 1)]
            comp.estado = 'reintentando'
            comp.descripcion_respuesta = f"No se pudo verificar estado en SUNAT; reintentando en {seg}s"[:500]
            db.commit()
            try:
                celery_app.send_task('enviar_comprobante_sunat', args=[str(comp.id)], countdown=seg)
            except Exception as e:
                logger.exception("No se pudo encolar reintento (incierto): %s", e)
        else:
            comp.estado = 'error'
            comp.descripcion_respuesta = ("No se pudo verificar el estado en SUNAT tras varios "
                                          "intentos; revisar manualmente")[:500]
            db.commit()
        print(f"🛡️ ANTI-DUP {comp.serie}-{comp.numero}: estado INCIERTO — NO se reenvía")
        return True

    return False  # 'proceder': SUNAT confirma que NO lo tiene → seguro reenviar


def _programar_reintento_o_fallo(comp, emisor, db, codigo: str, mensaje: str):
    """A2: clasifica la causa (clasificar_error_a2) y decide (decidir_reintento). Reintenta con
    backoff corto en segundo plano, o marca rechazado con motivo claro. El anti-duplicado se hace
    al inicio del task (getStatusCdr) antes de cada reenvío. Llamar tras incrementar intentos_envio."""
    categoria = clasificar_error_a2(codigo, mensaje)
    intentos = comp.intentos_envio or 0
    # getStatusCdr PAUSADO → perfil no usa historial; se pasa False (reservado para el rediseño).
    accion = decidir_reintento(categoria, intentos, False, MAX_REINTENTOS)

    logger.info("A2 %s-%s cat=%s accion=%s intentos=%d codigo=%s",
                comp.serie, comp.numero, categoria, accion, intentos, codigo)
    print(f"[A2] {comp.serie}-{comp.numero} cat={categoria} accion={accion} intentos={intentos} codigo={codigo}")

    # 1033 "registrado previamente": SUNAT YA lo tiene registrado → marcar ACEPTADO, NO reenviar.
    # (getStatusCdr PAUSADO: no recuperamos el CDR real todavía; queda pendiente para el rediseño.)
    if accion == 'marcar_aceptado':
        comp.estado = 'aceptado'
        comp.procesando_desde = None
        comp.descripcion_respuesta = ("SUNAT reporta que el comprobante ya estaba registrado "
                                      "(código 1033) — se marca aceptado. CDR pendiente de recuperar.")[:500]
        db.commit()
        # Hook de stock idempotente (no-fatal), igual que en la aceptación normal.
        try:
            from src.services.stock_service import descontar_por_comprobante
            descontar_por_comprobante(db, comp.id)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        logger.info("A2 %s-%s 1033 → aceptado (ya registrado en SUNAT, sin CDR)", comp.serie, comp.numero)
        print(f"✅ A2 {comp.serie}-{comp.numero}: SUNAT ya lo tenía registrado (1033) → ACEPTADO")
        return 'aceptado_1033'

    if accion == 'reintentar':
        seg = BACKOFF_SEGUNDOS[min(intentos, len(BACKOFF_SEGUNDOS) - 1)]
        comp.estado = 'reintentando'
        comp.procesando_desde = None
        comp.descripcion_respuesta = (f"[{categoria} {codigo or '?'}] reintento {intentos + 1}/"
                                      f"{MAX_REINTENTOS} en {seg}s — {mensaje}")[:500]
        db.commit()
        try:
            celery_app.send_task('enviar_comprobante_sunat', args=[str(comp.id)], countdown=seg)
        except Exception as e:
            logger.exception("No se pudo encolar reintento: %s", e)
        notificar_reintento_temporal(comp, emisor, codigo, intentos, MAX_REINTENTOS, max(seg // 60, 1))
        return 'retry_scheduled'

    # Rechazos: 'rechazar' | 'rechazar_perfil' | 'rechazar_revision'
    comp.estado = 'rechazado'
    comp.procesando_desde = None
    if accion == 'rechazar_perfil':
        comp.descripcion_respuesta = (f"{mensaje} — verificar permisos SOL del usuario secundario")[:500]
    elif accion == 'rechazar_revision':
        comp.descripcion_respuesta = (f"[revisar] {mensaje}")[:500]
    else:
        comp.descripcion_respuesta = (mensaje or '')[:500]
    db.commit()

    logger.info("A2 FALLO %s-%s cat=%s accion=%s codigo=%s", comp.serie, comp.numero, categoria, accion, codigo)
    print(f"🛑 A2 RECHAZADO {comp.serie}-{comp.numero} accion={accion} codigo={codigo}")
    notificar_fallo_definitivo(comp, emisor, categoria, codigo)
    return 'terminal'


def _desencriptar(fernet, valor_encriptado):
    """Desencripta un valor con Fernet. Retorna bytes."""
    if isinstance(valor_encriptado, str):
        return fernet.decrypt(valor_encriptado.encode())
    return fernet.decrypt(valor_encriptado)


def _build_comprobante_xml_obj(comp):
    """Construye objeto con todos los datos del comprobante para el XML generator."""

    class ComprobanteXML:
        pass

    obj = ComprobanteXML()
    obj.tipo_documento = comp.tipo_documento
    obj.serie = comp.serie
    obj.numero = comp.numero
    obj.fecha_emision = comp.fecha_emision
    obj.moneda = comp.moneda or 'PEN'

    # Datos del cliente
    obj.cliente_tipo_documento = comp.cliente_tipo_documento
    obj.cliente_numero_documento = comp.cliente_numero_documento
    obj.cliente_razon_social = comp.cliente_razon_social
    obj.cliente_direccion = getattr(comp, 'cliente_direccion', '') or ''

    # Datos de NC/ND
    obj.motivo_nota = getattr(comp, 'motivo_nota', '01')
    obj.doc_referencia_tipo = getattr(comp, 'doc_referencia_tipo', '01')
    obj.doc_referencia_numero = getattr(comp, 'doc_referencia_numero', '')

    # Detracción (SPOT): columnas del comprobante -> el generador respeta la decisión guardada
    obj.detraccion_codigo_bien = getattr(comp, 'detraccion_codigo_bien', None)
    obj.detraccion_porcentaje = getattr(comp, 'detraccion_porcentaje', None)
    obj.detraccion_monto = getattr(comp, 'detraccion_monto', None)

    # Items con tipo de afectación IGV
    class ItemXML:
        pass

    items = []
    for linea in comp.lineas:
        item = ItemXML()
        item.orden = linea.orden
        item.descripcion = linea.descripcion or ''
        item.cantidad = linea.cantidad
        item.unidad = linea.unidad or 'NIU'
        item.precio_unitario = linea.precio_unitario
        item.tipo_afectacion_igv = getattr(linea, 'tipo_afectacion_igv', '10') or '10'
        items.append(item)

    obj.items = items
    return obj


def _build_emisor_dict(emisor) -> dict:
    """Construye dict con datos del emisor para el XML generator."""
    return {
        'ruc': emisor.ruc,
        'razon_social': emisor.razon_social,
        'nombre_comercial': getattr(emisor, 'nombre_comercial', '') or emisor.razon_social,
        'direccion': getattr(emisor, 'direccion', '') or '',
        'ubigeo': getattr(emisor, 'ubigeo', '') or '',
        'departamento': getattr(emisor, 'departamento', '') or '',
        'provincia': getattr(emisor, 'provincia', '') or '',
        'distrito': getattr(emisor, 'distrito', '') or '',
        # Para leyenda Amazonía (cat.52 / 2002) en el generador XML
        'es_amazonia': bool((getattr(emisor, 'config_json', None) or {}).get('es_amazonia', False)),
        # Detracción (SPOT): claves aditivas; None si el emisor no la usa -> XML sin cambios
        'detraccion': (getattr(emisor, 'config_json', None) or {}).get('detraccion'),
        'cuenta_detraccion': getattr(emisor, 'cuenta_detraccion', None),
    }


@celery_app.task(name='enviar_comprobante_sunat', bind=True, max_retries=0)
def enviar_comprobante_task(self, comprobante_id: str):
    """
    Tarea asíncrona para procesar y enviar comprobante a SUNAT.
    1. Genera XML UBL 2.1 completo
    2. Firma con certificado digital
    3. Envía a SUNAT (beta o producción)
    4. Guarda CDR
    """
    db = SessionLocal()
    logger.info(f"enviar_comprobante_sunat START id={comprobante_id}")
    print(f"📤 enviar_comprobante_sunat START id={comprobante_id}")

    try:
        # ============================
        # CARGAR COMPROBANTE Y EMISOR
        # ============================
        comp = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
        if not comp:
            logger.error(f"Comprobante {comprobante_id} no encontrado")
            return {"exito": False, "error": "Comprobante no encontrado"}

        emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
        if not emisor:
            comp.estado = 'error'
            db.commit()
            logger.error(f"Emisor no encontrado para comprobante {comprobante_id}")
            return {"exito": False, "error": "Emisor no encontrado"}

        comp.estado = 'enviando'
        db.commit()

        # ============================
        # A2 — ANTI-DUPLICADO por getStatusCdr: PAUSADO (A2_ANTIDUP_GETSTATUSCDR_ACTIVO=False).
        # getStatusCdr no existe en beta y no cubre boletas → se reactiva tras el rediseño.
        # (El código de _anti_duplicado_detener queda intacto para retomarlo.)
        # ============================
        if A2_ANTIDUP_GETSTATUSCDR_ACTIVO and _anti_duplicado_detener(comp, emisor, db):
            return {
                "exito": comp.estado in ('aceptado', 'aceptado_con_observaciones'),
                "estado": comp.estado,
                "id": comprobante_id,
            }

        # ============================
        # OBTENER CERTIFICADO
        # ============================
        certificado = db.query(Certificado).filter_by(
            emisor_id=emisor.id, activo=True
        ).order_by(Certificado.creado_en.desc()).first()

        if not certificado:
            comp.estado = 'error'
            comp.descripcion_respuesta = 'Certificado digital no encontrado'
            db.commit()
            logger.error(f"Certificado no encontrado para emisor {emisor.ruc}")
            return {"exito": False, "error": "Certificado no encontrado"}

        # Desencriptar PFX y contraseña
        try:
            f = Fernet(settings.encryption_key.encode())
            pfx_bytes = _desencriptar(f, certificado.pfx_encriptado)
            password = _desencriptar(f, certificado.password_encriptado).decode()
        except Exception as e:
            comp.estado = 'error'
            comp.descripcion_respuesta = f'Error desencriptando certificado: {e}'
            db.commit()
            logger.exception("Error desencriptando certificado")
            return {"exito": False, "error": f"Error certificado: {e}"}

        # ============================
        # GENERAR XML + FIRMAR
        # ============================
        try:
            comp_xml = _build_comprobante_xml_obj(comp)
            emisor_dict = _build_emisor_dict(emisor)

            print(f"📝 Generando XML para {comp.serie}-{comp.numero} tipo={comp.tipo_documento}")
            xml_bytes = build_invoice_xml(comp_xml, emisor_dict)

            print(f"🔏 Firmando XML...")
            signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)

            # Guardar XML firmado
            comp.xml = signed_xml
            db.commit()

            logger.info(f"XML firmado OK para {comp.serie}-{comp.numero}")
            print(f"✅ XML firmado OK ({len(signed_xml)} bytes)")

        except Exception as e:
            tb = traceback.format_exc()
            logger.exception("Error generando/firmando XML")
            print(f"❌ Error XML: {e}\n{tb}")

            comp.estado = 'rechazado'
            comp.descripcion_respuesta = f'Error XML: {e}'
            db.commit()

            # Guardar error como RespuestaSunat para visibilidad
            try:
                respuesta = RespuestaSunat(
                    comprobante_id=comp.id, codigo_cdr='',
                    descripcion=str(e), cdr_xml=tb.encode('utf-8')
                )
                db.add(respuesta)
                db.commit()
            except Exception:
                pass

            return {"exito": False, "error": f"Error XML: {e}"}

        # ============================
        # ENVIAR A SUNAT
        # ============================
        try:
            # Desencriptar clave SOL
            sol_password_plain = None
            if emisor.sol_password:
                try:
                    f2 = Fernet(settings.encryption_key.encode())
                    sol_password_plain = f2.decrypt(emisor.sol_password.encode()).decode()
                    logger.info("SOL password desencriptada OK")
                except Exception:
                    logger.warning("SOL password no encriptada, usando tal cual")
                    sol_password_plain = emisor.sol_password

            username_log = f"{emisor.ruc}{emisor.sol_usuario}" if emisor.sol_usuario else None
            print(f"📡 Enviando a SUNAT - Username: {username_log}")

            _prod_flag = getattr(emisor, 'produccion', False)
            print(f"🔧 PRODUCCION FLAG: {_prod_flag} (tipo: {type(_prod_flag)})")

            cdr = enviar_comprobante(
                signed_xml, emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=sol_password_plain,
                use_production=getattr(emisor, 'produccion', False)
            )

            print(f"📨 CDR recibido: codigo={cdr.get('codigo')}, desc={cdr.get('descripcion')}")

        except Exception as e:
            err_text = str(e)
            logger.exception(f"Error enviando a SUNAT: {err_text}")
            print(f"❌ Error SUNAT: {err_text}")

            # Guardar error como RespuestaSunat (visibilidad)
            try:
                respuesta = RespuestaSunat(
                    comprobante_id=comp.id, codigo_cdr='',
                    descripcion=err_text, cdr_xml=err_text.encode('utf-8')
                )
                db.add(respuesta)
                db.commit()
            except Exception:
                pass

            # Excepción de red/cliente → tratar como transitorio
            comp.intentos_envio = (comp.intentos_envio or 0) + 1
            comp.ultimo_intento_envio = datetime.now(timezone.utc)
            _programar_reintento_o_fallo(
                comp, emisor, db, codigo='', mensaje=err_text,
            )
            return {"exito": False, "error": err_text}

        # ============================
        # GUARDAR CDR
        # ============================
        try:
            respuesta = RespuestaSunat(
                comprobante_id=comp.id,
                codigo_cdr=str(cdr.get('codigo') or ''),
                descripcion=cdr.get('descripcion') or '',
                cdr_xml=cdr.get('cdr_xml')
            )
            db.add(respuesta)

            codigo = str(cdr.get('codigo') or '')
            descripcion_cdr = cdr.get('descripcion') or ''

            # Extraer DigestValue del XML firmado (= RESUMEN del CPE)
            try:
                from lxml import etree
                doc = etree.fromstring(signed_xml)
                digest_els = doc.xpath("//*[local-name()='DigestValue']")
                if digest_els and digest_els[0].text:
                    comp.hash_cpe = digest_els[0].text.strip()
                    logger.info(f"Hash CPE (DigestValue): {comp.hash_cpe}")
            except Exception as e:
                logger.warning(f"No se pudo extraer DigestValue: {e}")

            intentos_previos = comp.intentos_envio or 0

            if codigo == '0' or codigo.startswith('2'):
                # Éxito (aceptado o aceptado con observaciones)
                comp.estado = 'aceptado' if codigo == '0' else 'aceptado_con_observaciones'
                comp.intentos_envio = intentos_previos + 1
                comp.ultimo_intento_envio = datetime.now(timezone.utc)
                comp.procesando_desde = None
                db.commit()

                # Hook no-fatal: descontar stock al quedar aceptada.
                try:
                    from src.services.stock_service import descontar_por_comprobante
                    descontar_por_comprobante(db, comp.id)
                except Exception as _e:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.warning("[STOCK] Descuento no-fatal falló para %s: %s", comp.id, _e)

                if codigo == '0':
                    print(f"✅ {comp.serie}-{comp.numero} ACEPTADO por SUNAT")
                else:
                    print(f"⚠️ {comp.serie}-{comp.numero} ACEPTADO CON OBSERVACIONES")

                # Si veníamos de reintentos, avisar que se resolvió
                if intentos_previos > 0:
                    notificar_resuelto(comp, emisor)
            else:
                # Rechazo SUNAT → clasificar y decidir reintento vs terminal
                comp.intentos_envio = intentos_previos + 1
                comp.ultimo_intento_envio = datetime.now(timezone.utc)
                db.commit()

                print(f"❌ {comp.serie}-{comp.numero} RECHAZO {codigo}: {descripcion_cdr}")

                _programar_reintento_o_fallo(
                    comp, emisor, db,
                    codigo=codigo, mensaje=descripcion_cdr,
                )

        except Exception as e:
            logger.exception("Error guardando CDR")
            comp.estado = 'error'
            comp.descripcion_respuesta = f'Error guardando CDR: {e}'
            db.commit()
            return {"exito": False, "error": f"Error CDR: {e}"}

        return {
            "exito": comp.estado in ('aceptado', 'aceptado_con_observaciones'),
            "estado": comp.estado,
            "mensaje": cdr.get('descripcion', ''),
            "id": comprobante_id
        }

    except Exception as e:
        logger.exception(f"Error general en enviar_comprobante_sunat: {e}")
        print(f"❌ Error general: {e}")

        try:
            comp = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
            if comp:
                comp.estado = 'error'
                comp.descripcion_respuesta = str(e)
                db.commit()
        except Exception:
            pass

        return {"exito": False, "error": str(e)}

    finally:
        db.close()


# =====================================================================
# RESUMEN DIARIO — polling de ticket (getStatus)
# =====================================================================

@celery_app.task(name='consultar_ticket_resumen', bind=True, max_retries=10)
def consultar_ticket_resumen_task(self, resumen_id: str):
    """Consulta el ticket de un Resumen Diario en SUNAT cada 30s hasta tener CDR.

    - codigo='0'  → estado='aceptado' y boletas incluidas → 'autorizado'
    - codigo!='0' (rechazo)  → estado='rechazado' y boletas vuelven a 'aceptado'
    - pending → reintentar con countdown=30
    """
    from celery.exceptions import Retry

    db = SessionLocal()
    logger.info("consultar_ticket_resumen START id=%s (try %d)", resumen_id, self.request.retries)
    print(f"🎫 consultar_ticket_resumen id={resumen_id} (intento {self.request.retries + 1})")

    try:
        resumen = db.query(ResumenDiario).filter(ResumenDiario.id == resumen_id).first()
        if not resumen:
            logger.error("ResumenDiario %s no encontrado", resumen_id)
            return {"exito": False, "error": "ResumenDiario no encontrado"}

        emisor = db.query(Emisor).filter(Emisor.id == resumen.emisor_id).first()
        if not emisor:
            resumen.estado = 'error'
            resumen.descripcion_sunat = 'Emisor no encontrado'
            db.commit()
            return {"exito": False, "error": "Emisor no encontrado"}

        # Desencriptar SOL password
        sol_password_plain = None
        if emisor.sol_password:
            try:
                f = Fernet(settings.encryption_key.encode())
                sol_password_plain = f.decrypt(emisor.sol_password.encode()).decode()
            except Exception:
                sol_password_plain = emisor.sol_password

        # Llamada a SUNAT — los errores HTTP bajan al except inferior
        try:
            cdr = consultar_ticket_resumen(
                ticket=resumen.ticket,
                emisor_ruc=emisor.ruc,
                sol_usuario=emisor.sol_usuario or '',
                sol_password=sol_password_plain or '',
                use_production=getattr(emisor, 'produccion', False),
            )
        except Retry:
            raise
        except Exception as e:
            logger.exception("Error consultando ticket %s: %s", resumen.ticket, e)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e, countdown=30)
            resumen.estado = 'error'
            resumen.descripcion_sunat = str(e)[:500]
            db.commit()
            return {"exito": False, "error": str(e)}

        # Pending → reintentar
        if cdr.get("pending"):
            logger.info("Ticket %s aún pendiente — reintentando en 30s", resumen.ticket)
            print(f"⏳ Ticket {resumen.ticket} pendiente — reintentando en 30s")
            if self.request.retries < self.max_retries:
                raise self.retry(countdown=30)
            resumen.estado = 'timeout'
            resumen.descripcion_sunat = 'Ticket no resuelto tras 10 reintentos'
            db.commit()
            return {"exito": False, "error": "Timeout esperando CDR"}

        # CDR recibido → guardar y actualizar boletas
        codigo = str(cdr.get('codigo') or '')
        descripcion = cdr.get('descripcion') or ''
        cdr_xml = cdr.get('cdr_xml')

        resumen.codigo_sunat = codigo
        resumen.descripcion_sunat = descripcion
        resumen.cdr_xml = cdr_xml

        # Boletas incluidas: las que quedaron en estado 'en_resumen' para esa fecha+emisor
        boletas_en_resumen = db.query(Comprobante).filter(
            Comprobante.emisor_id == resumen.emisor_id,
            Comprobante.tipo_documento == '03',
            Comprobante.fecha_emision == resumen.fecha_referencia,
            Comprobante.estado == 'en_resumen',
        ).all()

        if codigo == '0':
            resumen.estado = 'aceptado'
            for b in boletas_en_resumen:
                b.estado = 'autorizado'
            print(f"✅ Resumen {resumen.id} ACEPTADO — {len(boletas_en_resumen)} boletas autorizadas")
        else:
            resumen.estado = 'rechazado'
            # Restaurar boletas para reintento manual
            for b in boletas_en_resumen:
                b.estado = 'aceptado'
            print(f"❌ Resumen {resumen.id} RECHAZADO ({codigo}): {descripcion}")

        db.commit()
        return {
            "exito": codigo == '0',
            "estado": resumen.estado,
            "codigo": codigo,
            "descripcion": descripcion,
        }

    finally:
        db.close()