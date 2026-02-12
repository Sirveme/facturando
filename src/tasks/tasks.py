from .celery_app import celery_app
from src.models.models import Comprobante, Emisor, Certificado, RespuestaSunat, LogEnvio
from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.services.xml_generator import build_invoice_xml
from src.services.firma_digital import firmar_xml
from src.services.sunat_client import enviar_comprobante
from cryptography.fernet import Fernet
import traceback
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Zona horaria Perú
PERU_TZ = timezone(timedelta(hours=-5))


def _desencriptar_sol_password(emisor) -> str | None:
    """Desencripta la clave SOL del emisor. Retorna None si no tiene."""
    if not emisor.sol_password:
        return None
    try:
        f = Fernet(settings.encryption_key.encode())
        return f.decrypt(emisor.sol_password.encode()).decode()
    except Exception:
        logger.warning("SOL password no encriptada o error al desencriptar, usando tal cual")
        return emisor.sol_password


def _build_emisor_dict(emisor) -> dict:
    """Construye dict con datos del emisor para el XML generator."""
    return {
        'ruc': emisor.ruc,
        'razon_social': emisor.razon_social,
        'nombre_comercial': getattr(emisor, 'nombre_comercial', '') or emisor.razon_social,
        'direccion': getattr(emisor, 'direccion', '') or '',
        'ubigeo': getattr(emisor, 'ubigeo', '150101') or '150101',
        'departamento': getattr(emisor, 'departamento', '') or '',
        'provincia': getattr(emisor, 'provincia', '') or '',
        'distrito': getattr(emisor, 'distrito', '') or '',
    }


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

    # Datos de NC/ND (si aplica)
    obj.motivo_nota = getattr(comp, 'motivo_nota', '01')
    obj.doc_referencia_tipo = getattr(comp, 'doc_referencia_tipo', '01')
    obj.doc_referencia_numero = getattr(comp, 'doc_referencia_numero', '')

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


