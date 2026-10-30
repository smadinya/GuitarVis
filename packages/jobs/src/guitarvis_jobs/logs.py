"""How the api and the worker print their log lines.

One handler, on the root logger, writing to stderr in one format, with our
own loggers at INFO and every other library's from WARNING. Each app calls
`configure_logging` once, as it starts to serve: the worker before RQ starts,
the api in its lifespan. uvicorn's loggers keep their own handlers and do
not propagate to the root, and RQ adds no handler of its own once the root
has one, so each line prints once.
"""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# The packages both apps run; each app names its own loggers beside them.
SHARED_INFO_LOGGERS = ("guitarvis_core", "guitarvis_jobs", "guitarvis_fetch")


def configure_logging(*info_loggers: str) -> None:
    """Our lines at INFO, with their time, level and logger.

    Does nothing when the root logger already has a handler: one from a
    --log-config, say, or pytest's log capture.
    """
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.WARNING, format=LOG_FORMAT)
    for name in (*SHARED_INFO_LOGGERS, *info_loggers):
        logging.getLogger(name).setLevel(logging.INFO)
