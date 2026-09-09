from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from src.api.routes import router as api_router
from src.api.frontend import router as frontend_router
from src.models.models import Base
from src.api.dependencies import engine

from src.api.productos import router as productos_router
from src.api.clientes import router as clientes_router

from src.api.v1.router import router as api_v1_router
from src.api.admin import router as admin_router
from src.api.registro import router as registro_router
from src.api.verificacion import router as verificacion_router
from src.api.contadores import router as contadores_router
from src.api.stock_ui import router as stock_router
from src.api.importaciones_ui import router as importaciones_router
from src.api.guias_ui import router as guias_router
from src.api.lookup_ui import router as lookup_router
from src.api.referencias_ui import router as referencias_router

app = FastAPI(
    title='facturalo.pro',
    version='0.1.0',
    description='Sistema de Facturación Electrónica SUNAT'
)

# Crear tablas si no existen
try:
    Base.metadata.create_all(bind=engine)
except Exception:
    pass

# Montar archivos estáticos
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/robots.txt", include_in_schema=False)
    async def serve_robots():
        return FileResponse(static_path / "robots.txt", media_type="text/plain")

    @app.get("/llms.txt", include_in_schema=False)
    async def serve_llms():
        return FileResponse(static_path / "llms.txt", media_type="text/plain")

    @app.get("/llms-full.txt", include_in_schema=False)
    async def serve_llms_full():
        return FileResponse(static_path / "llms-full.txt", media_type="text/plain")

    @app.get("/sitemap.xml", include_in_schema=False)
    async def serve_sitemap():
        return FileResponse(static_path / "sitemap.xml", media_type="application/xml")

# Incluir routers
#app.include_router(api_router, prefix='/api')
#app.include_router(frontend_router)
#app.include_router(productos_router)
#app.include_router(clientes_router)
app.include_router(api_v1_router)
app.include_router(admin_router)


# Antes de api_router: sus rutas literales (/api/comprobantes/recientes) deben
# ganarle al catch-all /api/comprobantes/{comprobante_id} de routes.py.
app.include_router(referencias_router, include_in_schema=False)
app.include_router(api_router, prefix='/api', include_in_schema=False)
app.include_router(frontend_router, include_in_schema=False)
app.include_router(productos_router, include_in_schema=False)
app.include_router(clientes_router, include_in_schema=False)
#app.include_router(admin_router, include_in_schema=False)
app.include_router(registro_router)
app.include_router(verificacion_router)

app.include_router(contadores_router)
app.include_router(stock_router, include_in_schema=False)
app.include_router(importaciones_router, include_in_schema=False)
app.include_router(guias_router, include_in_schema=False)
app.include_router(lookup_router, include_in_schema=False)

# ── Fingerprint de build: permite confirmar en /health QUÉ versión corre en prod ──
import os as _os
import hashlib as _hashlib
from datetime import datetime as _dt, timezone as _tz

_STARTED_AT = _dt.now(_tz.utc).isoformat(timespec="seconds")


def _code_fingerprint() -> str:
    """Hash corto del código Python desplegado (src/**/*.py). Cambia SOLO si cambia el
    código → detecta deploys que no tomaron los últimos cambios. Si BUILD_TAG (env) está
    seteado, se usa ese. No-fatal: ante cualquier error devuelve 'unknown'."""
    try:
        from src.core.config import settings as _s
        if getattr(_s, "BUILD_TAG", ""):
            return _s.BUILD_TAG
        root = Path(__file__).resolve().parent  # .../src
        h = _hashlib.sha256()
        for p in sorted(root.rglob("*.py")):
            h.update(p.relative_to(root).as_posix().encode())
            # Normaliza CRLF→LF: mismo hash en Windows (local) y Linux (Railway).
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        return h.hexdigest()[:12]
    except Exception:
        return "unknown"


_BUILD_TAG = _code_fingerprint()


@app.get("/health")
def health_check():
    from src.core.config import settings as _s
    return {
        "status": "ok",
        "service": "facturalo.pro",
        "version": getattr(_s, "APP_VERSION", "?"),   # sello manual (bumpear cada deploy)
        "build": _BUILD_TAG,                           # fingerprint automático del código .py
        "git": (_os.getenv("RAILWAY_GIT_COMMIT_SHA", "") or "")[:12] or None,
        "started_at": _STARTED_AT,                     # cuándo arrancó este proceso
    }
