#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspeccionar_comprobante.py — AUDITORÍA DE SOLO LECTURA de un comprobante.

Reporta el estado real de una factura/boleta, su CDR de SUNAT, si ya tiene NC asociada,
y si pasa el filtro de la lista "para emitir Nota de Crédito". No escribe NADA.

Ejecutar EN RAILWAY:
    python -m src.scripts.inspeccionar_comprobante                 # F778-4 de RUC 10736459791
    python -m src.scripts.inspeccionar_comprobante 10736459791 F778 4
"""
import sys

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante, RespuestaSunat

RUC = sys.argv[1] if len(sys.argv) > 1 else '10736459791'
SERIE = sys.argv[2] if len(sys.argv) > 2 else 'F778'
NUMERO = int(sys.argv[3]) if len(sys.argv) > 3 else 4

# Réplica EXACTA del filtro de la lista de NC (frontend.py: nota_credito_page)
NC_LIST_TIPOS = ('01', '03')
NC_LIST_ESTADO = 'aceptado'


def main():
    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == RUC).first()
        if not emisor:
            print(f"❌ No existe emisor con RUC {RUC}"); return

        c = (db.query(Comprobante)
             .filter(Comprobante.emisor_id == emisor.id,
                     Comprobante.serie == SERIE, Comprobante.numero == NUMERO)
             .first())
        if not c:
            print(f"❌ No existe {SERIE}-{NUMERO} para el emisor {RUC}"); return

        print("=" * 72)
        print(f"COMPROBANTE {c.numero_formato or f'{SERIE}-{NUMERO}'}  (RUC {RUC})")
        print("=" * 72)
        print(f"  id                 : {c.id}")
        print(f"  tipo_documento     : {c.tipo_documento}  (01=Factura, 03=Boleta, 07=NC)")
        print(f"  ESTADO             : {c.estado!r}   <<< clave para la lista de NC")
        print(f"  monto_total        : {c.monto_total}")
        print(f"  fecha_emision      : {c.fecha_emision}")
        print(f"  creado_en          : {c.creado_en}")
        print(f"  actualizado_en     : {c.actualizado_en}")
        print(f"  hash_cpe           : {c.hash_cpe or '(NULL)'}")
        print(f"  intentos_envio     : {c.intentos_envio}")
        print(f"  procesando_desde   : {c.procesando_desde}")
        print(f"  descripcion_resp.  : {getattr(c, 'descripcion_respuesta', None)}")

        # CDR de SUNAT (tabla RespuestaSunat)
        resp = (db.query(RespuestaSunat)
                .filter(RespuestaSunat.comprobante_id == c.id)
                .order_by(RespuestaSunat.recibido_en.desc())
                .first())
        print("\n  --- CDR / RespuestaSunat ---")
        if not resp:
            print("  (sin RespuestaSunat -> nunca llegó CDR)")
        else:
            print(f"  codigo_cdr         : {resp.codigo_cdr!r}   "
                  f"(0=aceptado, 2xxx=aceptado con observaciones, otro=rechazo)")
            print(f"  descripcion        : {resp.descripcion}")
            print(f"  tiene cdr_xml      : {'sí' if resp.cdr_xml else 'no'}")
            print(f"  recibido_en        : {resp.recibido_en}")

        # ¿Ya tiene NC asociada? (NC = tipo 07 que referencia su numero_formato)
        ncs = (db.query(Comprobante)
               .filter(Comprobante.emisor_id == emisor.id,
                       Comprobante.tipo_documento == '07',
                       Comprobante.doc_referencia_numero == c.numero_formato)
               .all())
        print("\n  --- Notas de Crédito que la referencian ---")
        if not ncs:
            print("  (ninguna)")
        else:
            for nc in ncs:
                print(f"  {nc.numero_formato}  estado={nc.estado}  motivo={nc.motivo_nota}")

        # ¿Pasa el filtro de la lista de NC?
        print("\n" + "-" * 72)
        pasa_tipo = c.tipo_documento in NC_LIST_TIPOS
        pasa_estado = c.estado == NC_LIST_ESTADO
        print("FILTRO lista 'para emitir NC' = tipo_documento in ('01','03') AND estado == 'aceptado'")
        print(f"  tipo in (01,03)?         {pasa_tipo}   (tipo={c.tipo_documento})")
        print(f"  estado == 'aceptado'?    {pasa_estado}   (estado={c.estado!r})")
        if pasa_tipo and pasa_estado:
            print("  ✅ DEBERÍA aparecer en la lista (revisar el limit(50) por fecha si hay muchas).")
        else:
            motivo = []
            if not pasa_tipo:
                motivo.append(f"tipo {c.tipo_documento} no es 01/03")
            if not pasa_estado:
                motivo.append(f"estado {c.estado!r} != 'aceptado'")
            print(f"  ❌ NO aparece porque: {'; '.join(motivo)}")
            if c.estado == 'aceptado_con_observaciones':
                print("     → OJO: 'aceptado_con_observaciones' SÍ fue aceptada por SUNAT y es anulable,")
                print("       pero el filtro exacto ('== aceptado') la excluye. Es un bug del filtro.")
        print("-" * 72)

    finally:
        db.close()


if __name__ == '__main__':
    main()
