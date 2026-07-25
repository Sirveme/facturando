#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nc_prueba_bingazo.py — Emisión CONTROLADA de UNA sola Nota de Crédito de prueba.

Caso "Bingazo 18/07/2026": anular boletas B400 duplicadas con NC (catálogo 09, motivo '01').
Este script emite EXCLUSIVAMENTE la NC de PRUEBA que anula la boleta B400-1680 (PINEDO),
y se DETIENE. No procesa el lote. No reintenta. No toca las boletas válidas 1691/1692.

Debe ejecutarse EN RAILWAY (donde vive la ENCRYPTION_KEY de producción y la BD real).
No corre desde una máquina local: el certificado está cifrado con la key de producción.

USO
---
1) Validación sin enviar nada (recomendado primero) — NO escribe en BD, NO transmite a SUNAT:
       python -m scripts.nc_prueba_bingazo
   Valida la boleta, verifica que no exista NC previa, construye y FIRMA el XML,
   y muestra un resumen + preview del XML. Hace rollback.

2) Envío real de la NC de prueba a SUNAT (un solo disparo, luego se detiene):
       python -m scripts.nc_prueba_bingazo --send

Reglas incorporadas (no configurables por diseño):
- Objetivo fijo y único: boleta B400-1680, cliente DNI 45817384 (PINEDO). Cualquier
  discrepancia aborta.
- Idempotencia: si ya existe una NC que referencia esa boleta, aborta y reporta.
- Serie NC fija: BC40. Motivo fijo: '01' (Anulación de la operación, catálogo 09).
- Sin reintentos automáticos: si SUNAT rechaza/observa o hay fallo técnico, se reporta y
  se detiene. La decisión de qué hacer la toma el humano.
