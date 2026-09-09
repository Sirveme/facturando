#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probar_clasificador_a2.py — SOLO LECTURA.

Muestra QUÉ versión de la clasificación A2 corre en ESTE entorno (Railway),
para confirmar si el build desplegado es el actual o uno viejo (deploy lag).
No toca BD ni SUNAT: solo importa las funciones puras y las evalúa, e imprime
el código fuente de clasificar_error_a2 tal como está desplegado.

Ejecutar EN RAILWAY:
    python -m src.scripts.probar_clasificador_a2
"""
import inspect

from src.services import notificaciones_sunat as N
from src.services.notificaciones_sunat import clasificar_error_a2, decidir_reintento

MSG_3128 = ("El XML contiene información de código de bien y servicio de detracción "
            "que no corresponde al tipo de operación (nodo cac:PaymentTerms/cbc:ID valor Detraccion)")

# (codigo, mensaje, categoria ESPERADA post-arreglo, etiqueta)
CASOS = [
    ('3128',       MSG_3128,                            'contenido',   '3128 real (venta de bienes)'),
    ('3128',       '',                                  'contenido',   '3128 sin mensaje'),
    ('2017',       'numero de documento del receptor',  'contenido',   '2017'),
    ('3100',       'Error de conexion con el servicio', 'contenido',   '3xxx + msg con "conexion" (orden)'),
    ('0111',       'Servicio temporalmente no disponible', 'transitorio', '0111 servicio caido'),
    ('',           'Read timed out',                    'transitorio', 'sin codigo + timeout (red)'),
    ('1033',       'registrado previamente',            'ya_aceptado', '1033 ya aceptado'),
    ('Client.0102', 'rejected by policy',               'perfil',      'fault de perfil'),
]


def main():
    print("=" * 88)
    print("VERIFICACIÓN A2 — versión desplegada en ESTE entorno")
    print("=" * 88)
    print(f"módulo: {inspect.getfile(N)}")
    print("-" * 88)
    print("FUENTE de clasificar_error_a2() tal como corre AQUÍ (esto revela la versión):")
    print("-" * 88)
    print(inspect.getsource(clasificar_error_a2))
    print("-" * 88)
    print(f"{'codigo':13} {'cat obtenida':13} {'accion':16} {'esperado':12} caso")
    print("-" * 88)
    for cod, msg, esperado, label in CASOS:
        cat = clasificar_error_a2(cod, msg)
        acc = decidir_reintento(cat, 0, False, 3)
        flag = 'OK' if cat == esperado else '*** DIFERENTE ***'
        print(f"{cod:13} {cat:13} {acc:16} {esperado:12} [{flag}] {label}")
    print("-" * 88)

    veredicto = clasificar_error_a2('3128', MSG_3128)
    print(f"VEREDICTO 3128 → {veredicto}")
    if veredicto == 'transitorio':
        print("  ⇒ El build DESPLEGADO es VIEJO (deploy lag): reintenta rechazos de contenido.")
        print("     El reorden + redeploy VERIFICADO lo corrige.")
    elif veredicto == 'contenido':
        print("  ⇒ El build desplegado YA clasifica 3128 como 'contenido' (rechaza, no reintenta).")
        print("     Si el log de ayer mostró 'transitorio', el mensaje registrado traía otra")
        print("     sub-causa (keyword) — habría que ver ese mensaje. El reorden lo blinda igual.")
    else:
        print("  ⇒ Resultado inesperado; pega toda esta salida para analizar.")
    print("=" * 88)
    print("Pega TODA esta salida (incluida la fuente) para decidir el siguiente paso.")


if __name__ == '__main__':
    main()