@celery_app.task(bind=True)
def emitir_comprobante_task(self, comprobante_id: str, test_mode: bool = False):
    """Procesa un comprobante: genera XML, firma y envía a SUNAT.

    Si test_mode=True, no se envía a SUNAT: se genera un CDR simulado (aceptado).
    Además, si no hay certificado en BD y test_mode=True, se crea un certificado autofirmado temporal.
    """
    session = SessionLocal()
    logger.info(f"emitir_comprobante_task started: comprobante_id={comprobante_id}, test_mode={test_mode}")
    print(f"emitir_comprobante_task START id={comprobante_id} test_mode={test_mode}")

    try:
        comp = session.query(Comprobante).filter_by(id=comprobante_id).first()
        if not comp:
            return {'error': 'not_found'}

        # Marcar procesando
        comp.estado = 'procesando'
        session.commit()

        # Cargar emisor
        emisor = session.query(Emisor).filter_by(id=comp.emisor_id).first()
        if not emisor:
            comp.estado = 'rechazado'
            session.commit()
            return {'error': 'emisor_not_found'}

        # ============================
        # CERTIFICADO DIGITAL
        # ============================
        certificado = session.query(Certificado).filter_by(
            emisor_id=emisor.id, activo=True
        ).order_by(Certificado.creado_en.desc()).first()

        pfx_bytes = None
        password = None

        if not certificado:
            if test_mode:
                # Crear certificado autofirmado temporal para test
                try:
                    from cryptography.hazmat.primitives.asymmetric import rsa
                    from cryptography.hazmat.primitives import serialization, hashes
                    from cryptography import x509
                    from cryptography.x509.oid import NameOID
                    from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates

                    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                    subject = issuer = x509.Name([
                        x509.NameAttribute(NameOID.COUNTRY_NAME, u"PE"),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Test Org"),
                        x509.NameAttribute(NameOID.COMMON_NAME, u"test.local"),
                    ])
                    cert_obj = (
                        x509.CertificateBuilder()
                        .subject_name(subject)
                        .issuer_name(issuer)
                        .public_key(key.public_key())
                        .serial_number(x509.random_serial_number())
                        .not_valid_before(datetime.utcnow() - timedelta(days=1))
                        .not_valid_after(datetime.utcnow() + timedelta(days=365))
                        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                        .sign(key, hashes.SHA256())
                    )
                    password = 'testpass'
                    pfx_bytes = serialize_key_and_certificates(
                        name=b"test", key=key, cert=cert_obj, cas=None,
                        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
                    )
                    session.add(LogEnvio(
                        comprobante_id=comp.id, emisor_id=emisor.id,
                        evento='test_cert_generated', nivel='INFO',
                        mensaje='Certificado de prueba generado', meta_json=None
                    ))
                    session.commit()
                except Exception as e:
                    comp.estado = 'rechazado'
                    session.add(LogEnvio(
                        comprobante_id=comp.id, emisor_id=emisor.id,
                        evento='test_cert_error', nivel='ERROR',
                        mensaje=str(e), meta_json={'trace': traceback.format_exc()}
                    ))
                    session.commit()
                    return {'error': 'test_cert_failed'}
            else:
                comp.estado = 'rechazado'
                session.add(LogEnvio(
                    comprobante_id=comp.id, emisor_id=emisor.id,
                    evento='certificado_missing', nivel='ERROR',
                    mensaje='Certificado no encontrado', meta_json=None
                ))
                session.commit()
                return {'error': 'certificado_missing'}
        else:
            # Desencriptar PFX y contraseña
            try:
                f = Fernet(settings.encryption_key.encode())
                pfx_bytes = f.decrypt(certificado.pfx_encriptado)
                password = f.decrypt(certificado.password_encriptado).decode()
            except Exception as e:
                comp.estado = 'rechazado'
                session.add(LogEnvio(
                    comprobante_id=comp.id, emisor_id=emisor.id,
                    evento='certificado_decrypt_error', nivel='ERROR',
                    mensaje=str(e), meta_json={'trace': traceback.format_exc()}
                ))
                session.commit()
                return {'error': 'decrypt_failed'}

        # ============================
        # GENERAR XML + FIRMAR
        # ============================
        try:
            comp_xml = _build_comprobante_xml_obj(comp)
            emisor_dict = _build_emisor_dict(emisor)

            xml_bytes = build_invoice_xml(comp_xml, emisor_dict)
            signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)

            # Guardar XML firmado
            comp.xml = signed_xml
            session.commit()

            session.add(LogEnvio(
                comprobante_id=comp.id, emisor_id=emisor.id,
                evento='signed', nivel='INFO',
                mensaje='XML firmado', meta_json=None
            ))
            session.commit()

        except Exception as e:
            logger.exception("XML generation/signing failed")
            tb = traceback.format_exc()
            print(f"XML generation failed:\n{tb}")

            comp.estado = 'rechazado'
            session.add(LogEnvio(
                comprobante_id=comp.id, emisor_id=emisor.id,
                evento='xml_sign_error', nivel='ERROR',
                mensaje=str(e), meta_json={'trace': tb}
            ))
            try:
                respuesta = RespuestaSunat(
                    comprobante_id=comp.id, codigo_cdr='',
                    descripcion=str(e), cdr_xml=tb.encode('utf-8')
                )
                session.add(respuesta)
            except Exception:
                pass
            session.commit()
            return {'error': 'xml_generation_failed'}

        # ============================
        # TEST MODE: CDR SIMULADO
        # ============================
        if test_mode:
            try:
                cdr_xml = b"<cdr><codigo>0</codigo><descripcion>Aceptado (simulado)</descripcion></cdr>"
                respuesta = RespuestaSunat(
                    comprobante_id=comp.id, codigo_cdr='0',
                    descripcion='Aceptado (simulado)', cdr_xml=cdr_xml
                )
                session.add(respuesta)
                comp.estado = 'aceptado'
                session.add(LogEnvio(
                    comprobante_id=comp.id, emisor_id=emisor.id,
                    evento='cdr_simulated', nivel='INFO',
                    mensaje='CDR simulado guardado', meta_json=None
                ))
                session.commit()
                return {'status': 'ok', 'id': comprobante_id, 'estado': comp.estado}
            except Exception as e:
                comp.estado = 'rechazado'
                session.add(LogEnvio(
                    comprobante_id=comp.id, emisor_id=emisor.id,
                    evento='cdr_sim_save_error', nivel='ERROR',
                    mensaje=str(e), meta_json={'trace': traceback.format_exc()}
                ))
                session.commit()
                return {'error': 'cdr_save_failed'}

        # ============================
        # ENVIAR A SUNAT
        # ============================
        try:
            sol_password_plain = _desencriptar_sol_password(emisor)

            username_log = f"{emisor.ruc}{emisor.sol_usuario}" if emisor.sol_usuario else None
            logger.info(f"Enviando a SUNAT - Username: {username_log}")

            cdr = enviar_comprobante(
                signed_xml, emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=sol_password_plain
            )
        except Exception as e:
            err_text = str(e)
            comp.estado = 'rechazado'
            session.add(LogEnvio(
                comprobante_id=comp.id, emisor_id=emisor.id,
                evento='sunat_send_error', nivel='ERROR',
                mensaje=err_text, meta_json={'trace': traceback.format_exc()}
            ))
            try:
                respuesta = RespuestaSunat(
                    comprobante_id=comp.id, codigo_cdr='',
                    descripcion=err_text, cdr_xml=err_text.encode('utf-8')
                )
                session.add(respuesta)
                session.commit()
            except Exception:
                session.commit()
            return {'error': 'sunat_send_failed'}

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
            session.add(respuesta)

            codigo = str(cdr.get('codigo') or '')
            if codigo == '0':
                comp.estado = 'aceptado'
            elif codigo.startswith('2'):
                comp.estado = 'aceptado_con_observaciones'
            else:
                comp.estado = 'rechazado'

            # Guardar hash del CDR (si existe) para el campo RESUMEN del PDF
            try:
                import hashlib
                if cdr.get('cdr_xml'):
                    cdr_bytes = cdr['cdr_xml'] if isinstance(cdr['cdr_xml'], bytes) else cdr['cdr_xml'].encode('utf-8')
                    comp.hash_cpe = hashlib.sha256(cdr_bytes).hexdigest()[:20]
            except Exception:
                pass

            session.commit()
        except Exception as e:
            comp.estado = 'rechazado'
            session.add(LogEnvio(
                comprobante_id=comp.id, emisor_id=emisor.id,
                evento='cdr_save_error', nivel='ERROR',
                mensaje=str(e), meta_json={'trace': traceback.format_exc()}
            ))
            session.commit()
            return {'error': 'cdr_save_failed'}

        return {'status': 'ok', 'id': comprobante_id, 'estado': comp.estado}

    finally:
        session.close()


