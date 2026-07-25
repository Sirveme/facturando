#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nc_lote_bingazo.py — FASE 3: emitir las 11 NC restantes del caso Bingazo (18/07/2026).

Anula las boletas B400 duplicadas con Notas de Crédito serie BC40, motivo '01'
(catálogo 09, Anulación de la operación), replicando cliente/montos/líneas de cada boleta.
Reutiliza EXACTAMENTE el flujo ya aceptado por SUNAT (build_invoice_xml tipo 07 → firmar →
enviar) y el fix del hash (DigestValue del XML firmado → comprobante.hash_cpe).

GUARDAS (no configurables):
- De a UNA, secuencial. Nunca en paralelo (la concurrencia causó la duplicación original).
- Por boleta antes de emitir: existe, está 'aceptado', el DNI coincide con el esperado, y
  NO tiene NC previa. Si ya tiene NC → se SALTA y se reporta (idempotencia).
- STOP-AL-PRIMER-FALLO: si una NC sale rechazada/observada (ResponseCode != '0') o hay
  fallo técnico, se DETIENE todo el lote, se reporta el código exacto de SUNAT y la boleta
  donde paró, y se espera decisión humana. NO se continúa con las siguientes. NO se reintenta.
- Las boletas 1691 y 1692 (válidas) están FUERA de toda operación (guarda estructural).

Ejecutar EN RAILWAY:
  Dry-run (valida las 11, no envía nada):   python -m src.scripts.nc_lote_bingazo
  Envío real (de a una, stop al fallo):     python -m src.scripts.nc_lote_bingazo --send
  Verificación FASE 4 (solo lectura):       python -m src.scripts.nc_lote_bingazo --verificar
