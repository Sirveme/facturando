#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_pagook_form.py — SOLO LECTURA. Reproduce el payload EXACTO que pagook_client
arma desde el flujo del formulario /pagar/confirmar y muestra la respuesta REAL de
PagoOK (status + body). Compara formatos de fecha para encontrar el que da 422.

No marca nada ni emite. `consultar` es una lectura inofensiva.
Ejecutar EN RAILWAY (Facturalo):
    python -m src.scripts.diag_pagook_form
"""
import os

import certifi
_CA = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = _CA
os.environ['SSL_CERT_FILE'] = _CA
os.environ['CURL_CA_BUNDLE'] = _CA

import httpx
from src.services import pagook_client as pk

# Espía: imprime el body saliente EXACTO (como lo arma pagook_client) + la respuesta real.
_real_post = httpx.post
def _spy(url, **kw):
    print(f"  → POST {url}")
    print(f"    body: {kw.get('json')}")
    r = _real_post(url, **kw)
    print(f"    ← HTTP {r.status_code} · {r.text[:400]}")
    return r
pk.httpx.post = _spy


def probar(label, fecha, pagador=None, canal=None, codigo=None):
    print("=" * 88)
    print(f"CASO: {label}")
    res = pk.consultar_pago("4.00", fecha, nombre_pagador_declarado=pagador,
                            canal=canal, codigo_operacion=codigo)
    print(f"    consultar_pago() → nivel={res.get('nivel')} motivo={res.get('motivo')}")


def main():
    print("API Key presente:", bool(os.environ.get("PAGOOK_API_KEY")),
          "· base:", os.environ.get("PAGOOK_BASE_URL") or "(default pagook.pro/api/v1)")

    # 1) Como el test que dio 200 (fecha completa con segundos + zona Lima)
    probar("fecha COMPLETA con tz (como test 200)", "2026-10-03T22:15:00-05:00")

    # 2) Como lo manda el <input type=datetime-local>: SIN segundos, SIN zona
    probar("datetime-local crudo (sin seg, sin tz)", "2026-10-03T22:15")

    # 3) datetime-local + segundos
    probar("con segundos, sin tz", "2026-10-03T22:15:00")

    # 4) Shape COMPLETO del formulario (fecha cruda + pagador + canal)
    probar("FORM completo (fecha cruda + pagador + canal)", "2026-10-03T22:15",
           pagador="Milton Castillo", canal="yape")

    # 5) Igual pero con fecha completa (para aislar fecha vs otros campos)
    probar("FORM con fecha completa (aísla la fecha)", "2026-10-03T22:15:00-05:00",
           pagador="Milton Castillo", canal="yape")

    print("=" * 88)
    print("LECTURA: el/los caso(s) con HTTP 422 muestran en su body QUÉ campo rechaza PagoOK.")
    print("Si solo fallan los de fecha CRUDA (2 y 4) → el bug es el formato de fecha del")
    print("datetime-local (falta segundos/zona). Fix: normalizar la fecha antes de enviarla.")


if __name__ == '__main__':
    main()
