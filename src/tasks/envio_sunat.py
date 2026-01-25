"""
Tareas Celery para envío de comprobantes a SUNAT
"""
from celery import Celery
from src.core.config import settings
from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, LineaDetalle
from src.services.sunat_service import SunatService
import os

# Configurar Celery
celery_app = Celery('facturalo')

# Usar mock si está configurado
USE_MOCK = os.getenv('USE_MOCK_CELERY', 'false').lower() == 'true'

if USE_MOCK:
    # Mock para desarrollo sin Redis
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
else:
    # Configuración real con Redis
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.result_backend = settings.redis_url

celery_app.conf.task_serializer = 'json'
celery_app.conf.result_serializer = 'json'
celery_app.conf.accept_content = ['json']
celery_app.conf.timezone = 'America/Lima'
celery_app.conf.enable_utc = True


@celery_app.task(name='enviar_comprobante_sunat', bind=True, max_retries=3)
def enviar_comprobante_task(self, comprobante_id: str):
    """
    Tarea asíncrona para enviar comprobante a SUNAT
    
    Args:
        comprobante_id: ID del comprobante a enviar
    """
    db = SessionLocal()
    
    try:
        # Buscar comprobante
        comprobante = db.query(Comprobante).filter(
            Comprobante.id == comprobante_id
        ).first()
        
        if not comprobante:
            print(f"❌ Comprobante {comprobante_id} no encontrado")
            return {"exito": False, "error": "Comprobante no encontrado"}
        
        # Buscar emisor
        emisor = db.query(Emisor).filter(
            Emisor.id == comprobante.emisor_id
        ).first()
        
        if not emisor:
            print(f"❌ Emisor no encontrado para comprobante {comprobante_id}")
            comprobante.estado = 'error'
            db.commit()
            return {"exito": False, "error": "Emisor no encontrado"}
        
        # Actualizar estado
        comprobante.estado = 'enviando'
        db.commit()
        
        print(f"📤 Enviando comprobante {comprobante.serie}-{comprobante.numero} a SUNAT...")
        
        # Enviar a SUNAT
        sunat_service = SunatService(db)
        resultado = sunat_service.enviar_comprobante(comprobante.id)
        
        if resultado.get('exito'):
            print(f"✅ Comprobante {comprobante.serie}-{comprobante.numero} aceptado por SUNAT")
            comprobante.estado = 'aceptado'
        else:
            print(f"❌ Comprobante {comprobante.serie}-{comprobante.numero} rechazado: {resultado.get('mensaje')}")
            comprobante.estado = 'rechazado'
            comprobante.descripcion_respuesta = resultado.get('mensaje', 'Error desconocido')
        
        db.commit()
        
        return resultado
        
    except Exception as e:
        print(f"❌ Error enviando comprobante {comprobante_id}: {str(e)}")
        
        # Actualizar estado a error
        comprobante = db.query(Comprobante).filter(
            Comprobante.id == comprobante_id
        ).first()
        
        if comprobante:
            comprobante.estado = 'error'
            comprobante.descripcion_respuesta = str(e)
            db.commit()
        
        # Reintentar si es posible
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        
        return {"exito": False, "error": str(e)}
        
    finally:
        db.close()