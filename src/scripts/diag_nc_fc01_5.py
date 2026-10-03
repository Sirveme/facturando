#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_nc_fc01_5.py — SOLO LECTURA.

Confirma con qué MOTIVO (catálogo 09) y con qué IMPORTES se guardó la NC FC01-5
de Maykol (RUC 10736459791), y a qué comprobante referencia. No escribe nada.

Ejecutar EN RAILWAY:
    python -m src.scripts.diag_nc_fc01_5
"""
from src.api.dependencies import SessionLocal
from src.models.models import Emisor, Comprobante, LineaDetalle

RUC = '10736459791'
SERIE = 'FC01'
NUMERO = 5

MOTIVOS09 = {
    '01': 'Anulación de la operación', '02': 'Anulación por error en el RUC',
    '03': 'Corrección por error en la descripción', '04': 'Descuento global',
    '05': 'Descuento por ítem', '06': 'Devolución total', '07': 'Devolución por ítem',
}


def main():
    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == RUC).first()
        nc = db.query(Comprobante).filter(
            Comprobante.emisor_id == (emisor.id if emisor else None),
            Comprobante.serie == SERIE, Comprobante.numero == NUMERO,
            Comprobante.tipo_documento == '07').first()
        if not nc:
            print(f"(no se encontró NC {SERIE}-{NUMERO})")
            return

        print("=" * 84)
        print(f"NC {nc.serie}-{nc.numero} ({nc.numero_formato})  id={nc.id}")
        print(f"  estado           : {nc.estado}")
        print(f"  motivo_nota      : {nc.motivo_nota}  → '{MOTIVOS09.get(nc.motivo_nota, '?')}'")
        print(f"  referencia       : {nc.doc_referencia_tipo} {nc.doc_referencia_numero}")
        print(f"  IMPORTES NC      : base={nc.monto_base}  IGV={nc.monto_igv}  TOTAL={nc.monto_total}")
        print(f"  observaciones    : {nc.observaciones}")
        print("-" * 84)
        print("  LÍNEAS:")
        for l in (db.query(LineaDetalle).filter(LineaDetalle.comprobante_id == nc.id)
                  .order_by(LineaDetalle.orden).all()):
            print(f"   #{l.orden} '{l.descripcion}' cant={l.cantidad} x {l.precio_unitario} "
                  f"= monto_linea {l.monto_linea} (afect {l.tipo_afectacion_igv})")
        print("=" * 84)
        if nc.motivo_nota == '03' and (nc.monto_total or 0) != 0:
            print("⚠️ NC motivo 03 (corrección de descripción) emitida CON importes completos")
            print("   → SUNAT/SIRE la interpreta como crédito total → la factura referida queda en CERO.")
            print("   Esperado para 03 (solo texto): NO debe restar importe a la operación.")
        print("=" * 84)
    finally:
        db.close()


if __name__ == '__main__':
    main()
