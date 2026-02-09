"""
Router: Verificación pública de comprobantes
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from urllib.parse import urlencode

from src.api.dependencies import get_db

router = APIRouter(prefix="/verificar", tags=["verificacion"])


@router.get("/{hash_o_id}", response_class=HTMLResponse)
async def verificar_comprobante(
    hash_o_id: str,
    db: Session = Depends(get_db)
):
    """Página pública de verificación de comprobante electrónico."""
    
    comprobante = db.execute(
        text("""
            SELECT 
                c.*,
                e.ruc as emisor_ruc,
                e.razon_social as emisor_nombre
            FROM comprobantes c
            JOIN empresas e ON c.empresa_id = e.id
            WHERE c.hash_cpe = :hash 
               OR c.id::text = :hash
               OR c.external_id::text = :hash
            LIMIT 1
        """),
        {"hash": hash_o_id}
    ).fetchone()
    
    if not comprobante:
        return HTMLResponse(_pagina_no_encontrado(), status_code=404)
    
    sunat_url = _construir_url_sunat(comprobante)
    return HTMLResponse(_pagina_verificacion(comprobante, sunat_url))


def _construir_url_sunat(comp) -> str:
    """Construye URL de verificación en SUNAT."""
    fecha = comp.fecha_emision.strftime("%d/%m/%Y") if comp.fecha_emision else ""
    
    params = {
        "ruc": comp.emisor_ruc,
        "tipo": comp.tipo,
        "serie": comp.serie,
        "numero": str(comp.numero),
        "fechaEmision": fecha,
        "monto": f"{float(comp.total):.2f}"
    }
    
    base = "https://www.sunat.gob.pe/ol-ti-itconsultaunificadalibre/consultaUnificadaLibre/consulta"
    return f"{base}?{urlencode(params)}"


def _pagina_verificacion(comp, sunat_url: str) -> str:
    """HTML de verificación."""
    tipo_nombre = "FACTURA" if comp.tipo == "01" else "BOLETA"
    es_valido = comp.estado in ("accepted", "enviado")
    estado_class = "valid" if es_valido else "invalid"
    estado_texto = "✅ COMPROBANTE VÁLIDO" if es_valido else "❌ COMPROBANTE NO VÁLIDO"
    
    fecha_str = comp.fecha_emision.strftime("%d/%m/%Y %H:%M") if comp.fecha_emision else "-"
    
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verificación - facturalo.pro</title>
    <link rel="icon" href="/static/favicon.ico">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            padding: 20px;
            color: #e2e8f0;
        }}
        .container {{ max-width: 550px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 25px; }}
        .header img {{ height: 40px; margin-bottom: 15px; }}
        .header h1 {{ font-size: 20px; color: #f8fafc; margin-bottom: 5px; }}
        .header p {{ color: #64748b; font-size: 13px; }}
        .card {{
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 25px;
            border: 1px solid rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
        }}
        .status {{
            text-align: center;
            padding: 14px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-weight: 700;
            font-size: 16px;
        }}
        .status.valid {{
            background: rgba(34, 197, 94, 0.12);
            color: #22c55e;
            border: 1px solid rgba(34, 197, 94, 0.25);
        }}
        .status.invalid {{
            background: rgba(239, 68, 68, 0.12);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.25);
        }}
        .info-grid {{ display: grid; gap: 2px; }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }}
        .info-row:last-child {{ border-bottom: none; }}
        .info-label {{ color: #64748b; font-size: 12px; }}
        .info-value {{ color: #f1f5f9; font-weight: 600; font-size: 13px; text-align: right; max-width: 60%; }}
        .info-value.hash {{ font-family: monospace; font-size: 10px; word-break: break-all; }}
        .buttons {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 20px;
        }}
        .btn {{
            padding: 12px 16px;
            border-radius: 10px;
            text-decoration: none;
            text-align: center;
            font-weight: 600;
            font-size: 12px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #3b82f6, #2563eb);
            color: white;
        }}
        .btn-outline {{
            background: transparent;
            color: #94a3b8;
            border: 1px solid rgba(255,255,255,0.15);
        }}
        .btn-sunat {{
            grid-column: 1 / -1;
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            color: white;
            margin-top: 5px;
        }}
        .btn:hover {{ transform: translateY(-1px); opacity: 0.9; }}
        .footer {{
            text-align: center;
            margin-top: 20px;
            color: #475569;
            font-size: 11px;
        }}
        .footer a {{ color: #3b82f6; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="/static/img/logo-facturalo-white.png" alt="facturalo.pro" onerror="this.style.display='none'">
            <h1>🔐 Verificación de Comprobante</h1>
            <p>Documento electrónico validado por SUNAT</p>
        </div>
        
        <div class="card">
            <div class="status {estado_class}">{estado_texto}</div>
            
            <div class="info-grid">
                <div class="info-row">
                    <span class="info-label">Tipo</span>
                    <span class="info-value">{tipo_nombre} ELECTRÓNICA</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Serie - Número</span>
                    <span class="info-value">{comp.serie}-{comp.numero}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Emisor</span>
                    <span class="info-value">{comp.emisor_nombre[:35]}...</span>
                </div>
                <div class="info-row">
                    <span class="info-label">RUC Emisor</span>
                    <span class="info-value">{comp.emisor_ruc}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Fecha Emisión</span>
                    <span class="info-value">{fecha_str}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Cliente</span>
                    <span class="info-value">{comp.cliente_nombre[:30]}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Doc. Cliente</span>
                    <span class="info-value">{comp.cliente_num_doc}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Total</span>
                    <span class="info-value">S/ {float(comp.total):.2f}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Hash SUNAT</span>
                    <span class="info-value hash">{comp.hash_cpe or 'N/A'}</span>
                </div>
            </div>
            
            <div class="buttons">
                <a href="/api/v1/comprobantes/{comp.external_id}/pdf" target="_blank" class="btn btn-primary">
                    📄 Ver PDF
                </a>
                <a href="/api/v1/comprobantes/{comp.external_id}/xml" target="_blank" class="btn btn-outline">
                    📥 XML
                </a>
                <a href="{sunat_url}" target="_blank" class="btn btn-sunat">
                    🔍 Verificar en SUNAT
                </a>
            </div>
        </div>
        
        <div class="footer">
            Verificación generada por <a href="https://facturalo.pro">facturalo.pro</a>
        </div>
    </div>
</body>
</html>"""


def _pagina_no_encontrado() -> str:
    """HTML para comprobante no encontrado."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>No encontrado - facturalo.pro</title>
    <style>
        body { 
            font-family: -apple-system, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e293b);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #e2e8f0;
            text-align: center;
            padding: 20px;
        }
        .card { max-width: 400px; }
        h1 { font-size: 60px; margin-bottom: 10px; opacity: 0.5; }
        h2 { margin-bottom: 10px; }
        p { color: #64748b; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🔍</h1>
        <h2>Comprobante no encontrado</h2>
        <p>El código ingresado no corresponde a ningún comprobante registrado en el sistema.</p>
    </div>
</body>
</html>"""