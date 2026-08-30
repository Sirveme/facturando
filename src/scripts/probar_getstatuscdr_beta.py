#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probar_getstatuscdr_beta.py — Verifica getStatusCdr contra SUNAT (A2). SOLO LECTURA:
getStatusCdr no modifica nada en SUNAT ni en la BD.

Resuelve las credenciales SOL del PROPIO EMISOR desde la BD (desencriptando con Fernet,
igual que el envío normal) — NO se pasan claves por línea de comandos. El entorno
(beta/producción) se toma de `emisor.produccion`; si el emisor está en producción, ABORTA
por seguridad (este script es para probar en BETA).

Nota: getStatusCdr NO usa el certificado — es una consulta con WSSE UsernameToken (usuario +
clave SOL). Solo necesita esas credenciales.

USO (en Railway). Corre los 5 casos por defecto del emisor de prueba:
    python -m src.scripts.probar_getstatuscdr_beta 10053701537

O especifica comprobantes propios como SERIE-NUMERO (tipo inferido: F→01, B→03):
    python -m src.scripts.probar_getstatuscdr_beta 10053701537 B001-3 B001-4 B001-99
"""
import os
import sys

import certifi

# --- Fix CA bundle LOCAL (Windows) ---------------------------------------------------------
# En esta PC, REQUESTS_CA_BUNDLE apunta a C:\xero\cacert.pem (otro proyecto) que NO existe, y
# requests la prioriza → "Could not find a suitable TLS CA certificate bundle". Forzamos el
# bundle de 'certifi' SOLO para este proceso, antes de cualquier request. NO afecta producción
# (Railway/Linux no tiene esa variable) ni el código de envío (sunat_client queda intacto).
_CA = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = _CA
os.environ['SSL_CERT_FILE'] = _CA
os.environ['CURL_CA_BUNDLE'] = _CA
# -------------------------------------------------------------------------------------------

from cryptography.fernet import Fernet

from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.models.models import Emisor
from src.services.sunat_client import consultar_estado_cdr

# Casos por defecto (emisor de prueba 10053701537). (serie, numero, resultado esperado)
DEFAULT_CASOS = [
    ("B001", 3, "aceptado"),
    ("B001", 4, "aceptado"),
    ("B001", 2, "rechazado"),
    ("B001", 6, "rechazado"),
    ("B001", 99, "no_existe"),
]


def _tipo_por_serie(serie):
    """Infiere el tipo de comprobante por el prefijo de la serie."""
    p = (serie or "")[:1].upper()
    return {"F": "01", "B": "03", "T": "01"}.get(p, "01")


def _sol_pass_plain(emisor):
    """Desencripta la clave SOL del emisor (Fernet), igual que el flujo de envío."""
    if not emisor.sol_password:
        return None
    try:
        f = Fernet(settings.encryption_key.encode())
        return f.decrypt(emisor.sol_password.encode()).decode()
    except Exception:
        return emisor.sol_password


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ruc = sys.argv[1]

    # Comprobantes: de la línea de comandos (SERIE-NUMERO) o los 5 por defecto.
    if len(sys.argv) > 2:
        casos = []
        for tok in sys.argv[2:]:
            serie, num = tok.rsplit("-", 1)
            casos.append((serie, int(num), "?"))
    else:
        casos = DEFAULT_CASOS

    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not emisor:
            print(f"❌ No existe emisor con RUC {ruc}")
            return

        # GUARDA DE SEGURIDAD: este script es para BETA.
        if getattr(emisor, "produccion", False):
            print(f"🛑 El emisor {ruc} está en produccion=True → getStatusCdr iría a PRODUCCIÓN, "
                  f"no a beta. Abortado por seguridad. (Para probar A2 usa un emisor con produccion=False.)")
            return

        sol_pass = _sol_pass_plain(emisor)

        print("=" * 96)
        print(f"VERIFICACIÓN getStatusCdr — SUNAT BETA (billConsultService)")
        print(f"Emisor: {ruc} — {emisor.razon_social}   produccion={getattr(emisor,'produccion',False)} "
              f"(→ BETA)   sol_usuario={emisor.sol_usuario}   sol_pass={'cargada' if sol_pass else 'FALTA'}")
        print("=" * 96)
        print(f"{'COMPROBANTE':<18} {'TIPO':<5} {'ESTADO':<12} {'statusCode':<12} {'ESPERADO':<10} statusMessage")
        print("-" * 96)

        for serie, num, esperado in casos:
            tipo = _tipo_por_serie(serie)
            res = consultar_estado_cdr(
                ruc, tipo, serie, int(num),
                sol_usuario=emisor.sol_usuario, sol_password=sol_pass,
                use_production=getattr(emisor, "produccion", False),  # False → BETA
            )
            doc = f"{serie}-{int(num):08d}"
            marca = "✓" if (esperado == "?" or res.get("estado") == esperado) else "✗ DIFERENTE"
            print(f"{doc:<18} {tipo:<5} {str(res.get('estado')):<12} {str(res.get('status_code')):<12} "
                  f"{esperado:<10} {res.get('status_msg')}  {marca}")

        print("-" * 96)
        print("Confirma: aceptados→'aceptado', rechazados→'rechazado', inexistente→'no_existe'.")
        print("Si el inexistente dio 'incierto', pásame su statusCode/statusMessage para agregarlo")
        print("a _GETSTATUSCDR_NO_EXISTE en sunat_client.py. Solo tras esto, activar en prod.")
        print("=" * 96)

    finally:
        db.close()


if __name__ == "__main__":
    main()
