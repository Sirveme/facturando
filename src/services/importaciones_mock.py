"""
Datos MOCK del módulo Importadores (demo Glen Cask Wine & Spirits SAC).

NO es funcionalidad real: alimenta las plantillas del panel /importaciones con
una operación de importación completa y coherente (IMP-2026-001) y una segunda
en etapa temprana (IMP-2026-002). Todo en memoria; sin BD.

Una sola fuente de verdad para todas las vistas.
"""
from decimal import Decimal

# Etapas del flujo de importación (orden = progreso)
ETAPAS = [
    "OC", "Invoice", "Packing List", "BL/AWB", "Pre-DAM", "DAM", "Levante",
]

# Tipo de cambio usado para los tributos (demo)
TC = Decimal("3.750")


def _money(v) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01")))


def _calcular_tributos(cif_usd: Decimal) -> dict:
    """Tributos de importación de licores (demo, base CIF en PEN).
    Coherentes entre sí: cada uno se apila sobre el anterior."""
    cif_pen = (cif_usd * TC).quantize(Decimal("0.01"))

    ad_valorem_rate = Decimal("0.06")
    ad_valorem = (cif_pen * ad_valorem_rate).quantize(Decimal("0.01"))

    isc_base = cif_pen + ad_valorem
    isc_rate = Decimal("0.20")          # ISC licores
    isc = (isc_base * isc_rate).quantize(Decimal("0.01"))

    igv_base = cif_pen + ad_valorem + isc
    igv = (igv_base * Decimal("0.18")).quantize(Decimal("0.01"))   # IGV 16% + IPM 2%

    percep_base = cif_pen + ad_valorem + isc + igv
    percepcion = (percep_base * Decimal("0.035")).quantize(Decimal("0.01"))

    total = ad_valorem + isc + igv + percepcion
    return {
        "tc": float(TC),
        "cif_pen": _money(cif_pen),
        "ad_valorem_rate": "6%",
        "ad_valorem": _money(ad_valorem),
        "isc_rate": "20%",
        "isc": _money(isc),
        "igv_rate": "18%",
        "igv": _money(igv),
        "percepcion_rate": "3.5%",
        "percepcion": _money(percepcion),
        "total": _money(total),
    }


# ---------------------------------------------------------------------------
# OPERACIÓN COMPLETA — IMP-2026-001
# ---------------------------------------------------------------------------

_OC_ITEMS_001 = [
    {"codigo": "WSM-12", "descripcion": "Whisky Single Malt 12 años (caja x6 bot. 700ml)",
     "cajas": 120, "precio_caja": 280.00, "total": 33600.00},
    {"codigo": "VRT-RES", "descripcion": "Vino Reserva Tinto (caja x12 bot. 750ml)",
     "cajas": 80, "precio_caja": 142.50, "total": 11400.00},
]

_INV_ITEMS_001 = [
    {"codigo": "WSM-12", "descripcion": "Whisky Single Malt 12 años (caja x6 bot. 700ml)",
     "cajas_oc": 120, "cajas_inv": 118, "precio_caja": 280.00, "total": 33040.00,
     "discrepancia": -2},
    {"codigo": "VRT-RES", "descripcion": "Vino Reserva Tinto (caja x12 bot. 750ml)",
     "cajas_oc": 80, "cajas_inv": 80, "precio_caja": 142.50, "total": 11400.00,
     "discrepancia": 0},
]

_TRIBUTOS_001 = _calcular_tributos(Decimal("47940.00"))  # CIF del invoice

