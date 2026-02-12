from .celery_app import celery_app
from src.models.models import Comprobante, Emisor, Certificado, RespuestaSunat, LogEnvio
from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.services.xml_generator import build_invoice_xml
from src.services.firma_digital import firmar_xml
from src.services.sunat_client import enviar_comprobante
from cryptography.fernet import Fernet
import traceback
from datetime import datetime, timezone, timedelta

@celery_app.task(bind=True)
def emitir_comprobante_task(self, comprobante_id: str, test_mode: bool = False):
    """Procesa un comprobante: genera XML, firma y envía a SUNAT.

    Si test_mode=True, no se envía a SUNAT: se genera un CDR simulado (aceptado).
    Además, si no hay certificado en BD y test_mode=True, se crea un certificado autofirmado temporal.
    """
    import logging
    logger = logging.getLogger(__name__)
    session = SessionLocal()
    logger.info(f"emitir_comprobante_task started: comprobante_id={comprobante_id}, test_mode={test_mode}")
    print(f"emitir_comprobante_task START id={comprobante_id} test_mode={test_mode}")
    try:
        comp = session.query(Comprobante).filter_by(id=comprobante_id).first()
        if not comp:
            return {'error': 'not_found'}

        # mark procesando
        comp.estado = 'procesando'
        session.commit()

        # load emisor
        emisor = session.query(Emisor).filter_by(id=comp.emisor_id).first()
        if not emisor:
            comp.estado = 'rechazado'
            session.commit()
            return {'error': 'emisor_not_found'}

        # get active certificate
        certificado = session.query(Certificado).filter_by(emisor_id=emisor.id, activo=True).order_by(Certificado.creado_en.desc()).first()

        pfx_bytes = None
        password = None

        if not certificado:
            if test_mode:
                # create temporary self-signed PFX in memory
                try:
                    from cryptography.hazmat.primitives.asymmetric import rsa
                    from cryptography.hazmat.primitives import serialization, hashes
                    from cryptography import x509
                    from cryptography.x509.oid import NameOID
                    from datetime import datetime, timedelta
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
                    pfx_bytes = serialize_key_and_certificates(name=b"test", key=key, cert=cert_obj, cas=None, encryption_algorithm=serialization.BestAvailableEncryption(password.encode()))
                    # log
                    session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='test_cert_generated', nivel='INFO', mensaje='Certificado de prueba generado', meta_json=None))
                    session.commit()
                except Exception as e:
                    comp.estado = 'rechazado'
                    session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='test_cert_error', nivel='ERROR', mensaje=str(e), meta_json={'trace': traceback.format_exc()}))
                    session.commit()
                    return {'error': 'test_cert_failed'}
            else:
                comp.estado = 'rechazado'
                session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='certificado_missing', nivel='ERROR', mensaje='Certificado no encontrado', meta_json=None))
                session.commit()
                return {'error': 'certificado_missing'}
        else:
            # decrypt pfx and password using Fernet
            try:
                f = Fernet(settings.encryption_key.encode())
                pfx_bytes = f.decrypt(certificado.pfx_encriptado)
                password = f.decrypt(certificado.password_encriptado).decode()
            except Exception as e:
                comp.estado = 'rechazado'
                session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='certificado_decrypt_error', nivel='ERROR', mensaje=str(e), meta_json={'trace': traceback.format_exc()}))
                session.commit()
                return {'error': 'decrypt_failed'}

        # Build comprobante payload to feed build_invoice_xml (use Pydantic-compatible object)
        from src.schemas.schemas import ComprobanteCreate, LineaItem
        items = []
        for linea in comp.lineas:
            items.append(LineaItem(orden=linea.orden, descripcion=linea.descripcion or '', cantidad=linea.cantidad, unidad=linea.unidad or 'NIU', precio_unitario=linea.precio_unitario))
        comprobante_payload = ComprobanteCreate(
            emisor_ruc=emisor.ruc,
            tipo_documento=comp.tipo_documento,
            serie=comp.serie,
            numero=comp.numero,
            fecha_emision=comp.fecha_emision.strftime('%d/%m/%Y') if comp.fecha_emision else datetime.now(timezone(timedelta(hours=-5))).strftime('%d/%m/%Y'),
            moneda=comp.moneda,
            items=items
        )

        try:
            xml_bytes = build_invoice_xml(comprobante_payload, {'ruc': emisor.ruc, 'razon_social': emisor.razon_social, 'nombre_comercial': emisor.nombre_comercial, 'direccion': emisor.direccion})
            # sign
            signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)
            # save signed xml
            comp.xml = signed_xml
            session.commit()
            session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='signed', nivel='INFO', mensaje='XML firmado', meta_json=None))
            session.commit()
        except Exception as e:
            # Log full exception with traceback
            logger.exception("XML generation failed")
            tb = traceback.format_exc()
            print("XML generation failed:\n", tb)
            comp.estado = 'rechazado'
            session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='xml_sign_error', nivel='ERROR', mensaje=str(e), meta_json={'trace': tb}))
            # Save error into RespuestaSunat for visibility in API
            try:
                respuesta = RespuestaSunat(comprobante_id=comp.id, codigo_cdr='', descripcion=str(e), cdr_xml=tb.encode('utf-8'))
                session.add(respuesta)
            except Exception:
                pass
            session.commit()
            return {'error': 'xml_generation_failed'}

        # If test_mode: simulate CDR accepted and do not call SUNAT
        if test_mode:
            try:
                cdr_xml = b"<cdr><codigo>0</codigo><descripcion>Aceptado (simulado)</descripcion></cdr>"
                respuesta = RespuestaSunat(comprobante_id=comp.id, codigo_cdr='0', descripcion='Aceptado (simulado)', cdr_xml=cdr_xml)
                session.add(respuesta)
                comp.estado = 'aceptado'
                session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='cdr_simulated', nivel='INFO', mensaje='CDR simulado guardado', meta_json=None))
                session.commit()
                return {'status': 'ok', 'id': comprobante_id, 'estado': comp.estado}
            except Exception as e:
                comp.estado = 'rechazado'
                session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='cdr_sim_save_error', nivel='ERROR', mensaje=str(e), meta_json={'trace': traceback.format_exc()}))
                session.commit()
                return {'error': 'cdr_save_failed'}

        # send to SUNAT
        try:
            # Desencriptar clave SOL
            from cryptography.fernet import Fernet
            from src.core.config import settings

            sol_password_plain = emisor.sol_password
            if emisor.sol_password:
                try:
                    f = Fernet(settings.encryption_key.encode())
                    sol_password_plain = f.decrypt(emisor.sol_password.encode()).decode()
                    logger.info("SOL password desencriptada OK")
                except Exception:
                    logger.warning("SOL password no encriptada, usando tal cual")
                    sol_password_plain = emisor.sol_password

            username_used = f"{emisor.ruc}{emisor.sol_usuario}" if emisor.sol_usuario else None
            logger.info(f"Enviando a SUNAT - Username: {username_used}")

            cdr = enviar_comprobante(signed_xml, emisor.ruc, sol_usuario=emisor.sol_usuario, sol_password=sol_password_plain)
        except Exception as e:
            # If enviar_comprobante raises, log and try to save raw exception as respuesta
            err_text = str(e)
            comp.estado = 'rechazado'
            session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='sunat_send_error', nivel='ERROR', mensaje=err_text, meta_json={'trace': traceback.format_exc()}))
            # save raw error as RespuestaSunat for debugging
            try:
                respuesta = RespuestaSunat(comprobante_id=comp.id, codigo_cdr='', descripcion=err_text, cdr_xml=err_text.encode('utf-8'))
                session.add(respuesta)
                session.commit()
            except Exception:
                session.commit()
            return {'error': 'sunat_send_failed'}

        # save CDR
        try:
            # Ensure cdr keys exist even if None
            respuesta = RespuestaSunat(comprobante_id=comp.id, codigo_cdr=str(cdr.get('codigo') or ''), descripcion=cdr.get('descripcion') or '', cdr_xml=cdr.get('cdr_xml'))
            session.add(respuesta)
            # update status
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
            session.add(LogEnvio(comprobante_id=comp.id, emisor_id=emisor.id, evento='cdr_save_error', nivel='ERROR', mensaje=str(e), meta_json={'trace': traceback.format_exc()}))
            session.commit()
            return {'error': 'cdr_save_failed'}

        return {'status': 'ok', 'id': comprobante_id, 'estado': comp.estado}

    finally:
        session.close()