"""

import sys
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, RespuestaSunat, LineaDetalle
from src.services.xml_generator import build_invoice_xml
from src.services.firma_digital import firmar_xml
from src.services.sunat_client import enviar_comprobante

# Reutilizar el flujo corregido y probado del script de prueba
from src.scripts.nc_prueba_bingazo import (
    _extraer_hash_cpe,
    _build_comprobante_xml_obj,
    _build_emisor_dict,
    _desencriptar_sol_password,
    cargar_cert,
    PERU_TZ,
    BOLETA_SERIE,
    BOLETA_TIPO,
    NC_SERIE,
    NC_TIPO,
    MOTIVO_NC,
)

# =====================================================================
# LOTE — orden de emisión (numero de boleta B400, DNI esperado)
# =====================================================================
PINEDO = '45817384'
OLORTEGUI = '05325999'

LOTE = [
    (1681, PINEDO), (1683, PINEDO), (1684, PINEDO),
    (1686, PINEDO), (1688, PINEDO), (1689, PINEDO),
    (1679, OLORTEGUI), (1682, OLORTEGUI), (1685, OLORTEGUI),
    (1687, OLORTEGUI), (1690, OLORTEGUI),
]

# Boletas VÁLIDAS que jamás deben tocarse (guarda estructural)
VALIDAS_INTOCABLES = {1691, 1692}

# Para verificación FASE 4: las 12 duplicadas (incluye 1680 = BC40-46 ya emitida)
TODAS_ANULADAS = [1680] + [n for n, _ in LOTE]

# --- Guarda estructural dura: 1691/1692 no pueden estar en ninguna lista operativa ---
_lote_nums = {n for n, _ in LOTE}
assert VALIDAS_INTOCABLES.isdisjoint(_lote_nums), "GUARDA: 1691/1692 no deben estar en el lote"
assert VALIDAS_INTOCABLES.isdisjoint(set(TODAS_ANULADAS)), "GUARDA: 1691/1692 fuera de anuladas"
assert len(LOTE) == 11, "El lote debe tener exactamente 11 boletas"


# ---------------------------------------------------------------------
def _cargar_boleta(db, numero):
    return (
        db.query(Comprobante)
        .filter(
            Comprobante.serie == BOLETA_SERIE,
            Comprobante.numero == numero,
            Comprobante.tipo_documento == BOLETA_TIPO,
        )
        .first()
    )


def _nc_previa(db, boleta):
    return (
        db.query(Comprobante)
        .filter(
            Comprobante.emisor_id == boleta.emisor_id,
            Comprobante.tipo_documento == NC_TIPO,
            Comprobante.doc_referencia_numero == boleta.numero_formato,
        )
        .first()
    )


def _validar_boleta(db, numero, dni_esperado):
    """Valida una boleta. Devuelve (boleta, motivo_skip|None) o lanza ValueError si estado inválido."""
    if numero in VALIDAS_INTOCABLES:
        raise ValueError(f"{numero} es una boleta VÁLIDA intocable; no puede procesarse.")
    boleta = _cargar_boleta(db, numero)
    if not boleta:
        raise ValueError(f"Boleta {BOLETA_SERIE}-{numero} no encontrada.")
    if (boleta.cliente_numero_documento or '') != dni_esperado:
        raise ValueError(
            f"{boleta.numero_formato}: DNI {boleta.cliente_numero_documento} != esperado {dni_esperado}."
        )
    if boleta.estado != 'aceptado':
        raise ValueError(f"{boleta.numero_formato}: estado '{boleta.estado}' (se requiere 'aceptado').")
    if not boleta.numero_formato or not boleta.lineas:
        raise ValueError(f"{boleta.numero_formato}: sin numero_formato o sin líneas.")
    prev = _nc_previa(db, boleta)
    if prev:
        return boleta, f"ya tiene NC {prev.numero_formato} (estado={prev.estado})"
    return boleta, None


def _construir_nc(db, boleta, emisor, extra=0):
    """Construye (sin persistir) la NC BC40 y sus líneas replicando la boleta. Devuelve (nc, lineas).

    `extra` desplaza el correlativo para simular numeración secuencial en dry-run (donde nada
    se commitea y max(numero) no avanza). En --send siempre es 0: el max real avanza por commit.
    """
    max_numero = (
        db.query(func.max(Comprobante.numero))
        .filter(
            Comprobante.emisor_id == emisor.id,
            Comprobante.serie == NC_SERIE,
            Comprobante.tipo_documento == NC_TIPO,
        )
        .scalar()
    )
    siguiente = ((max_numero + 1) if max_numero else 1) + extra
    numero_formato = f"{NC_SERIE}-{str(siguiente).zfill(8)}"
    nc = Comprobante(
        id=str(uuid4()),
        emisor_id=emisor.id,
        tipo_documento=NC_TIPO,
        serie=NC_SERIE,
        numero=siguiente,
        numero_formato=numero_formato,
        fecha_emision=datetime.now(PERU_TZ).date(),
        moneda=boleta.moneda or 'PEN',
        cliente_tipo_documento=boleta.cliente_tipo_documento,
        cliente_numero_documento=boleta.cliente_numero_documento,
        cliente_razon_social=boleta.cliente_razon_social,
        cliente_direccion=boleta.cliente_direccion,
        monto_base=boleta.monto_base,
        monto_igv=boleta.monto_igv,
        monto_total=boleta.monto_total,
        op_gravada=boleta.op_gravada,
        estado='pendiente',
        observaciones=f"Anulación por duplicidad (Bingazo 18/07/2026). Ref {boleta.numero_formato}.",
        doc_referencia_tipo=boleta.tipo_documento,
        doc_referencia_numero=boleta.numero_formato,
        motivo_nota=MOTIVO_NC,
    )
    lineas = []
    for ln in sorted(boleta.lineas, key=lambda x: x.orden or 0):
        lineas.append(LineaDetalle(
            id=str(uuid4()), comprobante_id=nc.id, orden=ln.orden,
            descripcion=ln.descripcion, cantidad=ln.cantidad, unidad=ln.unidad or 'NIU',
            precio_unitario=ln.precio_unitario, monto_linea=ln.monto_linea,
            tipo_afectacion_igv=getattr(ln, 'tipo_afectacion_igv', '10') or '10',
            es_bonificacion=False,
        ))
    nc.lineas = lineas
    return nc, lineas


# =====================================================================
# MODO --verificar (FASE 4, solo lectura)
# =====================================================================
def verificar(db):
    print("=" * 72)
    print("VERIFICACIÓN FASE 4 (solo lectura)")
    print("=" * 72)

    print("\n[A] Las 12 boletas duplicadas → su NC BC40 (por referencia con formato completo):")
    faltantes, sin_hash, no_aceptadas = [], [], []
    for numero in sorted(TODAS_ANULADAS):
        boleta = _cargar_boleta(db, numero)
        if not boleta:
            print(f"  B400-{numero}: ❌ boleta no encontrada")
            faltantes.append(numero)
            continue
        ref = boleta.numero_formato  # p.ej. 'B400-00001680'
        nc = (
            db.query(Comprobante)
            .filter(
                Comprobante.serie == NC_SERIE,
                Comprobante.tipo_documento == NC_TIPO,
                Comprobante.doc_referencia_numero == ref,
            )
            .first()
        )
        if not nc:
            print(f"  {ref}: ❌ SIN NC")
            faltantes.append(numero)
            continue
        estado_ok = nc.estado == 'aceptado'
        hash_ok = bool(nc.hash_cpe)
        marca = "OK" if (estado_ok and hash_ok) else "⚠️"
        print(f"  {ref} → {nc.numero_formato}  estado={nc.estado}  "
              f"hash_cpe={nc.hash_cpe or '(NULL)'}  [{marca}]")
        if not estado_ok:
            no_aceptadas.append(nc.numero_formato)
        if not hash_ok:
            sin_hash.append(nc.numero_formato)

    print("\n[B] Boletas VÁLIDAS 1691/1692 (deben seguir 'aceptado' y SIN NC):")
    for numero in sorted(VALIDAS_INTOCABLES):
        boleta = _cargar_boleta(db, numero)
        if not boleta:
            print(f"  B400-{numero}: ❌ no encontrada")
            continue
        nc = (
            db.query(Comprobante)
            .filter(
                Comprobante.serie == NC_SERIE,
                Comprobante.tipo_documento == NC_TIPO,
                Comprobante.doc_referencia_numero == boleta.numero_formato,
            )
            .first()
        )
        estado = boleta.estado
        tiene_nc = "❌ TIENE NC!" if nc else "sin NC ✅"
        marca = "OK" if (estado == 'aceptado' and not nc) else "⚠️"
        print(f"  {boleta.numero_formato}: estado={estado}  {tiene_nc}  [{marca}]")

    print("\n" + "-" * 72)
    total_ok = len(TODAS_ANULADAS) - len(faltantes) - len(no_aceptadas) - len(sin_hash)
    if not faltantes and not sin_hash and not no_aceptadas:
        print("✅ Las 12 duplicadas tienen NC 'aceptado' con hash_cpe. Boletas válidas intactas.")
    else:
        if faltantes:
            print(f"⚠️ Sin NC: {faltantes}")
        if no_aceptadas:
            print(f"⚠️ NC no 'aceptado': {no_aceptadas}")
        if sin_hash:
            print(f"⚠️ NC sin hash_cpe: {sin_hash}")
    print("-" * 72)


# =====================================================================
# MODOS dry-run / --send
# =====================================================================
def procesar(db, send_mode):
    print("=" * 72)
    print(f"LOTE BINGAZO — {len(LOTE)} NC restantes  (serie {NC_SERIE}, motivo {MOTIVO_NC})")
    print("MODO:", "🚨 ENVÍO REAL A SUNAT (de a una, stop al primer fallo)"
          if send_mode else "🧪 DRY-RUN (valida y firma; sin BD, sin SUNAT)")
    print("=" * 72)

    # Emisor + certificado: se cargan una vez desde la primera boleta válida.
    emisor = None
    pfx_bytes = password = None
    emitidas, saltadas = [], []
    dry_built = 0  # simula el avance del correlativo en dry-run

    for idx, (numero, dni) in enumerate(LOTE, 1):
        print(f"\n[{idx}/{len(LOTE)}] Boleta B400-{numero} (DNI {dni})")
        try:
            boleta, motivo_skip = _validar_boleta(db, numero, dni)
        except ValueError as e:
            # Estado inesperado de una boleta que debía anularse → DETENER (no saltar en silencio).
            print(f"   🛑 VALIDACIÓN FALLIDA: {e}")
            print(f"   Se detiene el lote en B400-{numero}. Reportar a Duilio.")
            _resumen(emitidas, saltadas, parada=numero)
            sys.exit(1)

        if motivo_skip:
            print(f"   ⏭️  SALTADA (idempotencia): {motivo_skip}")
            saltadas.append((numero, motivo_skip))
            continue

        # Cargar emisor/cert la primera vez que hace falta
        if emisor is None:
            emisor = db.query(Emisor).filter(Emisor.id == boleta.emisor_id).first()
            if not emisor:
                print("   🛑 Emisor no encontrado. Se detiene."); sys.exit(1)
            pfx_bytes, password = cargar_cert(db, emisor)
            print(f"   emisor {emisor.ruc} produccion={getattr(emisor, 'produccion', False)} cert OK.")
        elif boleta.emisor_id != emisor.id:
            print(f"   🛑 B400-{numero} pertenece a otro emisor. Se detiene."); sys.exit(1)

        # Construir + firmar + hash
        nc, lineas = _construir_nc(db, boleta, emisor, extra=(dry_built if not send_mode else 0))
        comp_xml = _build_comprobante_xml_obj(nc)
        signed_xml = firmar_xml(build_invoice_xml(comp_xml, _build_emisor_dict(emisor)),
                                pfx_bytes, password)
        nc.hash_cpe = _extraer_hash_cpe(signed_xml)
        if not nc.hash_cpe:
            print(f"   🛑 No se pudo extraer hash_cpe para NC de B400-{numero}. Se detiene.")
            _resumen(emitidas, saltadas, parada=numero)
            sys.exit(1)

        print(f"   NC {nc.numero_formato}  ref={nc.doc_referencia_numero}  hash={nc.hash_cpe}  "
              f"total={nc.monto_total}")

        if not send_mode:
            db.rollback()  # descartar cualquier objeto transitorio; nada se persiste en dry-run
            dry_built += 1
            continue

        # --- ENVÍO REAL ---
        nc.xml = signed_xml
        db.add(nc)
        for ln in lineas:
            db.add(ln)
        nc.estado = 'enviando'
        db.commit()

        try:
            cdr = enviar_comprobante(
                signed_xml, emisor.ruc,
                sol_usuario=emisor.sol_usuario,
                sol_password=_desencriptar_sol_password(emisor),
                use_production=getattr(emisor, 'produccion', False),
            )
        except Exception as e:
            nc.estado = 'error'
            db.commit()
            print(f"   ❌ FALLO TÉCNICO (sin CDR) en NC de B400-{numero}: {e}")
            print("   🛑 Se detiene el lote. NO se reintenta.")
            _resumen(emitidas, saltadas, parada=numero)
            sys.exit(2)

        codigo = str(cdr.get('codigo') or '')
        descripcion = cdr.get('descripcion') or ''
        db.add(RespuestaSunat(comprobante_id=nc.id, codigo_cdr=codigo,
                              descripcion=descripcion, cdr_xml=cdr.get('cdr_xml')))
        if codigo == '0':
            nc.estado = 'aceptado'
        elif codigo.startswith('2'):
            nc.estado = 'aceptado_con_observaciones'
        else:
            nc.estado = 'rechazado'
        db.commit()

        if codigo == '0':
            print(f"   ✅ ACEPTADA {nc.numero_formato}  (código 0)")
            emitidas.append((numero, nc.numero_formato))
        else:
            # Observada o rechazada → DETENER el lote (regla del prompt).
            print(f"   ❌ NO ACEPTADA {nc.numero_formato}  ResponseCode={codigo!r}: {descripcion}")
            print(f"   🛑 Se detiene el lote en B400-{numero}. Reportar código y mensaje a Duilio.")
            _resumen(emitidas, saltadas, parada=numero)
            sys.exit(3)

    # Fin sin paradas
    if not send_mode:
        print("\n🧪 DRY-RUN completado: las 11 se validaron y firmaron OK. Nada en BD ni SUNAT.")
        print("   Envío real:  python -m src.scripts.nc_lote_bingazo --send")
    _resumen(emitidas, saltadas, parada=None)


def _resumen(emitidas, saltadas, parada):
    print("\n" + "=" * 72)
    print("RESUMEN DEL LOTE")
    print(f"  Emitidas y aceptadas: {len(emitidas)}")
    for numero, ncf in emitidas:
        print(f"     B400-{numero} → {ncf}")
    if saltadas:
        print(f"  Saltadas (ya tenían NC): {len(saltadas)}")
        for numero, motivo in saltadas:
            print(f"     B400-{numero}: {motivo}")
    if parada is not None:
        print(f"  ⛔ DETENIDO en: B400-{parada}")
        print("     Ejecutar --verificar y reportar a Duilio antes de cualquier reintento (decisión humana).")
    else:
        print("  ✔️ Sin paradas.")
    print("=" * 72)


def main():
    args = sys.argv[1:]
    db = SessionLocal()
    try:
        if '--verificar' in args:
            verificar(db)
        else:
            procesar(db, send_mode=('--send' in args))
    finally:
        db.close()


if __name__ == '__main__':
    main()
