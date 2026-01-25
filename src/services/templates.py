from datetime import datetime


def fecha_display_to_iso(fecha_display: str) -> str:
    """Convierte fecha de display dd/mm/YYYY a ISO YYYY-MM-DD"""
    if '/' in fecha_display:
        d, m, y = fecha_display.split('/')
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return fecha_display


def format_money(value) -> str:
    return f"{value:.2f}"
