"""IDP queue — the single public seam between the files module and RQ.

Keeps RQ imports out of the files module (module boundary per CLAUDE.md).
"""

import uuid

import redis
from rq import Queue
from rq.job import Retry

from app.core.config import settings


def enqueue_document(doc_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Push a document-processing job onto the IDP queue.

    The worker executes ``app.modules.idp.jobs.process_document`` with the two
    string arguments. ``Retry`` handles transient failures (e.g. upload→commit
    race where the worker starts before the row is visible).
    """
    conn = redis.from_url(settings.redis_url)
    q = Queue(settings.idp_queue_name, connection=conn)
    q.enqueue(
        "app.modules.idp.jobs.process_document",
        str(doc_id),
        str(tenant_id),
        retry=Retry(max=3, interval=[10, 30, 60]),
    )