IMP_001 = {
    "codigo": "IMP-2026-001",
    "proveedor": "Highland Distillers Ltd",
    "proveedor_pais": "Escocia, Reino Unido",
    "incoterm": "CIF Callao",
    "moneda": "USD",
    "fob": 45000.00,
    "flete": 2800.00,
    "seguro": 700.00,
    "cif": 48500.00,
    "resumen_carga": "120 cajas whisky single malt + 80 cajas vino reserva",
    "fecha_eta": "2026-04-19",
    "etapa_actual": "Levante",
    "estado_label": "Levante autorizado",
    "estado_tono": "success",

    "orden_compra": {
        "numero": "OC-GC-2026-014",
        "fecha": "2026-03-02",
        "condicion_pago": "50% adelanto / 50% contra BL",
        "items": _OC_ITEMS_001,
        "fob": 45000.00, "flete": 2800.00, "seguro": 700.00, "cif": 48500.00,
    },

    "invoice": {
        "numero": "INV-HD-88231",
        "fecha": "2026-03-10",
        "items": _INV_ITEMS_001,
        "fob": 44440.00, "flete": 2800.00, "seguro": 700.00, "cif": 47940.00,
        "discrepancia_texto": "Discrepancia detectada: -2 cajas de whisky vs OC (118 facturadas / 120 pedidas, -USD 560.00)",
        "discrepancia_monto": -560.00,
    },

    "packing_list": {
        "numero": "PL-HD-88231",
        "fecha": "2026-03-11",
        "validacion": "OK contra Invoice (198 cajas / 198 facturadas)",
        "validacion_ok": True,
        "lineas": [
            {"descripcion": "Whisky Single Malt 12 años", "cajas": 118, "peso_neto": 2124.0, "peso_bruto": 2360.0},
            {"descripcion": "Vino Reserva Tinto", "cajas": 80, "peso_neto": 1600.0, "peso_bruto": 1760.0},
        ],
        "total_cajas": 198, "total_pallets": 12,
        "peso_neto_total": 3724.0, "peso_bruto_total": 4120.0,
    },

    "bl_awb": {
        "tipo": "BL (marítimo)",
        "numero": "MAEU-560123456",
        "naviera": "Maersk Line",
        "nave": "Maersk Cardiff — Voy. 612W",
        "puerto_origen": "Greenock, Reino Unido",
        "puerto_destino": "Callao, Perú",
        "etd": "2026-03-28",
        "eta": "2026-04-19",
        "contenedor": "1 x 40' HC — MRKU2748851",
    },

    "pre_dam": {
        "agente_aduana": "Aduanas del Pacífico S.A.C.",
        "fecha_entrega": "2026-04-18",
        "regimen": "10 - Importación para el consumo",
        "partidas": [
            {"partida": "2208.30.00.00", "descripcion": "Whisky", "cif_usd": 33040.00},
            {"partida": "2204.21.00.00", "descripcion": "Vino reserva", "cif_usd": 11400.00},
        ],
        "cif_total_usd": 47940.00,
    },

    "dam": {
        "numero": "118-2026-10-123456",
        "fecha": "2026-04-21",
        "canal": "Naranja",
        "canal_tono": "warning",
        "canal_desc": "Revisión documentaria",
        "tributos": _TRIBUTOS_001,
        "validacion_final": {
            "oc_cajas": 200, "invoice_cajas": 198, "dam_cajas": 198,
            "texto": "OC 200 cajas vs Invoice/DAM 198 cajas — discrepancia de -2 cajas de whisky arrastrada desde el Invoice.",
            "ok": False,
        },
    },

    "timeline": [
        {"hito": "OC emitida", "fecha": "2026-03-02", "doc": "OC-GC-2026-014", "estado": "completado"},
        {"hito": "Invoice recibido", "fecha": "2026-03-10", "doc": "INV-HD-88231", "estado": "alerta",
         "nota": "-2 cajas de whisky vs OC"},
        {"hito": "Packing List", "fecha": "2026-03-11", "doc": "PL-HD-88231", "estado": "completado"},
        {"hito": "BL / AWB", "fecha": "2026-03-28", "doc": "MAEU-560123456", "estado": "completado"},
        {"hito": "Data pre-DAM entregada al agente", "fecha": "2026-04-18", "doc": "Pre-DAM (TXT)", "estado": "completado"},
        {"hito": "DAM numerada", "fecha": "2026-04-21", "doc": "DAM 118-2026-10-123456", "estado": "completado"},
        {"hito": "Levante / Canal", "fecha": "2026-04-23", "doc": "Canal Naranja → Levante autorizado", "estado": "completado"},
    ],
}


# ---------------------------------------------------------------------------
# OPERACIÓN TEMPRANA — IMP-2026-002 (solo OC registrada)
# ---------------------------------------------------------------------------

