#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reclasificar_opcion_c.py — Reclasifica comprobantes 'aceptado_con_observaciones' cuyo CDR
definitivo (código 0) trae SOLO observaciones informativas (CODIGOS_OBS_INFORMATIVOS,
default 4094,4252) → 'aceptado'. Conserva RespuestaSunat.observaciones (el detalle se guarda).
Los que tengan alguna observación SUSTANTIVA (4013/4207/4028/4367/...) se quedan igual.

USO:
    python -m src.scripts.reclasificar_opcion_c                 # DRY-RUN (no escribe)
    python -m src.scripts.reclasificar_opcion_c --confirm --expect 565
                                                                # aplica; ROLLBACK si != 565

Seguro: transacción única + SET LOCAL lock_timeout='3s' + verificación de conteo exacto.
NO toca stock, XML ni emisión. Solo cambia Comprobante.estado de los que califican.
"""
import re
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text
from lxml import etree

from src.api.dependencies import SessionLocal
from src.core.config import settings
from src.models.models import Comprobante, RespuestaSunat, Emisor

_RE_ANCLA = re.compile(r'^\s*(4\d{3})\b')


def _informativos():
    raw = getattr(settings, 'CODIGOS_OBS_INFORMATIVOS', '') or ''
    return {c.strip() for c in raw.split(',') if c.strip()}


def _obs_reales(cdr_xml, guardadas):
    """Mismos códigos 4xxx que ve la clasificación: ancla al inicio de la Note o
    languageLocaleID; fallback a las observaciones guardadas si no hay XML parseable."""
    if cdr_xml:
        try:
            xmlb = cdr_xml if isinstance(cdr_xml, (bytes, bytearray)) else str(cdr_xml).encode()
            doc = etree.fromstring(xmlb)
            cods = []
            for n in doc.xpath(".//*[local-name()='Note']"):
                txt = (n.text or '').strip()
                loc = (n.get('languageLocaleID') or '').strip()
                if re.fullmatch(r'4\d{3}', loc):
                    cods.append(loc)
                else:
                    m = _RE_ANCLA.match(txt)
                    if m:
                        cods.append(m.group(1))
            for rc in doc.xpath(".//*[local-name()='ResponseCode']"):
                c = (rc.text or '').strip()
                if re.fullmatch(r'4\d{3}', c):
                    cods.append(c)
            return sorted(set(cods))
        except Exception:
            pass
    return sorted(set(str(o.get('codigo')) for o in (guardadas or [])))


def _calcular_objetivo(db):
    """IDs a reclasificar + breakdown. Un comprobante califica si su CDR código 0 trae
    observaciones NO vacías y TODAS informativas."""
    informativos = _informativos()
    comps = (db.query(Comprobante).filter(
        Comprobante.estado == 'aceptado_con_observaciones').all())
    ids = [c.id for c in comps]
    resps = db.query(RespuestaSunat).filter(RespuestaSunat.comprobante_id.in_(ids)).all()
    por_comp = defaultdict(list)
    for r in resps:
        por_comp[r.comprobante_id].append(r)

    objetivo, se_quedan = [], Counter()
    combo = Counter()
    for c in comps:
        rs = por_comp.get(c.id, [])
        cero = [r for r in rs if str(r.codigo_cdr or '') == '0']
        def_r = sorted(cero, key=lambda r: (getattr(r, 'recibido_en', None) or r.id))[-1] if cero else None
        codes = set(_obs_reales(def_r.cdr_xml if def_r else None,
                                def_r.observaciones if def_r else None))
        if codes and codes.issubset(informativos):
            objetivo.append(c.id)
            combo[tuple(sorted(codes))] += 1
        else:
            se_quedan[tuple(sorted(codes)) or ('(vacio)',)] += 1
    return objetivo, combo, se_quedan, informativos


def main():
    confirm = '--confirm' in sys.argv
    expect = None
    if '--expect' in sys.argv:
        try:
            expect = int(sys.argv[sys.argv.index('--expect') + 1])
        except Exception:
            print("🛑 --expect requiere un número"); sys.exit(2)

    db = SessionLocal()
    try:
        objetivo, combo, se_quedan, informativos = _calcular_objetivo(db)
        n = len(objetivo)
        print(f"Códigos informativos: {sorted(informativos)}")
        print(f"A reclasificar → 'aceptado': {n}")
        for k, v in combo.most_common():
            print(f"    {v:4d}  {k}")
        print(f"Se quedan 'aceptado_con_observaciones': {sum(se_quedan.values())}")
        for k, v in se_quedan.most_common():
            print(f"    {v:4d}  {k}")

        if not confirm:
            print("\n[DRY-RUN] No se escribió nada. Para aplicar:"
                  f" --confirm --expect {n}")
            return

        if expect is None or expect != n:
            print(f"\n🛑 ABORTADO: --expect ({expect}) != objetivo real ({n}). "
                  "Revisa antes de aplicar."); sys.exit(1)

        # ── aplicar en una transacción con lock_timeout y verificación exacta ──
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        res = (db.query(Comprobante)
               .filter(Comprobante.id.in_(objetivo),
                       Comprobante.estado == 'aceptado_con_observaciones')
               .update({Comprobante.estado: 'aceptado'}, synchronize_session=False))
        if res != n:
            db.rollback()
            print(f"🛑 ROLLBACK: filas afectadas ({res}) != esperado ({n}).")
            sys.exit(1)
        db.commit()
        print(f"✅ COMMIT: {res} comprobantes → 'aceptado' (observaciones conservadas).")
    finally:
        db.close()


if __name__ == '__main__':
    main()