@celery_app.task(name="reenviar_comprobante")
def reenviar_comprobante_task(comprobante_id: str):
    """
    Reenvía un comprobante que falló o fue rechazado.
    """
    import logging
    from src.services.sunat_client import enviar_comprobante
    
    logger = logging.getLogger(__name__)
    logger.info(f"reenviar_comprobante_task started: comprobante_id={comprobante_id}")
    
    # Crear sesión de base de datos
    db = SessionLocal()
    
    try:
        # Buscar comprobante
        comprobante = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
        if not comprobante:
            logger.error(f"Comprobante {comprobante_id} no encontrado")
            return {"status": "error", "mensaje": "Comprobante no encontrado"}
        
        # Validar que no esté aceptado
        if comprobante.estado == "aceptado":
            return {"status": "error", "mensaje": "El comprobante ya fue aceptado"}
        
        # Buscar log de envío previo
        log = db.query(LogEnvio).filter(LogEnvio.comprobante_id == comprobante_id).first()
        if not log or not log.zip_bytes:
            return {"status": "error", "mensaje": "No hay datos de envío previo"}
        
        # Obtener certificado y credenciales
        certificado = db.query(Certificado).filter(
            Certificado.emisor_ruc == comprobante.emisor_ruc,
            Certificado.activo == True
        ).first()
        
        if not certificado:
            return {"status": "error", "mensaje": "Certificado no disponible"}
        
        emisor = db.query(Emisor).filter(Emisor.ruc == comprobante.emisor_ruc).first()
        
        # Preparar nombre del ZIP
        nombre_zip = f"{comprobante.emisor_ruc}-{comprobante.tipo_comprobante}-{comprobante.serie}-{comprobante.numero}.zip"
        
        # Reenviar a SUNAT
        resultado = enviar_comprobante(
            emisor_ruc=comprobante.emisor_ruc,
            nombre_zip=nombre_zip,
            zip_bytes=log.zip_bytes,
            sol_usuario=emisor.sol_usuario if emisor else None,
            sol_password=emisor.sol_password if emisor else None
        )
        
        # Actualizar estado del comprobante
        if resultado.get("aceptado"):
            comprobante.estado = "aceptado"
        else:
            comprobante.estado = "rechazado"
        
        db.commit()
        
        logger.info(f"Comprobante {comprobante_id} reenviado: {resultado.get('estado')}")
        
        return {
            "status": "ok",
            "id": str(comprobante_id),
            "estado": comprobante.estado,
            "mensaje": resultado.get("mensaje")
        }
        
    except Exception as e:
        logger.exception(f"Error reenviando comprobante {comprobante_id}")
        db.rollback()
        return {"status": "error", "mensaje": str(e)}
    finally:
        db.close()