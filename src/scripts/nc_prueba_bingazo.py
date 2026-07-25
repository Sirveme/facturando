#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nc_prueba_bingazo.py — Emisión CONTROLADA de UNA sola Nota de Crédito de prueba.

Caso "Bingazo 18/07/2026": anular boletas B400 duplicadas con NC (catálogo 09, motivo '01').
Este script emite EXCLUSIVAMENTE la NC de PRUEBA que anula la boleta B400-1680 (PINEDO),
y se DETIENE. No procesa el lote. No reintenta. No toca las boletas válidas 1691/1692.

Debe ejecutarse EN RAILWAY (donde vive la ENCRYPTION_KEY de producción, la BD real y
cacert.pem). No corre desde una máquina local.

FIX (hash_cpe): tras firmar, se extrae el DigestValue del XML firmado y se guarda en
comprobante.hash_cpe, replicando EXACTAMENTE el mecanismo del flujo estándar
(src/tasks/envio_sunat.py). El hash NO sale del CDR de SUNAT, sino del CPE firmado.

USO (en Railway)
----------------
1) Validación sin enviar nada — NO escribe en BD, NO transmite a SUNAT:
       python -m src.scripts.nc_prueba_bingazo
2) Envío real de la NC de prueba (un solo disparo, luego se detiene):
       python -m src.scripts.nc_prueba_bingazo --send