IMP_002 = {
    "codigo": "IMP-2026-002",
    "proveedor": "Douro Valley Wines, Lda",
    "proveedor_pais": "Portugal",
    "incoterm": "FOB Leixões",
    "moneda": "USD",
    "fob": 9200.00,
    "flete": 0.0,
    "seguro": 0.0,
    "cif": 9900.00,
    "resumen_carga": "60 cajas vino Porto reserva",
    "fecha_eta": "2026-06-30",
    "etapa_actual": "OC",
    "estado_label": "OC registrada",
    "estado_tono": "info",

    "orden_compra": {
        "numero": "OC-GC-2026-021",
        "fecha": "2026-05-28",
        "condicion_pago": "100% contra Invoice",
        "items": [
            {"codigo": "PRT-RES", "descripcion": "Vino Porto Reserva (caja x6 bot. 750ml)",
             "cajas": 60, "precio_caja": 153.33, "total": 9200.00},
        ],
        "fob": 9200.00, "flete": 0.0, "seguro": 0.0, "cif": 9900.00,
    },

    "timeline": [
        {"hito": "OC emitida", "fecha": "2026-05-28", "doc": "OC-GC-2026-021", "estado": "completado"},
        {"hito": "Invoice recibido", "fecha": None, "doc": None, "estado": "pendiente"},
        {"hito": "Packing List", "fecha": None, "doc": None, "estado": "pendiente"},
        {"hito": "BL / AWB", "fecha": None, "doc": None, "estado": "pendiente"},
        {"hito": "Data pre-DAM entregada al agente", "fecha": None, "doc": None, "estado": "pendiente"},
        {"hito": "DAM numerada", "fecha": None, "doc": None, "estado": "pendiente"},
        {"hito": "Levante / Canal", "fecha": None, "doc": None, "estado": "pendiente"},
    ],
}


_OPERACIONES = {op["codigo"]: op for op in (IMP_001, IMP_002)}


def progreso(op: dict) -> dict:
    """Devuelve {indice, total, porcentaje} de la etapa actual de la operación."""
    try:
        idx = ETAPAS.index(op["etapa_actual"])
    except ValueError:
        idx = 0
    total = len(ETAPAS)
    return {"indice": idx + 1, "total": total,
            "porcentaje": round((idx + 1) / total * 100)}


def listar_operaciones() -> list:
    """Lista de operaciones para el listado (con progreso calculado)."""
    out = []
    for op in _OPERACIONES.values():
        o = dict(op)
        o["progreso"] = progreso(op)
        out.append(o)
    return out


def obtener_operacion(codigo: str):
    op = _OPERACIONES.get(codigo)
    if not op:
        return None
    o = dict(op)
    o["progreso"] = progreso(op)
    o["etapas"] = ETAPAS
    return o


# ---------------------------------------------------------------------------
# Exportación Pre-DAM (TXT / XML / JSON) generada del mock
# ---------------------------------------------------------------------------

def _pre_dam_dict(op: dict) -> dict:
    pd = op.get("pre_dam", {})
    return {
        "operacion": op["codigo"],
        "regimen": pd.get("regimen"),
        "agente_aduana": pd.get("agente_aduana"),
        "proveedor": op["proveedor"],
        "incoterm": op["incoterm"],
        "moneda": op["moneda"],
        "cif_total_usd": pd.get("cif_total_usd"),
        "partidas": pd.get("partidas", []),
        "bl": op.get("bl_awb", {}).get("numero"),
        "invoice": op.get("invoice", {}).get("numero"),
    }


def exportar_pre_dam(codigo: str, fmt: str):
    """Devuelve (contenido_str, media_type, filename) para descargar el Pre-DAM
    en TXT/XML/JSON, generado del mock. None si la operación no existe o no
    tiene datos pre-DAM."""
    op = _OPERACIONES.get(codigo)
    if not op or "pre_dam" not in op:
        return None
    data = _pre_dam_dict(op)
    fmt = (fmt or "").lower()

    if fmt == "json":
        import json
        return json.dumps(data, ensure_ascii=False, indent=2), "application/json", f"PRE-DAM_{codigo}.json"

    if fmt == "xml":
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<PreDAM>"]
        for k, v in data.items():
            if k == "partidas":
                lines.append("  <Partidas>")
                for p in v:
                    lines.append("    <Partida>")
                    for pk, pv in p.items():
                        lines.append(f"      <{pk}>{pv}</{pk}>")
                    lines.append("    </Partida>")
                lines.append("  </Partidas>")
            else:
                lines.append(f"  <{k}>{v}</{k}>")
        lines.append("</PreDAM>")
        return "\n".join(lines), "application/xml", f"PRE-DAM_{codigo}.xml"

    # TXT (pipe-delimited, estilo data de agente de aduana)
    rows = [
        f"OPERACION|{data['operacion']}",
        f"REGIMEN|{data['regimen']}",
        f"AGENTE|{data['agente_aduana']}",
        f"PROVEEDOR|{data['proveedor']}",
        f"INCOTERM|{data['incoterm']}",
        f"MONEDA|{data['moneda']}",
        f"CIF_TOTAL|{data['cif_total_usd']}",
        f"BL|{data['bl']}",
        f"INVOICE|{data['invoice']}",
    ]
    for p in data["partidas"]:
        rows.append(f"PARTIDA|{p['partida']}|{p['descripcion']}|{p['cif_usd']}")
    return "\n".join(rows), "text/plain", f"PRE-DAM_{codigo}.txt"
