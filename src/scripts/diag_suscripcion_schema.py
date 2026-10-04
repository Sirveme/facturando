#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_suscripcion_schema.py — READ-ONLY. Confirma si la tabla `suscripcion` VIVA
coincide con el modelo, y reproduce el INSERT que hace procesar_confirmacion
(nivel 'alta') para capturar el IntegrityError REAL — SIN tocar PagoOK y SIN
escribir nada (la transacción SIEMPRE hace rollback).

Por qué: el síntoma 'ya_procesado' (sin suscripción creada, sin consulta visible
en PagoOK) encaja con un INSERT que falla por DESAJUSTE DE ESQUEMA y que el
`except IntegrityError` del motor rotula, por error, como 'pago ya procesado'.
Este script te dice la causa EXACTA (qué columna/constraint) en el acto.

USO (en Railway):
    python -m src.scripts.diag_suscripcion_schema <RUC_cliente>
    # RUC = el emisor logueado con el que probaste (p.ej. 10053937760)
"""
import sys
import io
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from src.api.dependencies import SessionLocal, engine
from src.models.models import Suscripcion, Emisor

# Columnas que el INSERT de procesar_confirmacion REALMENTE setea (resto: default/nullable)
SETEA = ['id', 'emisor_id', 'plan', 'periodicidad', 'monto', 'moneda', 'vence',
         'estado', 'pagook_pago_id', 'pagook_nivel', 'referencia_externa']


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    ruc = pos[0].strip() if pos else None

    insp = inspect(engine)
    if 'suscripcion' not in insp.get_table_names():
        print("🛑 La tabla `suscripcion` NO EXISTE en la BD viva.")
        sys.exit(1)

    print("=" * 72)
    print("COLUMNAS DE LA TABLA VIVA `suscripcion`")
    print("=" * 72)
    db_cols = {c['name']: c for c in insp.get_columns('suscripcion')}
    for name, c in db_cols.items():
        nn = 'NOT NULL' if not c['nullable'] else 'null'
        dflt = c.get('default')
        print(f"  {name:22} {str(c['type']):18} {nn:9} default={dflt}")

    model_cols = {col.name: col for col in Suscripcion.__table__.columns}

    print("\n" + "=" * 72)
    print("DIFERENCIAS MODELO vs TABLA VIVA")
    print("=" * 72)
    faltan_en_db = [n for n in model_cols if n not in db_cols]
    sobran_en_db = [n for n in db_cols if n not in model_cols]
    print(f"  Columnas del MODELO que FALTAN en la tabla : {faltan_en_db or 'ninguna'}")
    print(f"  Columnas de la TABLA que no están en modelo: {sobran_en_db or 'ninguna'}")

    # NOT NULL en la BD que el INSERT NO setea y SIN server default → rompería el INSERT
    riesgo = []
    for name, c in db_cols.items():
        if not c['nullable'] and name not in SETEA and c.get('default') is None:
            riesgo.append(name)
    print(f"  NOT NULL sin default que el INSERT NO setea : {riesgo or 'ninguna'}")
    if riesgo:
        print("    ⚠️  CUALQUIERA de estas hace fallar el INSERT → ya_procesado falso.")

    print("\n  Índices:")
    for ix in insp.get_indexes('suscripcion'):
        print(f"    {ix['name']}  cols={ix['column_names']}  unique={ix.get('unique')}")
    for uc in insp.get_unique_constraints('suscripcion'):
        print(f"    UNIQUE {uc.get('name')}  cols={uc.get('column_names')}")

    if not ruc:
        print("\n(Para la PRUEBA de INSERT real, pásame el RUC del cliente logueado.)")
        return

    print("\n" + "=" * 72)
    print(f"PRUEBA DE INSERT (rollback garantizado) — como lo hace el motor en 'alta'")
    print("=" * 72)
    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not emisor:
            print(f"🛑 No existe emisor con RUC {ruc}.")
            return
        print(f"  Cliente: {emisor.ruc} — {emisor.razon_social} (id={emisor.id})")
        s = Suscripcion(
            id=str(uuid4()), emisor_id=emisor.id, plan='prueba', periodicidad='mensual',
            monto=Decimal('4.00'), moneda='PEN', vence=date.today() + timedelta(days=30),
            estado='pendiente', pagook_pago_id=999999999, pagook_nivel='alta')
        s.referencia_externa = s.id
        db.add(s)
        try:
            db.flush()
            print("  ✅ INSERT OK → el esquema COINCIDE. El ya_procesado NO viene de aquí.")
        except IntegrityError as e:
            print("  ❌ IntegrityError en el INSERT (ESTA es la causa del ya_procesado):")
            print(f"     {getattr(e, 'orig', e)!r}")
        except Exception as e:
            print(f"  ❌ Otro error en el INSERT: {type(e).__name__}: {e}")
    finally:
        db.rollback()   # NUNCA commit: no se escribe nada
        db.close()
        print("\n  (rollback hecho — no se escribió NADA en la BD)")


if __name__ == '__main__':
    main()
