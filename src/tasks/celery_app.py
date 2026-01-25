from celery import Celery
from src.core.config import settings

broker = settings.redis_url or 'redis://localhost:6379/0'
celery_app = Celery('facturalo', broker=broker, backend=broker)

# Basic config
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    imports=['src.tasks.tasks'],
)

# Ensure tasks module is imported so tasks are registered when worker starts
try:
    from src.tasks import tasks  # noqa: F401
except Exception:
    pass
