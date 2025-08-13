# app/celery_app.py
import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"]
)
celery_app.conf.task_routes = {
    "app.tasks.update_user_library_task": {"queue": "encoding"},
}
