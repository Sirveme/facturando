#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
receptor_validator.py — Valida que la razón social del receptor (cuando es RUC) coincida
con el padrón antes de enviar a SUNAT. SUNAT NO verifica que el nombre corresponda al RUC,
así que esto caza casos como "RUC de DIMEXA con nombre de otra persona" (F347-5).

APAGADO por defecto (settings.VALIDAR_RECEPTOR = False) → siempre 'pasa'.

Decisión (fail-open + estricto por emisor):
  - Validación apagada / receptor no-RUC                → 'pasa'
  - Nombre coincide (igual normalizado o similitud≥umbral) → 'pasa'
  - Nombre NO coincide (padrón respondió)               → 'rechazar'
  - Padrón sin respuesta / no encontrado:
        emisor en modo estricto                          → 'rechazar'
        resto (fail-open)                                → 'pasa_no_validado'
                                                           (emite + marca + alerta Telegram)

NO toca emisión ni XML: solo lee el padrón (vía ruc_lookup.consultar_ruc, no-fatal) y
devuelve una decisión. El que llama decide bloquear/marcar/alertar.
"""
import logging
import re
import unicodedata
from difflib import SequenceMatcher

from src.core.config import settings

logger = logging.getLogger(__name__)

# Sufijos societarios que no aportan a la comparación (se quitan como tokens).
_SUFIJOS = {
    'SA', 'SAC', 'SAA', 'SRL', 'EIRL', 'SCRL', 'SCS', 'SENC',
    'SOCIEDAD', 'ANONIMA', 'CERRADA', 'COMERCIAL', 'INDIVIDUAL',
    'RESPONSABILIDAD', 'LIMITADA', 'EMPRESA', 'EIRLTDA', 'LTDA', 'E', 'I', 'R', 'L',
}


def _normalizar(nombre: str) -> str:
    """MAYÚSCULAS, sin acentos, sin puntuación, sin sufijos societarios, espacios colapsados."""
    s = (nombre or '').upper().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')         # quita tildes
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)                       # quita puntuación
    toks = [t for t in s.split() if t and t not in _SUFIJOS]
    return ' '.join(toks).strip()


def _similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _emisor_estricto(emisor_ruc) -> bool:
    raw = getattr(settings, 'VALIDAR_RECEPTOR_ESTRICTO', '') or ''
    rucs = {r.strip() for r in raw.split(',') if r.strip()}
    return bool(emisor_ruc) and str(emisor_ruc).strip() in rucs


def validar_receptor(ruc, razon_social_enviada, emisor_ruc=None) -> dict:
    """Devuelve dict con: ok(bool, False solo si hay que BLOQUEAR), accion, motivo,
    razon_social_oficial, razon_social_enviada, similitud, estricto."""
    base = {"ok": True, "accion": "pasa", "motivo": "", "razon_social_oficial": "",
            "razon_social_enviada": razon_social_enviada or "", "similitud": None,
            "estricto": _emisor_estricto(emisor_ruc)}

    if not getattr(settings, 'VALIDAR_RECEPTOR', False):
        base["motivo"] = "validacion_desactivada"
        return base

    ruc = (ruc or '').strip()
    if len(ruc) != 11 or not ruc.isdigit():
        base["motivo"] = "receptor_no_ruc"      # solo validamos receptores RUC
        return base

    # Consulta del padrón (no-fatal). PSP primero, apis.net.pe de respaldo.
    info = None
    try:
        from src.services.padron_lookup import consultar_ruc_padron
        info = consultar_ruc_padron(ruc)
    except Exception as e:
        logger.warning("[RECEPTOR] consulta padrón falló para %s: %s", ruc, e)

    if not info or not info.get("encontrado") or not (info.get("razon_social") or "").strip():
        # Padrón sin respuesta / RUC no hallado → fail-open salvo estricto.
        if base["estricto"]:
            return {**base, "ok": False, "accion": "rechazar", "motivo": "padron_sin_respuesta_estricto"}
        return {**base, "accion": "pasa_no_validado", "motivo": "padron_sin_respuesta"}

    oficial = (info.get("razon_social") or "").strip()
    env_n, ofi_n = _normalizar(razon_social_enviada), _normalizar(oficial)
    base["razon_social_oficial"] = oficial

    if not env_n:
        # No mandaron nombre que comparar → trátalo como no validado (no bloquea salvo estricto).
        if base["estricto"]:
            return {**base, "ok": False, "accion": "rechazar", "motivo": "sin_nombre_estricto"}
        return {**base, "accion": "pasa_no_validado", "motivo": "sin_nombre_enviado"}

    sim = _similitud(env_n, ofi_n)
    base["similitud"] = round(sim, 3)
    umbral = (getattr(settings, 'VALIDAR_RECEPTOR_UMBRAL', 90) or 90) / 100.0

    if env_n == ofi_n or sim >= umbral:
        return {**base, "accion": "pasa", "motivo": "coincide"}

    # Padrón respondió y el nombre NO coincide → rechazo (en ambos modos).
    return {**base, "ok": False, "accion": "rechazar", "motivo": "no_coincide"}


def mensaje_rechazo(res: dict) -> dict:
    """Payload de error claro para el sistema que emite (p.ej. 422)."""
    return {
        "error": "RECEPTOR_NO_COINCIDE",
        "detalle": "La razón social enviada no corresponde al RUC en el padrón.",
        "razon_social_enviada": res.get("razon_social_enviada"),
        "razon_social_oficial": res.get("razon_social_oficial"),
        "similitud": res.get("similitud"),
    }


def alertar_no_validado(res: dict, serie_numero: str = "", emisor_ruc: str = "", receptor_ruc: str = ""):
    """Alerta Telegram no-fatal cuando un comprobante sale como 'receptor no validado'
    (fail-open: el padrón no respondió y se emitió igual)."""
    try:
        from src.services.telegram_notify import enviar_telegram
        enviar_telegram(
            f"⚠️ Receptor NO validado (fail-open): {serie_numero or '(s/n)'} · "
            f"emisor {emisor_ruc or '?'} · receptor RUC {receptor_ruc or '?'} "
            f"'{res.get('razon_social_enviada') or ''}'. Motivo: {res.get('motivo')}. "
            f"Se emitió igual; revisar padrón."
        )
    except Exception as e:
        logger.warning("[RECEPTOR] no se pudo alertar Telegram: %s", e)
