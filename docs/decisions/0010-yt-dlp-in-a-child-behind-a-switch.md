# 0010. Links are fetched by yt-dlp in a child process, behind a switch that is off by default

**Status:** Accepted
**Date:** 2026-10-26
**Spec:** [012-url-ingestion](../specs/012-url-ingestion/spec.md#where-yt-dlp-runs)

## Context

Phase 6 lets a user paste a YouTube link instead of uploading a file. The
part that fetches is the part most likely to break, since YouTube changes
often and extraction tooling follows days later, and the part most likely to
need removing, since fetching from YouTube breaks its terms of service and
carries legal exposure beyond them. The parent spec asked for it to be
swappable, testable on its own, and possible to turn off in config.

The api must answer a lookup within a deadline, and a library call in a
thread cannot be stopped. A fetch runs on user input next to the database URL
and the storage secret. yt-dlp's command line reads `yt-dlp.conf` from the
host, and the library loads plugins from the same configuration directories.

## Decision

yt-dlp runs as a library inside a child process of our own,
`python -I -m guitarvis_fetch.child`, started by the api for a lookup and by
the worker for a download. The child gets no `GUITARVIS_*` variables and has
plugins switched off. It answers in JSON lines, classifies every failure while
yt-dlp's exception types are visible, and is killed with its whole process
group at its deadline, and when its parent dies by any means, SIGKILL
included. Deno is its JavaScript runtime.

`GUITARVIS_URL_INGESTION` turns links on, and it is off by default. The api
refuses links with 403 `links_disabled` when it is off, the worker fails a
queued link job with `links_disabled`, and the client hides the link field.

## Consequences

A hang, a crash or a memory blow-up in yt-dlp costs one child, never the api
or a worker. Failures arrive typed, not as English on stderr, and the failure
catalog maps each kind to a reason, a status, a message and a log level. The
whole path is one package, one call in the api's `app.py` and one branch in
the worker, so removing it touches no upload code.

The costs: an interpreter starts for every lookup (a few hundred
milliseconds); every host that fetches needs Deno 2.3 or later, as it needs
ffmpeg; and yt-dlp needs bumping when YouTube breaks it, with `make smoke-url`
as the check. A deployment that has not decided takes no risk, and a fresh
checkout shows the link field only under `make api`.

Revisit if hosting cannot fetch from YouTube at all (open decision 12), if
retention rules make stored fetches untenable (open decision 13), or if a
switch that works without a restart becomes necessary, which needs the admin
surface that open decision 11 has not provided.
