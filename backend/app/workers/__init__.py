"""Background processing package.

The document pipeline runs via FastAPI ``BackgroundTasks`` (see
``app.workers.orchestrator_task.run_document_pipeline``). Celery/Redis are no
longer used; OCR is performed through the free OCR.Space API.
"""
