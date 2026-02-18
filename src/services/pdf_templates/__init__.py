"""
Sistema de Templates PDF por Nicho - facturalo.pro

Cada emisor puede tener un "nicho" en su config_json.
Si existe un template para ese nicho, se usa. Si no, se usa el default.

Ejemplo config_json del emisor:
    {"nicho": "bodega", ...}
"""

SLOGANS = {
    "bodega": "El favorito de los bodegueros",
    "farmacia": "Exclusivo para farmacias",
    "ferreteria": "El preferido de las ferreterías",
    "libreria": "Exclusivo para librerías",
    "restaurante": "El más confiable para restaurantes",
    "ccploreto": "Confiado por instituciones",
    "default": "Más de 80 empresas ya usan facturalo.pro",
}


def get_emisor_nicho(emisor):
    """Obtiene el nicho del emisor desde config_json"""
    config = getattr(emisor, 'config_json', None)
    if config and isinstance(config, dict):
        return config.get('nicho', 'default')
    return 'default'


def get_slogan(nicho):
    """Retorna el slogan para el nicho dado"""
    return SLOGANS.get(nicho, SLOGANS["default"])


def get_template_generator(nicho):
    """
    Retorna la función generadora de PDF para el nicho dado.
    Retorna None si no existe template específico (usa el default).
    """
    if nicho == "bodega":
        from src.services.pdf_templates.bodega import generar_pdf_bodega
        return generar_pdf_bodega
    # Futuros nichos:
    # elif nicho == "farmacia":
    #     from src.services.pdf_templates.farmacia import generar_pdf_farmacia
    #     return generar_pdf_farmacia
    return None
