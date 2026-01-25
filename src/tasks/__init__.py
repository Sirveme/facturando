"""
Tareas asíncronas con Celery
"""
try:
    from src.tasks.envio_sunat import enviar_comprobante_task, celery_app
    __all__ = ['enviar_comprobante_task', 'celery_app']
except ImportError:
    print("⚠️  Celery no configurado")
    __all__ = []