@celery_app.task(name="reenviar_comprobante")
def reenviar_comprobante_task(comprobante_id: str):
    """
    Reenvía un comprobante que falló o fue rechazado.
    Reutiliza el XML firmado existente si lo tiene, o lo regenera.
    """
    session = SessionLocal()
    logger.info(f"reenviar_comprobante_task started: comprobante_id={comprobante_id}")

    try:
        comp = session.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
        if not comp:
            logger.error(f"Comprobante {comprobante_id} no encontrado")
            return {"status": "error", "mensaje": "Comprobante no encontrado"}

        if comp.estado == "aceptado":
            return {"status": "error", "mensaje": "El comprobante ya fue aceptado"}

        # Cargar emisor
        emisor = session.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
        if not emisor:
            return {"status": "error", "mensaje": "Emisor no encontrado"}

        # Si no tiene XML firmado, hay que regenerarlo
        if not comp.xml:
            # Obtener certificado
            certificado = session.query(Certificado).filter_by(
                emisor_id=emisor.id, activo=True
            ).order_by(Certificado.creado_en.desc()).first()

            if not certificado:
                return {"status": "error", "mensaje": "Certificado no disponible"}

            try:
                f = Fernet(settings.encryption_key.encode())
                pfx_bytes = f.decrypt(certificado.pfx_encriptado)
                password = f.decrypt(certificado.password_encriptado).decode()
            except Exception as e:
                return {"status": "error", "mensaje": f"Error desencriptando certificado: {e}"}

            try:
                comp_xml = _build_comprobante_xml_obj(comp)
                emisor_dict = _build_emisor_dict(emisor)
                xml_bytes = build_invoice_xml(comp_xml, emisor_dict)
                signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)
                comp.xml = signed_xml
                session.commit()
            except Exception as e:
                return {"status": "error", "mensaje": f"Error generando XML: {e}"}

        # Enviar a SUNAT
        try:
            sol_password_plain = _desencriptar_sol_password(emisor)

            cdr = enviar_comprobante(
                comp.xml, emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=sol_password_plain
            )
        except Exception as e:
            comp.estado = 'rechazado'
            session.commit()
            return {"status": "error", "mensaje": f"Error enviando a SUNAT: {e}"}

        # Guardar CDR
        try:
            respuesta = RespuestaSunat(
                comprobante_id=comp.id,
                codigo_cdr=str(cdr.get('codigo') or ''),
                descripcion=cdr.get('descripcion') or '',
                cdr_xml=cdr.get('cdr_xml')
            )
            session.add(respuesta)

            codigo = str(cdr.get('codigo') or '')
            if codigo == '0':
                comp.estado = 'aceptado'
            elif codigo.startswith('2'):
                comp.estado = 'aceptado_con_observaciones'
            else:
                comp.estado = 'rechazado'

            session.commit()
        except Exception as e:
            comp.estado = 'rechazado'
            session.commit()
            return {"status": "error", "mensaje": f"Error guardando CDR: {e}"}

        logger.info(f"Comprobante {comprobante_id} reenviado: {comp.estado}")
        return {
            "status": "ok",
            "id": str(comprobante_id),
            "estado": comp.estado,
            "mensaje": cdr.get('descripcion', '')
        }

    except Exception as e:
        logger.exception(f"Error reenviando comprobante {comprobante_id}")
        session.rollback()
        return {"status": "error", "mensaje": str(e)}
    finally:
        session.close()