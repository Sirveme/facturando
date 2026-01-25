from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from src.api.routes import router as api_router
from src.api.frontend import router as frontend_router
from src.models.models import Base
from src.api.dependencies import engine

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

# Incluir routers
app.include_router(api_router, prefix='/api')
app.include_router(frontend_router)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "facturalo.pro"}
