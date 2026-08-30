#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_getstatuscdr_raw.py — DIAGNÓSTICO: imprime la respuesta CRUDA de getStatusCdr de SUNAT
beta (billConsultService), SIN parsear. No modifica nada (ni SUNAT ni BD ni sunat_client.py).

Envía EXACTAMENTE el mismo envelope que consultar_estado_cdr y muestra: HTTP status, headers,
el BODY crudo completo, y si es SOAP Fault, el faultcode/faultstring. Resuelve la clave SOL del
emisor desde la BD (Fernet). Un solo caso basta.

USO (en Railway o local):
    python -m src.scripts.debug_getstatuscdr_raw 10053701537 03 B001 3
    (por defecto: RUC 10053701537, tipo 03, serie B001, numero 3)
"""
import os
import sys

import certifi

# Fix CA bundle local (Windows): REQUESTS_CA_BUNDLE roto → forzar certifi solo en este proceso.
_CA = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = _CA
os.environ['SSL_CERT_FILE'] = _CA
os.environ['CURL_CA_BUNDLE'] = _CA

import requests
from cryptography.fernet import Fernet
from lxml import etree

from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.models.models import Emisor
from src.services.sunat_client import SUNAT_CONSULT_BETA_URL, SUNAT_CONSULT_PROD_URL


def _sol_pass_plain(emisor):
    if not emisor.sol_password:
        return None
    try:
        return Fernet(settings.encryption_key.encode()).decrypt(emisor.sol_password.encode()).decode()
    except Exception:
        return emisor.sol_password


def main():
    ruc = sys.argv[1] if len(sys.argv) > 1 else '10053701537'
    tipo = sys.argv[2] if len(sys.argv) > 2 else '03'
    serie = sys.argv[3] if len(sys.argv) > 3 else 'B001'
    numero = str(int(sys.argv[4])) if len(sys.argv) > 4 else '3'

    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not emisor:
            print(f"❌ No existe emisor {ruc}"); return
        if getattr(emisor, 'produccion', False):
            print("🛑 Emisor en produccion=True — abortado (este debug es para BETA)."); return

        sol_pass = _sol_pass_plain(emisor)
        username = f"{ruc}{emisor.sol_usuario}" if emisor.sol_usuario else ruc
        endpoint = SUNAT_CONSULT_BETA_URL  # beta

        envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:ser="http://service.sunat.gob.pe"
                  xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <soapenv:Header><wsse:Security><wsse:UsernameToken>
    <wsse:Username>{username}</wsse:Username>
    <wsse:Password>{sol_pass or ''}</wsse:Password>
  </wsse:UsernameToken></wsse:Security></soapenv:Header>
  <soapenv:Body>
    <ser:getStatusCdr>
      <rucComprobante>{ruc}</rucComprobante>
      <tipoComprobante>{tipo}</tipoComprobante>
      <serieComprobante>{serie}</serieComprobante>
      <numeroComprobante>{numero}</numeroComprobante>
    </ser:getStatusCdr>
  </soapenv:Body>
</soapenv:Envelope>"""

        print("=" * 96)
        print(f"POST {endpoint}")
        print(f"WSSE Username: {username}   clave: {'*** (cargada)' if sol_pass else 'FALTA'}")
        print(f"Consulta: tipo={tipo} serie={serie} numero={numero}")
        print("=" * 96)
        print("---- ENVELOPE ENVIADO (clave oculta) ----")
        print(envelope.replace(sol_pass, '***') if sol_pass else envelope)

        headers = {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': '"urn:getStatusCdr"'}
        resp = requests.post(endpoint, data=envelope.encode('utf-8'), headers=headers, timeout=45)

        print("\n---- RESPUESTA HTTP ----")
        print(f"status_code : {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('Content-Type')}")
        print(f"body bytes  : {len(resp.content)}")
        print("\n---- BODY CRUDO (SIN PARSEAR) ----")
        print(resp.content.decode('utf-8', errors='replace'))

        print("\n---- ANÁLISIS DE NODOS ----")
        try:
            doc = etree.fromstring(resp.content)
            tags = [el.tag.split('}')[-1] for el in doc.iter()]
            print("Tags encontrados:", tags[:50])
            for name in ('faultcode', 'faultstring', 'statusCode', 'statusMessage', 'content',
                         'statusCdr', 'code', 'message'):
                els = doc.xpath(".//*[local-name()='%s']" % name)
                if els:
                    print(f"  <{name}> = {((els[0].text or '')[:150])!r}")
        except Exception as e:
            print("(no es XML parseable):", e)
        print("=" * 96)
        print("Pega TODO este bloque (sobre todo el BODY CRUDO) para diagnosticar el mapeo.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
