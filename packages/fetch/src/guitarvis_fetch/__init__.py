"""Audio from links: the part of the system most likely to break, walled off.

Spec 012. Only guitarvis_fetch.child imports yt-dlp, in a process of its own.
This package's only users are the api's routes_links.py, services.py and
schemas.py (app.py installs the router with one line) and the worker's
ingest.py (UrlSource) and runner.py (the _fetch branch and start-up), so
removing links is a bounded change that leaves the upload path alone
(ADR 0010).
"""

__version__ = "0.1.0"
