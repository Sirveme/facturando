#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_psp.py — SOLO LECTURA.

Verifica que PSP (Perú Sistemas Pro, RUC 20615446565) está listo para EMITIR la
factura de suscripción EXONERADA (Amazonía, afectación '20'):
  - SOL: usuario presente + clave desencriptable.
  - Certificado: activo, vigente y FIRMABLE (carga pkcs12 con su clave).
  - Afectación '20' exonerada: genera el XML en memoria (NO emite) y confirma
    EXO/9997, sin IGV, y la leyenda Amazonía 2002 si es_amazonia.

No escribe NADA ni emite. Ejecutar EN RAILWAY:
    python -m src.scripts.verificar_psp
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import pkcs12

from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.models.models import Emisor
from src.services import xml_generator as XG

RUC_PSP = '20615446565'


def _emisor_dict(e):
    """Espejo de envio_sunat._build_emisor_dict (para fidelidad del XML)."""
    cfg = getattr(e, 'config_json', None) or {}
    return {
        'ruc': e.ruc, 'razon_social': e.razon_social,
        'nombre_comercial': getattr(e, 'nombre_comercial', '') or e.razon_social,
        'direccion': getattr(e, 'direccion', '') or '', 'ubigeo': getattr(e, 'ubigeo', '') or '',
        'departamento': getattr(e, 'departamento', '') or '', 'provincia': getattr(e, 'provincia', '') or '',
        'distrito': getattr(e, 'distrito', '') or '',
        'es_amazonia': bool(cfg.get('es_amazonia', False)),
        'detraccion': cfg.get('detraccion'), 'cuenta_detraccion': getattr(e, 'cuenta_detraccion', None),
    }


def _dec(f, blob):
    return f.decrypt(blob if isinstance(blob, bytes) else blob.encode())


def main():
    db = SessionLocal()
    try:
        e = db.query(Emisor).filter(Emisor.ruc == RUC_PSP).first()
        if not e:
            print(f"❌ No existe emisor PSP {RUC_PSP} en la BD")
            return

        print("=" * 82)
        print(f"PSP: {e.ruc} — {e.razon_social}")
        print("=" * 82)
        print(f"  produccion        : {getattr(e, 'produccion', None)}")
        print(f"  modo_test         : {getattr(e, 'modo_test', None)}")
        print(f"  plan              : {getattr(e, 'plan', None)}")
        cfg = getattr(e, 'config_json', None) or {}
        print(f"  es_amazonia (cfg) : {cfg.get('es_amazonia')}")
        print(f"  ubigeo/dpto       : {getattr(e,'ubigeo',None)} / {getattr(e,'departamento',None)}")

        # ── SOL ──
        print("-" * 82)
        print("CREDENCIALES SOL")
        print(f"  sol_usuario       : {e.sol_usuario!r}")
        sol_ok = False
        if not e.sol_password:
            print("  sol_password      : ❌ ausente")
        else:
            try:
                Fernet(settings.encryption_key.encode()).decrypt(e.sol_password.encode())
                print("  sol_password      : ✅ presente y desencriptable")
                sol_ok = bool(e.sol_usuario)
            except Exception as ex:
                print(f"  sol_password      : ⚠️ no desencripta: {ex}")

        # ── CERTIFICADO ──
        print("-" * 82)
        print("CERTIFICADO")
        cert = next((c for c in e.certificados if c.activo), None) if e.certificados else None
        cert_ok = False
        if not cert:
            print("  ❌ No hay certificado activo")
        else:
            dias = (cert.fecha_vencimiento - date.today()).days if cert.fecha_vencimiento else None
            print(f"  serial            : {str(cert.serial_number)[:24]}")
            print(f"  vence             : {cert.fecha_vencimiento} (días restantes: {dias})")
            vigente = bool(cert.fecha_vencimiento and cert.fecha_vencimiento >= date.today())
            try:
                f = Fernet(settings.encryption_key.encode())
                pfx = _dec(f, cert.pfx_encriptado)
                pw = _dec(f, cert.password_encriptado)
                _k, _c, _ = pkcs12.load_key_and_certificates(pfx, pw, default_backend())
                print(f"  pkcs12 load       : ✅ OK (cert + clave válidos → FIRMABLE)")
                print(f"  not_valid_after   : {_c.not_valid_after_utc.date()}")
                cert_ok = vigente
            except Exception as ex:
                print(f"  pkcs12 load       : ⚠️ falló (no firmable): {ex}")

        # ── TEST EXONERADO (afectación 20), en memoria ──
        print("-" * 82)
        print("TEST EMISIÓN EXONERADA (afectación '20') — en memoria, NO emite")
        comp = NS(tipo_documento='01', moneda='PEN', serie='FTEST', numero=1,
                  fecha_emision=datetime(2026, 10, 3, 10, 0, 0), forma_pago='Contado',
                  items=[NS(descripcion='Suscripcion Facturalo (prueba)', cantidad=1,
                            precio_unitario=29.0, unidad_medida='ZZ', tipo_afectacion_igv='20', codigo=None)],
                  cliente_tipo_documento='6', cliente_numero_documento='10736459791',
                  cliente_razon_social='AUTOMOTRIZ CASTILLO', cliente_direccion='X')
        xml = XG.build_invoice_xml(comp, _emisor_dict(e))
        exo = (b'>EXO<' in xml) and (b'>9997<' in xml)
        sin_igv_scheme = b'>IGV<' not in xml
        print(f"  EXO/9997 presente : {exo}")
        print(f"  sin esquema IGV   : {sin_igv_scheme}")
        print(f"  leyenda Amazonía 2002: {b'2002' in xml}  (True solo si es_amazonia)")
        print(f"  listID=0101 (sin detracción): {b'listID=\"0101\"' in xml}")

        print("=" * 82)
        listo = sol_ok and cert_ok and exo
        print("VEREDICTO PSP:",
              "✅ LISTO para emitir facturas exoneradas de suscripción"
              if listo else "⚠️ Revisar arriba (SOL / certificado vigente / afectación)")
        if not cfg.get('es_amazonia'):
            print("Nota: config_json.es_amazonia no está en True → la leyenda 2002 no saldrá.")
            print("      La factura exonerada igual es válida; definir si PSP debe llevar 2002.")
        print("=" * 82)
    finally:
        db.close()


if __name__ == '__main__':
    main()
