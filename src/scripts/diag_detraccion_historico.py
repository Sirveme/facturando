#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_detraccion_historico.py — SOLO LECTURA.

Zanja la duda de regresión: ¿alguna detracción salió ACEPTADA alguna vez, y con
qué listID (tipo de operación) en su XML guardado? Compara el XML almacenado
(columna comprobante.xml) de las detracciones aceptadas vs rechazadas.

Evidencia definitiva:
 - Si alguna detracción ACEPTADA tiene listID="1001" en su XML → el código ANTES
   emitía 1001 y algo lo cambió a 0101 (regresión real; hay que restaurar 1001).
 - Si las aceptadas (si las hay) tienen listID="0101" → SUNAT aceptó 0101 y el bug
   es otro.
 - Si NO hay ninguna detracción aceptada → nunca funcionó end-to-end (bug latente,
   no regresión de nuestros cambios).

No escribe NADA. Ejecutar EN RAILWAY:
    python -m src.scripts.diag_detraccion_historico
"""
from lxml import etree

from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante


def _parse_xml(blob):
    """Devuelve (listID, tiene_paymentterms_detraccion, invoicetypecode_str) del XML guardado."""
    if not blob:
        return (None, None, '(sin XML guardado)')
    try:
        root = etree.fromstring(blob if isinstance(blob, bytes) else blob.encode())
    except Exception as e:
        return (None, None, f'(no parseable: {e})')
    itc = None
    for el in root.iter('{*}InvoiceTypeCode'):
        itc = el
        break
    list_id = itc.get('listID') if itc is not None else None
    itc_str = etree.tostring(itc).decode()[:200] if itc is not None else '(sin InvoiceTypeCode)'
    tiene_det = False
    for el in root.iter('{*}PaymentTerms'):
        ids = [x.text for x in el.iter('{*}ID')]
        if 'Detraccion' in ids:
            tiene_det = True
            break
    return (list_id, tiene_det, itc_str)


def main():
    db = SessionLocal()
    try:
        comps = (db.query(Comprobante)
                 .filter(Comprobante.detraccion_monto.isnot(None))
                 .order_by(Comprobante.estado, Comprobante.creado_en.desc())
                 .all())
        print("=" * 100)
        print(f"COMPROBANTES CON DETRACCIÓN (detraccion_monto NOT NULL): {len(comps)}")
        print("=" * 100)
        rucs = {}
        for e in db.query(Emisor).all():
            rucs[e.id] = e.ruc

        aceptadas_con_listid = {}
        print(f"{'ruc':12} {'serie-num':14} {'estado':16} {'creado':16} {'listID':7} {'SPOT?':6} {'det_monto'}")
        print("-" * 100)
        for c in comps:
            list_id, tiene_det, _ = _parse_xml(c.xml)
            creado = c.creado_en.strftime('%Y-%m-%d %H:%M') if c.creado_en else '—'
            ruc = rucs.get(c.emisor_id, '?')
            print(f"{ruc:12} {c.serie}-{c.numero:<8} {str(c.estado):16} {creado:16} "
                  f"{str(list_id):7} {str(tiene_det):6} {c.detraccion_monto}")
            if str(c.estado).startswith('aceptad'):
                aceptadas_con_listid.setdefault(str(list_id), 0)
                aceptadas_con_listid[str(list_id)] += 1

        print("\n" + "=" * 100)
        print("VEREDICTO")
        print("=" * 100)
        aceptadas = [c for c in comps if str(c.estado).startswith('aceptad')]
        print(f"Detracciones ACEPTADAS: {len(aceptadas)}  ·  listID de las aceptadas: {aceptadas_con_listid or '—'}")
        if not aceptadas:
            print(" ⇒ NUNCA hubo una detracción aceptada → no es regresión de nuestros cambios;")
            print("   el listID='0101' es un bug latente/original. Fix: emitir listID='1001' con SPOT.")
        elif '1001' in aceptadas_con_listid:
            print(" ⇒ Hubo detracciones aceptadas con listID='1001' → el código ANTES emitía 1001.")
            print("   REGRESIÓN CONFIRMADA: algo cambió el listID a '0101'. Restaurar '1001' con SPOT.")
            # Mostrar el XML de la aceptada más reciente con 1001, para comparar
            for c in aceptadas:
                lid, _, itc = _parse_xml(c.xml)
                if lid == '1001':
                    print("\n   Ejemplo ACEPTADA (listID=1001):", rucs.get(c.emisor_id), c.serie + '-' + str(c.numero))
                    print("   ", itc)
                    break
        elif '0101' in aceptadas_con_listid:
            print(" ⇒ Hubo detracciones aceptadas con listID='0101' → SUNAT aceptó 0101; el bug del")
            print("   3128 sería otro (revisar más a fondo el bloque SPOT vs esas aceptadas).")
        print("=" * 100)
    finally:
        db.close()


if __name__ == '__main__':
    main()
