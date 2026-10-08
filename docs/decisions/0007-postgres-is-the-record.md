# 0007. Postgres is the record; Redis carries job ids

**Status:** Accepted
**Date:** 2026-10-08
**Spec:** [005-api-job-queue](../specs/005-api-job-queue/spec.md#postgres-is-the-record-redis-carries-ids)

## Context

Phase 3 puts a queue between the api and the worker, on the stores the parent
spec chose: Postgres, Redis and S3-compatible object storage. Two of them now
hold facts about a job — the row a client reads and the RQ job a worker pulls —
and they can disagree. The api can die between inserting the row and
enqueueing it; Redis can lose its data; a worker can be killed outright and
never record that it stopped.

## Decision

The `jobs` table in Postgres is the only record of a job's state. RQ is told
only "run job `<uuid>`", and its job id is the GuitarVis job id. Clients never
read Redis. The known ways the stores disagree are repaired when a job is
read — by `GET /jobs/{id}`, and by the upload's dedupe lookup — with an update
conditional on the row being exactly as read, so a worker that writes first
wins.

## Consequences

Losing Redis loses pending work, not history: every job stays answerable, and a
lost one is failed honestly on its next read. There is no background reaper to
run or watch; a job nobody asks about can stay wrong until somebody does.

The cost is a dual write. Creating a job and queueing it are two steps against
two stores and cannot share a transaction; reconciliation exists to contain
what that allows. It also covers a third disagreement: a row `queued` while RQ
holds a job it will never run again — finished, or failed, stopped or
canceled for good, as when a worker cannot import `run_job` — is failed like
one whose RQ job is gone. A job RQ could still run but nothing does, such as a
scheduled retry with no scheduler running, would show as a job that never
moves. `attempts` in the job body, and the end-to-end test, are how it would
be noticed.

Revisit with Postgres as the queue (`SELECT … FOR UPDATE SKIP LOCKED`) if
reconciliation turns out to fire in practice: one service fewer, and creating
and queueing a job become one transaction.