"""

import sys
from datetime import datetime, timezone, timedelta

# --- Dependencias del sistema Facturalo (solo lectura de servicios; NO se modifican) ---
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
# Helpers de forma para el generador XML (copiados de src/tasks para no
# importar Celery/Redis; son funciones puras sin efectos secundarios).
# ---------------------------------------------------------------------
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
        # -------------------------------------------------------------
        # 1) Cargar y validar la boleta objetivo (única y fija)
        # -------------------------------------------------------------
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

        print(f"\n[1] Boleta encontrada: {boleta.numero_formato}")
        print(f"    id={boleta.id}")
        print(f"    estado={boleta.estado}  monto_total={boleta.monto_total}  moneda={boleta.moneda}")
        print(f"    cliente={boleta.cliente_razon_social} (doc {boleta.cliente_numero_documento})")
        print(f"    emisor_id={boleta.emisor_id}")

        # Guardas de seguridad
        if (boleta.cliente_numero_documento or '') != DNI_ESPERADO:
            _abort(
                f"El cliente de la boleta ({boleta.cliente_numero_documento}) no coincide con "
                f"el esperado ({DNI_ESPERADO}). NO se continúa por seguridad."
            )
        if boleta.estado != 'aceptado':
            _abort(
                f"La boleta no está 'aceptado' (estado actual: {boleta.estado}). "
                f"Solo se anula una boleta aceptada por SUNAT."
            )
        if not boleta.numero_formato:
            _abort("La boleta no tiene numero_formato; no se puede construir la referencia de la NC.")
        if not boleta.lineas:
            _abort("La boleta no tiene líneas de detalle; no se puede replicar en la NC.")

        # -------------------------------------------------------------
        # 2) Idempotencia: ¿ya existe una NC que referencia esta boleta?
        # -------------------------------------------------------------
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
            _abort(
                f"Ya existe una NC ({nc_previa.numero_formato}, estado={nc_previa.estado}) que "
                f"referencia {boleta.numero_formato}. NO se emite otra (evita duplicar)."
            )
        print("[2] OK: no existe NC previa que referencie esta boleta.")

        # -------------------------------------------------------------
        # 3) Emisor + certificado (descifrado con ENCRYPTION_KEY de prod)
        # -------------------------------------------------------------
        emisor = db.query(Emisor).filter(Emisor.id == boleta.emisor_id).first()
        if not emisor:
            _abort("Emisor de la boleta no encontrado.")

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
        except InvalidToken:
            _abort(
                "InvalidToken al descifrar el certificado: la ENCRYPTION_KEY del entorno NO "
                "corresponde al certificado. ¿Estás corriendo esto en Railway con la key de "
                "producción (huella 408917...)? En local con la key de desarrollo esto SIEMPRE falla."
            )
        except Exception as e:
            _abort(f"Error descifrando el certificado: {e}")

        print(f"[3] OK: emisor {emisor.ruc} ({emisor.razon_social}) — "
              f"produccion={getattr(emisor, 'produccion', False)} — certificado descifrado.")

        # -------------------------------------------------------------
        # 4) Construir la NC (serie BC40) replicando la boleta
        # -------------------------------------------------------------
        max_numero = (
            db.query(__import__('sqlalchemy').func.max(Comprobante.numero))
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

        from uuid import uuid4
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
            doc_referencia_tipo=boleta.tipo_documento,       # '03'
            doc_referencia_numero=boleta.numero_formato,     # p.ej. 'B400-00001680'
            motivo_nota=MOTIVO_NC,                           # '01'
        )

        # Replicar líneas EXACTAS de la boleta original
        lineas_nc = []
        for ln in sorted(boleta.lineas, key=lambda x: x.orden or 0):
            lineas_nc.append(LineaDetalle(
                id=str(uuid4()),
                comprobante_id=nc.id,
                orden=ln.orden,
                descripcion=ln.descripcion,
                cantidad=ln.cantidad,
                unidad=ln.unidad or 'NIU',
                precio_unitario=ln.precio_unitario,
                monto_linea=ln.monto_linea,
                tipo_afectacion_igv=getattr(ln, 'tipo_afectacion_igv', '10') or '10',
                es_bonificacion=False,
            ))
        # Adjuntar en memoria para que el generador XML las vea
        nc.lineas = lineas_nc

        print(f"[4] NC a emitir: {numero_formato}  (motivo {MOTIVO_NC} — Anulación de la operación)")
        print(f"    referencia -> {nc.doc_referencia_tipo} {nc.doc_referencia_numero}")
        print(f"    líneas replicadas: {len(lineas_nc)}")
        for ln in lineas_nc:
            print(f"      · orden={ln.orden} cant={ln.cantidad} pu={ln.precio_unitario} "
                  f"afect={ln.tipo_afectacion_igv} desc={ (ln.descripcion or '')[:40] }")

        # -------------------------------------------------------------
        # 5) Generar + firmar XML (se hace en ambos modos)
        # -------------------------------------------------------------
        comp_xml = _build_comprobante_xml_obj(nc)
        emisor_dict = _build_emisor_dict(emisor)
        xml_bytes = build_invoice_xml(comp_xml, emisor_dict)
        signed_xml = firmar_xml(xml_bytes, pfx_bytes, password)
        print(f"[5] XML NC generado y firmado OK ({len(signed_xml)} bytes).")

        if not send_mode:
            preview = signed_xml.decode('utf-8', errors='replace')[:1200]
            print("\n----- PREVIEW XML FIRMADO (primeros 1200 chars) -----")
            print(preview)
            print("----- FIN PREVIEW -----")
            db.rollback()
            print("\n🧪 DRY-RUN completado. NADA se guardó en BD ni se envió a SUNAT.")
            print("   Para enviar la NC de prueba real:  python -m scripts.nc_prueba_bingazo --send")
            return

        # -------------------------------------------------------------
        # 6) MODO ENVÍO: persistir NC, transmitir a SUNAT, guardar CDR
        # -------------------------------------------------------------
        nc.xml = signed_xml
        db.add(nc)
        for ln in lineas_nc:
            db.add(ln)
        nc.estado = 'enviando'
        db.commit()
        print(f"[6] NC {numero_formato} persistida (estado=enviando). Transmitiendo a SUNAT...")

        sol_password_plain = _desencriptar_sol_password(emisor)

        try:
            cdr = enviar_comprobante(
                signed_xml,
                emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=sol_password_plain,
                use_production=getattr(emisor, 'produccion', False),
            )
        except Exception as e:
            # Fallo técnico (red/timeout/excepción) ANTES de tener CDR:
            # reportar y DETENERSE. NO reintentar (un reintento a ciegas causó la duplicación).
            nc.estado = 'error'
            db.commit()
            print("\n" + "!" * 72)
            print(f"❌ FALLO TÉCNICO al transmitir (sin CDR): {e}")
            print("   NC quedó en estado 'error'. NO se reintenta. Reportar a Duilio.")
            print("!" * 72)
            sys.exit(2)

        codigo = str(cdr.get('codigo') or '')
        descripcion = cdr.get('descripcion') or ''
        cdr_xml = cdr.get('cdr_xml')

        # Guardar CDR
        db.add(RespuestaSunat(
            comprobante_id=nc.id,
            codigo_cdr=codigo,
            descripcion=descripcion,
            cdr_xml=cdr_xml,
        ))

        if codigo == '0':
            nc.estado = 'aceptado'
        elif codigo.startswith('2'):
            nc.estado = 'aceptado_con_observaciones'
        else:
            nc.estado = 'rechazado'
        db.commit()

        # -------------------------------------------------------------
        # 7) Reporte final (hard stop pase lo que pase)
        # -------------------------------------------------------------
        print("\n" + "=" * 72)
        print("RESULTADO NC DE PRUEBA — SUNAT")
        print("=" * 72)
        print(f"NC:              {numero_formato}")
        print(f"Referencia:      {nc.doc_referencia_numero}")
        print(f"ResponseCode:    {codigo!r}")
        print(f"Descripción:     {descripcion}")
        print(f"Estado final NC: {nc.estado}")
        if cdr_xml:
            try:
                raw = cdr_xml.decode('utf-8', errors='replace') if isinstance(cdr_xml, (bytes, bytearray)) else str(cdr_xml)
                print("\n--- CDR / respuesta cruda de SUNAT (literal) ---")
                print(raw[:4000])
                print("--- fin CDR ---")
            except Exception:
                pass

        print("\n🛑 DETENIDO POR DISEÑO tras la NC de prueba.")
        if nc.estado == 'aceptado':
            print("   → Prueba ACEPTADA. Reportar a Duilio y ESPERAR visto bueno antes del lote.")
        elif nc.estado == 'aceptado_con_observaciones':
            print("   → ACEPTADA CON OBSERVACIONES. Transcribir observaciones y esperar decisión humana.")
        else:
            print("   → RECHAZADA/OBSERVADA. NO reintentar, NO probar otra boleta. Reportar código y "
                  "mensaje exacto a Duilio (posible extemporaneidad/plazo).")
        print("=" * 72)

    finally:
        db.close()


if __name__ == '__main__':
    main()
