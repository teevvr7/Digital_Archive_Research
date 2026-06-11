"""RQ worker entrypoint.

Run with: ``python -m app.worker`` (or via the Docker worker image).
Listens on the ``idp`` queue defined in settings.

On Windows, RQ's default Worker uses os.fork() which doesn't exist.
SimpleWorker runs jobs in-process (no forking) and is the correct choice
for Windows dev. Production Linux uses the standard forking Worker.
"""

import logging
import platform

import redis
from rq import Queue, Worker

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    conn = redis.from_url(settings.redis_url)
    queue = Queue(settings.idp_queue_name, connection=conn)
    logger.info("Starting worker on queue '%s'", settings.idp_queue_name)

    if platform.system() == "Windows":
        from rq import SimpleWorker
        logger.info("Windows detected — using SimpleWorker (no os.fork)")
        worker = SimpleWorker([queue], connection=conn)
        worker.work()
    else:
        worker = Worker([queue], connection=conn)
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
