#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_observaciones.py — READ-ONLY. Vuelca un comprobante (por serie+numero) para
diagnosticar el campo `observaciones`: texto COMPLETO + longitud real, estado y CDR
reales, y si el XML FIRMADO (el que se envió a SUNAT) contiene ese texto o no.

No escribe nada en la BD. No modifica archivos.

USO (en Railway, servicio Facturalo):
    python -m src.scripts.dump_observaciones B778 64
    python -m src.scripts.dump_observaciones B778 64 --ruc 20616219686   # si hay colisión de serie
"""
import re
import sys

from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ruc = None
    for a in sys.argv[1:]:
        if a.startswith("--ruc"):
            ruc = a.split("=", 1)[1].strip() if "=" in a else None
    # --ruc VALUE (separado)
    if "--ruc" in sys.argv:
        i = sys.argv.index("--ruc")
        if i + 1 < len(sys.argv):
            ruc = sys.argv[i + 1].strip()

    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    serie = args[0].strip().upper()
    try:
        numero = int(args[1])
    except ValueError:
        print("🛑 El número debe ser entero (ej. 64).")
        sys.exit(1)

    db = SessionLocal()
    try:
        q = db.query(Comprobante).filter(
            Comprobante.serie == serie, Comprobante.numero == numero)
        if ruc:
            emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
            if not emisor:
                print(f"🛑 No existe emisor con RUC {ruc}.")
                sys.exit(1)
            q = q.filter(Comprobante.emisor_id == emisor.id)
        comps = q.all()

        if not comps:
            print(f"\n🛑 No se encontró {serie}-{numero:08d}"
                  f"{(' para RUC '+ruc) if ruc else ''}.\n")
            sys.exit(1)
        if len(comps) > 1:
            print(f"⚠️  Hay {len(comps)} comprobantes {serie}-{numero:08d} (varios emisores). "
                  f"Se muestran todos; usa --ruc para acotar.\n")

        for comp in comps:
            emisor = db.query(Emisor).filter(Emisor.id == comp.emisor_id).first()
            obs = comp.observaciones or ""
            resp = comp.respuesta

            print("=" * 74)
            print(f"COMPROBANTE {comp.serie}-{comp.numero:08d}")
            print("=" * 74)
            print(f"  Emisor         : {emisor.ruc if emisor else '?'} — {emisor.razon_social if emisor else '?'}")
            print(f"  Tipo           : {comp.tipo_documento}")
            print(f"  Fecha emisión  : {comp.fecha_emision}")
            print(f"  Estado         : {comp.estado}")
            print(f"  hash_cpe       : {comp.hash_cpe or '(vacío)'}")
            if resp:
                print(f"  CDR código     : {resp.codigo_cdr}")
                print(f"  CDR descripción: {resp.descripcion}")
            else:
                print(f"  CDR            : (sin RespuestaSunat registrada)")

            print("\n  --- OBSERVACIONES (texto completo en BD) ---")
            print(f"  Longitud real  : {len(obs)} caracteres")
            print(f"  ¿El PDF lo corta? (dibuja solo obs_text[:90]): {'SÍ, se pierde texto' if len(obs) > 90 else 'no'}")
            print("  Texto completo :")
            print("  " + (obs if obs else "(vacío)"))
            if len(obs) > 90:
                print("\n  Lo que MUESTRA el PDF hoy (primeros 90):")
                print("  Obs: " + obs[:90])
                print("  Lo que se PIERDE en el PDF (91+):")
                print("  " + obs[90:])

            print("\n  --- XML FIRMADO (lo que se envió a SUNAT) ---")
            xml_bytes = comp.xml
            if not xml_bytes:
                print("  (No hay XML firmado guardado en la BD para este comprobante.)")
            else:
                xml_text = (xml_bytes.decode("utf-8", "replace")
                            if isinstance(xml_bytes, (bytes, bytearray)) else str(xml_bytes))
                print(f"  Tamaño XML     : {len(xml_text)} caracteres")
                # ¿Está el texto de observaciones dentro del XML?
                presente = bool(obs) and (obs.strip() in xml_text)
                print(f"  ¿`observaciones` está en el XML?: {'SÍ' if presente else 'NO'}")
                # Tokens distintivos del taller (por si el texto difiere por espacios)
                tokens = [t for t in ["Placa", "Vin", "VIN", "ODS", "Marca", "Chasis"] if t in xml_text]
                print(f"  Tokens de vehículo hallados en XML: {tokens or 'ninguno'}")
                # Mostrar las cbc:Note presentes (deberían ser solo leyendas cat.52)
                notes = re.findall(r"<cbc:Note[^>]*>(.*?)</cbc:Note>", xml_text, re.DOTALL)
                print(f"  cbc:Note en el XML ({len(notes)}):")
                for n in notes:
                    print("    • " + n.strip()[:120])
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
