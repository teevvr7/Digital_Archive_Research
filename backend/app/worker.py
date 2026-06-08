"""RQ worker entrypoint.

Run with: ``python -m app.worker`` (or via the Docker worker image).
Listens on the ``idp`` queue defined in settings.
"""

import logging

import redis
from rq import Queue, Worker

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    conn = redis.from_url(settings.redis_url)
    queue = Queue(settings.idp_queue_name, connection=conn)
    logger.info("Starting worker on queue '%s'", settings.idp_queue_name)
    worker = Worker([queue], connection=conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
