#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_cdr_clasificacion.py — PRUEBA LOCAL (sin BD, sin red, sin SUNAT).

Verifica los 3 casos de clasificación de CDR con ejemplos:
  1) ResponseCode 0 sin notas          → aceptado
  2) ResponseCode 0 con nota 4xxx       → aceptado_con_observaciones (+ extrae código/texto)
  3) ResponseCode 2xxx                  → rechazado (NO descuenta stock)

Usa el parser real (sunat_client._parse_cdr) y la clasificación real
(envio_sunat._clasificar_estado_cdr).
"""
import os
import sys

# Settings() exige estas env para importar envio_sunat; valores dummy (no se conecta a nada).
os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost:5432/dummy')
os.environ.setdefault('SECRET_KEY', 'dummy')
os.environ.setdefault('ENCRYPTION_KEY', 'dummy')
os.environ.setdefault('JWT_SECRET', 'dummy')

from src.services.sunat_client import _parse_cdr          # noqa: E402
from src.tasks.envio_sunat import _clasificar_estado_cdr  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NS = ('xmlns:ar="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2" '
      'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
      'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')

CDR_ACEPTADO = f"""<?xml version="1.0" encoding="UTF-8"?>
<ar:ApplicationResponse {NS}>
  <cbc:ID>12345</cbc:ID>
  <cac:DocumentResponse><cac:Response>
    <cbc:ReferenceID>F001-1</cbc:ReferenceID>
    <cbc:ResponseCode>0</cbc:ResponseCode>
    <cbc:Description>La Factura numero F001-1, ha sido aceptada</cbc:Description>
  </cac:Response></cac:DocumentResponse>
</ar:ApplicationResponse>""".encode('utf-8')

CDR_CON_OBS = f"""<?xml version="1.0" encoding="UTF-8"?>
<ar:ApplicationResponse {NS}>
  <cbc:ID>12346</cbc:ID>
  <cac:DocumentResponse><cac:Response>
    <cbc:ReferenceID>F001-15</cbc:ReferenceID>
    <cbc:ResponseCode>0</cbc:ResponseCode>
    <cbc:Description>La Factura numero F001-15, ha sido aceptada</cbc:Description>
    <cbc:Note>4252 - El dato ingresado como atributo @listName es incorrecto. - Error en la linea: 1 Tributo: 1000</cbc:Note>
  </cac:Response></cac:DocumentResponse>
</ar:ApplicationResponse>""".encode('utf-8')

CDR_RECHAZADO = f"""<?xml version="1.0" encoding="UTF-8"?>
<ar:ApplicationResponse {NS}>
  <cbc:ID>12347</cbc:ID>
  <cac:DocumentResponse><cac:Response>
    <cbc:ReferenceID>F800-1</cbc:ReferenceID>
    <cbc:ResponseCode>2027</cbc:ResponseCode>
    <cbc:Description>2027 - El XML no contiene el tag o no existe informacion de Importe total</cbc:Description>
  </cac:Response></cac:DocumentResponse>
</ar:ApplicationResponse>""".encode('utf-8')


def _check(nombre, cdr_bytes, cod_esp, obs_count_esp, estado_esp):
    parsed = _parse_cdr(cdr_bytes)
    cod = parsed.get('codigo')
    obs = parsed.get('observaciones') or []
    estado = _clasificar_estado_cdr(cod, obs)
    ok = (str(cod) == cod_esp) and (len(obs) == obs_count_esp) and (estado == estado_esp)
    print(f"\n[{'PASS' if ok else 'FALLA'}] {nombre}")
    print(f"   codigo      = {cod}      (esperado {cod_esp})")
    print(f"   #observ.    = {len(obs)} (esperado {obs_count_esp})  {obs if obs else ''}")
    print(f"   estado      = {estado}   (esperado {estado_esp})")
    return ok


def main():
    results = []
    results.append(_check("Caso 1: ResponseCode 0 sin notas",
                          CDR_ACEPTADO, '0', 0, 'aceptado'))
    results.append(_check("Caso 2: ResponseCode 0 con nota 4252",
                          CDR_CON_OBS, '0', 1, 'aceptado_con_observaciones'))
    results.append(_check("Caso 3: ResponseCode 2027 (rechazo)",
                          CDR_RECHAZADO, '2027', 0, 'rechazado'))

    # Sanity extra: que la rama de rechazo NO coincida con 'aceptado*' (⇒ no descuenta stock)
    extra_ok = _clasificar_estado_cdr('3128', []) == 'rechazado' and \
               _clasificar_estado_cdr('2119', []) == 'rechazado'
    print(f"\n[{'PASS' if extra_ok else 'FALLA'}] Extra: 3128 y 2119 → rechazado (sin stock)")
    results.append(extra_ok)

    print("\n" + "=" * 60)
    print("RESULTADO:", "TODO PASA ✅" if all(results) else "HAY FALLAS ❌")
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