"""

import sys
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.models.models import (
    Comprobante, Emisor, Certificado, RespuestaSunat, LineaDetalle,
)
from src.services.xml_generator import build_invoice_xml
from src.services.firma_digital import firmar_xml
from src.services.sunat_client import enviar_comprobante

# =====================================================================
# PARÁMETROS FIJOS DEL CASO (no cambiar sin autorización de Duilio)
# =====================================================================
BOLETA_SERIE      = 'B400'
BOLETA_NUMERO     = 1680          # boleta de PRUEBA a anular
BOLETA_TIPO       = '03'          # boleta de venta
DNI_ESPERADO      = '45817384'    # PINEDO DE LA CRUZ CYNTHIA VANESSA (guarda de seguridad)
NC_SERIE          = 'BC40'        # serie de la Nota de Crédito (confirmado por Duilio)
NC_TIPO           = '07'          # Nota de Crédito
MOTIVO_NC         = '01'          # catálogo 09: Anulación de la operación

PERU_TZ = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------
# Helpers compartidos (usados también por el script de lote).
# ---------------------------------------------------------------------
def _extraer_hash_cpe(signed_xml):
    """Extrae el DigestValue del XML firmado (= RESUMEN/hash del CPE).

    Réplica EXACTA del mecanismo de src/tasks/envio_sunat.py. Devuelve str o None.
    """
    try:
        from lxml import etree
        doc = etree.fromstring(signed_xml)
        digest_els = doc.xpath("//*[local-name()='DigestValue']")
        if digest_els and digest_els[0].text:
            return digest_els[0].text.strip()
    except Exception as e:
        print(f"   [HASH] No se pudo extraer DigestValue: {e}")
    return None


def _build_emisor_dict(emisor) -> dict:
    return {
        'ruc': emisor.ruc,
        'razon_social': emisor.razon_social,
        'nombre_comercial': getattr(emisor, 'nombre_comercial', '') or emisor.razon_social,
        'direccion': getattr(emisor, 'direccion', '') or '',
        'ubigeo': getattr(emisor, 'ubigeo', '') or '',
        'departamento': getattr(emisor, 'departamento', '') or '',
        'provincia': getattr(emisor, 'provincia', '') or '',
        'distrito': getattr(emisor, 'distrito', '') or '',
        'es_amazonia': bool((getattr(emisor, 'config_json', None) or {}).get('es_amazonia', False)),
    }


def _build_comprobante_xml_obj(comp):
    class ComprobanteXML:
        pass

    obj = ComprobanteXML()
    obj.tipo_documento = comp.tipo_documento
    obj.serie = comp.serie
    obj.numero = comp.numero
    obj.fecha_emision = comp.fecha_emision
    obj.moneda = comp.moneda or 'PEN'

    obj.cliente_tipo_documento = comp.cliente_tipo_documento
    obj.cliente_numero_documento = comp.cliente_numero_documento
    obj.cliente_razon_social = comp.cliente_razon_social
    obj.cliente_direccion = getattr(comp, 'cliente_direccion', '') or ''

    obj.motivo_nota = getattr(comp, 'motivo_nota', '01')
    obj.doc_referencia_tipo = getattr(comp, 'doc_referencia_tipo', '01')
    obj.doc_referencia_numero = getattr(comp, 'doc_referencia_numero', '')

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


def _desencriptar_sol_password(emisor):
    if not emisor.sol_password:
        return None
    try:
        f = Fernet(settings.encryption_key.encode())
        return f.decrypt(emisor.sol_password.encode()).decode()
    except Exception:
        print("   [SOL] Clave SOL no cifrada o error al descifrar; se usa tal cual.")
        return emisor.sol_password


def cargar_cert(db, emisor):
    """Descifra el certificado activo del emisor. Aborta con mensaje claro si la key no corresponde."""
    certificado = (
        db.query(Certificado)
        .filter_by(emisor_id=emisor.id, activo=True)
        .order_by(Certificado.creado_en.desc())
        .first()
    )
    if not certificado:
        _abort(f"Emisor {emisor.ruc} no tiene certificado activo.")
    try:
        f = Fernet(settings.encryption_key.encode())
        pfx_bytes = f.decrypt(certificado.pfx_encriptado)
        password = f.decrypt(certificado.password_encriptado).decode()
        return pfx_bytes, password
    except InvalidToken:
        _abort(
            "InvalidToken al descifrar el certificado: la ENCRYPTION_KEY del entorno NO "
            "corresponde al certificado. ¿Estás en Railway con la key de producción "
            "(huella 408917...)? En local con la key de desarrollo esto SIEMPRE falla."
        )
    except Exception as e:
        _abort(f"Error descifrando el certificado: {e}")


def _abort(msg: str):
    print(f"\n🛑 ABORTADO: {msg}\n")
    sys.exit(1)


def main():
    send_mode = '--send' in sys.argv

    print("=" * 72)
    print("NC PRUEBA BINGAZO — anular boleta B400-1680 (PINEDO) con NC serie BC40")
    print("MODO:", "🚨 ENVÍO REAL A SUNAT" if send_mode else "🧪 DRY-RUN (sin BD, sin SUNAT)")
    print("=" * 72)

    db = SessionLocal()
    try:
        # 1) Cargar y validar la boleta objetivo (única y fija)
        boleta = (
            db.query(Comprobante)
            .filter(
                Comprobante.serie == BOLETA_SERIE,
                Comprobante.numero == BOLETA_NUMERO,
                Comprobante.tipo_documento == BOLETA_TIPO,
            )
            .first()
        )
        if not boleta:
            _abort(f"No se encontró la boleta {BOLETA_SERIE}-{BOLETA_NUMERO} (tipo {BOLETA_TIPO}).")

        print(f"\n[1] Boleta: {boleta.numero_formato}  estado={boleta.estado}  "
              f"total={boleta.monto_total}  cliente={boleta.cliente_razon_social} "
              f"(doc {boleta.cliente_numero_documento})")

        if (boleta.cliente_numero_documento or '') != DNI_ESPERADO:
            _abort(f"Cliente de la boleta ({boleta.cliente_numero_documento}) != esperado ({DNI_ESPERADO}).")
        if boleta.estado != 'aceptado':
            _abort(f"La boleta no está 'aceptado' (estado: {boleta.estado}).")
        if not boleta.numero_formato:
            _abort("La boleta no tiene numero_formato; no se puede referenciar.")
        if not boleta.lineas:
            _abort("La boleta no tiene líneas de detalle.")

        # 2) Idempotencia
        nc_previa = (
            db.query(Comprobante)
            .filter(
                Comprobante.emisor_id == boleta.emisor_id,
                Comprobante.tipo_documento == NC_TIPO,
                Comprobante.doc_referencia_numero == boleta.numero_formato,
            )
            .first()
        )
        if nc_previa:
            _abort(f"Ya existe NC {nc_previa.numero_formato} (estado={nc_previa.estado}) para {boleta.numero_formato}.")
        print("[2] OK: no existe NC previa para esta boleta.")

        # 3) Emisor + certificado
        emisor = db.query(Emisor).filter(Emisor.id == boleta.emisor_id).first()
        if not emisor:
            _abort("Emisor de la boleta no encontrado.")
        pfx_bytes, password = cargar_cert(db, emisor)
        print(f"[3] OK: emisor {emisor.ruc} produccion={getattr(emisor, 'produccion', False)} cert OK.")

        # 4) Construir NC BC40 replicando la boleta
        from sqlalchemy import func
        max_numero = (
            db.query(func.max(Comprobante.numero))
            .filter(
                Comprobante.emisor_id == emisor.id,
                Comprobante.serie == NC_SERIE,
                Comprobante.tipo_documento == NC_TIPO,
            )
            .scalar()
        )
        siguiente_numero = (max_numero + 1) if max_numero else 1
        numero_formato = f"{NC_SERIE}-{str(siguiente_numero).zfill(8)}"
        fecha_peru = datetime.now(PERU_TZ).date()

        nc = Comprobante(
            id=str(uuid4()),
            emisor_id=emisor.id,
            tipo_documento=NC_TIPO,
            serie=NC_SERIE,
            numero=siguiente_numero,
            numero_formato=numero_formato,
            fecha_emision=fecha_peru,
            moneda=boleta.moneda or 'PEN',
            cliente_tipo_documento=boleta.cliente_tipo_documento,
            cliente_numero_documento=boleta.cliente_numero_documento,
            cliente_razon_social=boleta.cliente_razon_social,
            cliente_direccion=boleta.cliente_direccion,
            monto_base=boleta.monto_base,
            monto_igv=boleta.monto_igv,
            monto_total=boleta.monto_total,
            op_gravada=boleta.op_gravada,
            estado='pendiente',
            observaciones=f"Anulación por duplicidad (Bingazo 18/07/2026). Ref {boleta.numero_formato}.",
            doc_referencia_tipo=boleta.tipo_documento,
            doc_referencia_numero=boleta.numero_formato,
            motivo_nota=MOTIVO_NC,
        )
        lineas_nc = []
        for ln in sorted(boleta.lineas, key=lambda x: x.orden or 0):
            lineas_nc.append(LineaDetalle(
                id=str(uuid4()), comprobante_id=nc.id, orden=ln.orden,
                descripcion=ln.descripcion, cantidad=ln.cantidad, unidad=ln.unidad or 'NIU',
                precio_unitario=ln.precio_unitario, monto_linea=ln.monto_linea,
                tipo_afectacion_igv=getattr(ln, 'tipo_afectacion_igv', '10') or '10',
                es_bonificacion=False,
            ))
        nc.lineas = lineas_nc
        print(f"[4] NC a emitir: {numero_formato}  ref->{nc.doc_referencia_tipo} {nc.doc_referencia_numero}  "
              f"líneas={len(lineas_nc)}")

        # 5) Generar + firmar + extraer hash (FIX)
        comp_xml = _build_comprobante_xml_obj(nc)
        xml_bytes = build_invoice_xml(comp_xml, _build_emisor_dict(emisor))
        signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)
        nc.hash_cpe = _extraer_hash_cpe(signed_xml)      # <-- FIX: guardar DigestValue
        print(f"[5] XML firmado OK ({len(signed_xml)} bytes). hash_cpe={nc.hash_cpe}")
        if not nc.hash_cpe:
            _abort("No se pudo extraer hash_cpe del XML firmado. Se detiene (no emitir sin hash).")

        if not send_mode:
            db.rollback()
            print("\n🧪 DRY-RUN completado. NADA en BD ni SUNAT.")
            print("   Envío real:  python -m src.scripts.nc_prueba_bingazo --send")
            return

        # 6) Envío real
        nc.xml = signed_xml
        db.add(nc)
        for ln in lineas_nc:
            db.add(ln)
        nc.estado = 'enviando'
        db.commit()
        print(f"[6] NC {numero_formato} persistida (hash guardado). Transmitiendo a SUNAT...")

        try:
            cdr = enviar_comprobante(
                signed_xml, emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=_desencriptar_sol_password(emisor),
                use_production=getattr(emisor, 'produccion', False),
            )
        except Exception as e:
            nc.estado = 'error'
            db.commit()
            print(f"\n❌ FALLO TÉCNICO (sin CDR): {e}\n   NC en 'error'. NO se reintenta.")
            sys.exit(2)

        codigo = str(cdr.get('codigo') or '')
        descripcion = cdr.get('descripcion') or ''
        cdr_xml = cdr.get('cdr_xml')

        db.add(RespuestaSunat(comprobante_id=nc.id, codigo_cdr=codigo,
                              descripcion=descripcion, cdr_xml=cdr_xml))
        if codigo == '0':
            nc.estado = 'aceptado'
        elif codigo.startswith('2'):
            nc.estado = 'aceptado_con_observaciones'
        else:
            nc.estado = 'rechazado'
        db.commit()

        print("\n" + "=" * 72)
        print(f"NC {numero_formato}  ResponseCode={codigo!r}  estado={nc.estado}  hash_cpe={nc.hash_cpe}")
        print(f"Descripción: {descripcion}")
        if cdr_xml:
            raw = cdr_xml.decode('utf-8', errors='replace') if isinstance(cdr_xml, (bytes, bytearray)) else str(cdr_xml)
            print("--- CDR literal ---")
            print(raw[:4000])
            print("--- fin CDR ---")
        print("🛑 DETENIDO POR DISEÑO tras la NC de prueba. Reportar a Duilio.")
        print("=" * 72)

    finally:
        db.close()


if __name__ == '__main__':
    main()
