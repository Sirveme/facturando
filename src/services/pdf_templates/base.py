"""
Base compartida para templates PDF - facturalo.pro

Re-exporta constantes, colores y utilidades del generador principal.
Los templates de nicho importan desde aquí lo que necesitan,
evitando duplicar definiciones.
"""

from src.api.v1.pdf_generator import (
    # Diccionarios de tipos
    TIPOS_DOCUMENTO,
    TIPOS_DOC_CORTO,
    TIPOS_DOC_IDENTIDAD,

    # Colores
    COLOR_PRIMARIO,
    COLOR_SECUNDARIO,
    COLOR_GRIS,
    COLOR_GRIS_TEXTO,
    COLOR_GRIS_FONDO,
    COLOR_GRIS_OSCURO,
    COLOR_LINEA,
    COLOR_BORDE,
    COLOR_VERDE,
    COLOR_ROJO,
    COLOR_HABIL,

    # Configuración
    PERU_TZ,
    FACTURALO_URL,

    # Utilidades de dibujo
    _rounded_rect,
    _safe_float,
    numero_a_letras,

    # Generador de ticket (compartido)
    _generar_ticket,
)

__all__ = [
    'TIPOS_DOCUMENTO', 'TIPOS_DOC_CORTO', 'TIPOS_DOC_IDENTIDAD',
    'COLOR_PRIMARIO', 'COLOR_SECUNDARIO', 'COLOR_GRIS', 'COLOR_GRIS_TEXTO',
    'COLOR_GRIS_FONDO', 'COLOR_GRIS_OSCURO', 'COLOR_LINEA', 'COLOR_BORDE',
    'COLOR_VERDE', 'COLOR_ROJO', 'COLOR_HABIL',
    'PERU_TZ', 'FACTURALO_URL',
    '_rounded_rect', '_safe_float', 'numero_a_letras',
    '_generar_ticket',
]
