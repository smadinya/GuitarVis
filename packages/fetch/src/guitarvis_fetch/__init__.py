"""Audio from links: the part of the system most likely to break, walled off.

Spec 012. Only the api and the worker depend on this package, and only
guitarvis_fetch.child imports yt-dlp, in a process of its own. Removing links
for good means deleting this package, one call in the api's app.py and one
branch in the worker's runner.
"""

__version__ = "0.1.0"
