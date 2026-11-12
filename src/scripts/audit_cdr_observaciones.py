#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_cdr_observaciones.py — READ-ONLY. No escribe ni corrige nada.

A) Rechazos MAL clasificados: comprobantes en estado 'aceptado_con_observaciones'
   cuyo codigo_cdr empieza en 2 o 3 (según SUNAT 2xxx/3xxx = RECHAZO).
B) Observaciones NO detectadas: comprobantes con codigo_cdr = 0 cuyo cdr_xml
   contiene notas 4xxx (aceptado con observaciones real, hoy guardado como 'aceptado').

Para cada caso: emisor, serie-número, fecha, monto, código y descripción.
"""
import re
import sys
from lxml import etree

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, RespuestaSunat

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RE_4XXX = re.compile(r'\b(4\d{3})\b')


def _cdr_text(xml):
    if not xml:
        return None
    return xml.decode('utf-8', 'replace') if isinstance(xml, (bytes, bytearray)) else str(xml)


def _notas_4xxx(xml):
    """Devuelve lista de (codigo4xxx, texto_nota) encontradas en el cdr_xml."""
    t = _cdr_text(xml)
    if not t:
        return []
    try:
        doc = etree.fromstring(t.encode('utf-8'))
    except Exception:
        # fallback: regex sobre el texto crudo
        return [(m, '') for m in set(RE_4XXX.findall(t))]
    out = []
    # Notas explícitas
    for n in doc.xpath(".//*[local-name()='Note']"):
        txt = (n.text or '').strip()
        m = RE_4XXX.search(txt)
        if m:
            out.append((m.group(1), txt[:180]))
    # ResponseCode 4xxx en cualquier DocumentResponse/Response
    for rc in doc.xpath(".//*[local-name()='ResponseCode']"):
        code = (rc.text or '').strip()
        if re.fullmatch(r'4\d{3}', code):
            desc = rc.xpath("../*[local-name()='Description']/text()")
            out.append((code, (desc[0].strip()[:180] if desc else '')))
    return out


def _fila(em, comp, resp, extra=''):
    return (f"  {em.ruc if em else '?':<11} {comp.numero_formato:<16} "
            f"{str(comp.fecha_emision)[:10]:<10} {str(comp.monto_total):>10}  "
            f"cod={resp.codigo_cdr if resp else '?'}  {(resp.descripcion if resp else '')[:60]}{extra}")


def main():
    db = SessionLocal()
    try:
        print("=" * 90)
        print("A) RECHAZOS MAL CLASIFICADOS — estado 'aceptado_con_observaciones' con codigo 2xxx/3xxx")
        print("=" * 90)
        q = (db.query(Comprobante, RespuestaSunat, Emisor)
             .join(RespuestaSunat, RespuestaSunat.comprobante_id == Comprobante.id)
             .join(Emisor, Emisor.id == Comprobante.emisor_id)
             .filter(Comprobante.estado == 'aceptado_con_observaciones'))
        a = 0
        for comp, resp, em in q.all():
            cod = (resp.codigo_cdr or '')
            if cod.startswith('2') or cod.startswith('3'):
                a += 1
                print(_fila(em, comp, resp))
        print(f"  → {a} comprobante(s) con rechazo mal clasificado." if a else "  ✅ Ninguno.")

        print("\n" + "=" * 90)
        print("B) OBSERVACIONES NO DETECTADAS — codigo_cdr = 0 pero cdr_xml tiene notas 4xxx")
        print("=" * 90)
        q2 = (db.query(Comprobante, RespuestaSunat, Emisor)
              .join(RespuestaSunat, RespuestaSunat.comprobante_id == Comprobante.id)
              .join(Emisor, Emisor.id == Comprobante.emisor_id)
              .filter(RespuestaSunat.codigo_cdr == '0',
                      RespuestaSunat.cdr_xml.isnot(None)))
        b = 0
        total_rev = 0
        for comp, resp, em in q2.all():
            total_rev += 1
            notas = _notas_4xxx(resp.cdr_xml)
            if notas:
                b += 1
                codes = ', '.join(sorted({c for c, _ in notas}))
                print(_fila(em, comp, resp, extra=f"  OBS[{codes}]"))
                for c, txt in notas[:3]:
                    print(f"        · {c}: {txt}")
        print(f"\n  (revisados {total_rev} CDR con codigo 0)")
        print(f"  → {b} con observaciones 4xxx no detectadas." if b else "  ✅ Ninguno.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
