#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
revisar_ui.py — Tablero /revisar (solo lectura del snapshot del vigilante).

Seguridad en dos capas:
  - Gesto secreto (5 taps sobre una letra) = comodidad para abrir la vista. Reusa el
    patrón de la página "En construcción".
  - El dato REAL lo entrega /revisar/data SOLO si el token (WATCHDOG_VIEW_TOKEN) coincide,
    así nadie con F12 lee el snapshot sin el token. El token viaja en la URL (?token=…),
    que solo tiene Duilio.

No login/clave. No toca emisión ni XML. Lee el snapshot que dejó el vigilante en Redis.
"""
import hmac

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.core.config import settings
from src.services.watchdog import leer_snapshot

router = APIRouter()


def _token_ok(token: str) -> bool:
    secret = settings.WATCHDOG_VIEW_TOKEN or ""
    if not secret or not token:
        return False
    return hmac.compare_digest(str(token), str(secret))


@router.get("/revisar/data", include_in_schema=False)
async def revisar_data(request: Request):
    token = request.query_params.get("token", "")
    if not _token_ok(token):
        return JSONResponse({"error": "token invalido o no configurado"}, status_code=403)
    snap = leer_snapshot()
    if not snap:
        return JSONResponse({"error": "sin_snapshot", "clientes": []}, status_code=200)
    return JSONResponse(snap)


@router.get("/revisar", include_in_schema=False, response_class=HTMLResponse)
async def revisar_page():
    return HTMLResponse(_PAGINA)


_PAGINA = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Mantenimiento</title>
<style>
  :root{ --bg:#0b0e14; --panel:#131824; --line:#232a3a; --txt:#e6e9f0; --mut:#8a93a6;
         --accent:#5E6AD2; --ok:#2ecc71; --warn:#e0a106; --bad:#e23c3c; }
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--txt);font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;
       display:flex;align-items:center;justify-content:center;padding:16px}
  .wrap{max-width:980px;width:100%}
  .maint{text-align:center;color:var(--mut);margin-top:22vh;user-select:none}
  .maint h1{color:var(--txt);font-weight:600;letter-spacing:.3px}
  .g{cursor:default;color:var(--mut)}
  #panel{display:none}
  .head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
  .head h2{margin:0;font-size:18px} .meta{color:var(--mut);font-size:13px}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px;white-space:nowrap}
  th{background:#0f1420;color:var(--mut);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.4px}
  td.cli{font-weight:600} tr:last-child td{border-bottom:none}
  .sub{color:var(--mut);font-size:12px}
  .pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;border:1px solid var(--line)}
  .err{color:var(--bad)} .warnp{color:var(--warn)}
  @media(max-width:640px){ th,td{padding:8px;font-size:12.5px} .maint{margin-top:30vh} }
</style></head><body>
<div class="wrap">
  <div id="maint" class="maint">
    <h1>Sitio en <span id="gesto" class="g">m</span>antenimiento</h1>
    <p>Volvemos pronto.</p>
  </div>
  <div id="panel">
    <div class="head">
      <h2>Vigilante · estado por cliente</h2>
      <span class="meta" id="meta">—</span>
    </div>
    <table><thead><tr>
      <th>Cliente</th><th>Último (ayer)</th><th>Primero (hoy)</th><th>Último (hoy)</th><th>Total hoy</th><th>Hora</th>
    </tr></thead><tbody id="rows"><tr><td colspan="6" class="sub">Cargando…</td></tr></tbody></table>
    <p class="sub" id="status" style="margin-top:10px"></p>
  </div>
</div>
<script>
(function(){
  var token = new URLSearchParams(location.search).get('token') || '';
  var taps = 0, timer = null;
  var gesto = document.getElementById('gesto');
  gesto.addEventListener('click', function(){
    taps++; clearTimeout(timer); timer = setTimeout(function(){ taps = 0; }, 1200);
    if (taps >= 5){ taps = 0; abrir(); }
  });
  function abrir(){
    document.getElementById('maint').style.display = 'none';
    document.getElementById('panel').style.display = 'block';
    cargar();
    setInterval(cargar, 60000);
  }
  function celda(c){ if(!c) return '<span class="sub">—</span>';
    return c.numero + '<br><span class="sub">'+c.estado+' · '+c.hora+'</span>'; }
  function cargar(){
    fetch('/revisar/data?token='+encodeURIComponent(token)).then(function(r){
      if(r.status===403){ throw new Error('token'); } return r.json();
    }).then(function(d){
      document.getElementById('meta').textContent = d.generado_en ? ('snapshot: '+d.generado_en+' ('+ (d.tz||'') +')') : '';
      var tb = document.getElementById('rows'); tb.innerHTML='';
      (d.clientes||[]).forEach(function(c){
        var tr = document.createElement('tr');
        if(c.falta_emisor){ tr.innerHTML = '<td class="cli">'+c.nombre+'</td><td colspan="5" class="err">emisor no encontrado</td>'; tb.appendChild(tr); return; }
        var total = (c.total_hoy===0) ? '<span class="warnp">0</span>' : c.total_hoy;
        tr.innerHTML = '<td class="cli">'+c.nombre+'<br><span class="sub">'+c.ruc+'</span></td>'+
          '<td>'+celda(c.ultimo_ayer)+'</td>'+'<td>'+celda(c.primero_hoy)+'</td>'+
          '<td>'+celda(c.ultimo_hoy)+'</td>'+'<td>'+total+'</td>'+
          '<td class="sub">'+(d.generado_en? d.generado_en.split(' ')[1] : '—')+'</td>';
        tb.appendChild(tr);
      });
      document.getElementById('status').textContent = 'Actualizado. Auto-refresh cada 60 s.';
    }).catch(function(e){
      document.getElementById('rows').innerHTML = '<tr><td colspan="6" class="err">'+
        (e.message==='token' ? 'Falta el token válido en la URL (?token=…).' : 'No se pudo cargar el snapshot.')+'</td></tr>';
    });
  }
})();
</script>
</body></html>"""
