"""
Tareas Celery para envío de comprobantes a SUNAT
"""
from src.tasks.celery_app import celery_app  # ← USAR LA MISMA INSTANCIA
from src.api.dependencies import SessionLocal
from src.models.models import Comprobante, Emisor, LineaDetalle
from src.services.sunat_service import SunatService


@celery_app.task(name='enviar_comprobante_sunat', bind=True, max_retries=3)
def enviar_comprobante_task(self, comprobante_id: str):
    """
    Tarea asíncrona para enviar comprobante a SUNAT
    """
    db = SessionLocal()
    
    try:
        comprobante = db.query(Comprobante).filter(
            Comprobante.id == comprobante_id
        ).first()
        
        if not comprobante:
            print(f"❌ Comprobante {comprobante_id} no encontrado")
            return {"exito": False, "error": "Comprobante no encontrado"}
        
        emisor = db.query(Emisor).filter(
            Emisor.id == comprobante.emisor_id
        ).first()
        
        if not emisor:
            print(f"❌ Emisor no encontrado para comprobante {comprobante_id}")
            comprobante.estado = 'error'
            db.commit()
            return {"exito": False, "error": "Emisor no encontrado"}
        
        comprobante.estado = 'enviando'
        db.commit()
        
        print(f"📤 Enviando comprobante {comprobante.serie}-{comprobante.numero} a SUNAT...")
        
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
        
        comprobante = db.query(Comprobante).filter(
            Comprobante.id == comprobante_id
        ).first()
        
        if comprobante:
            comprobante.estado = 'error'
            comprobante.descripcion_respuesta = str(e)
            db.commit()
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        
        return {"exito": False, "error": str(e)}
        
    finally:
        db.close()