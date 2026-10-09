import { useEffect, useState } from "react";

import { ApiError, getDocument, getJob } from "../api/client";
import type { MediaLike } from "../playback/clock";
import { Player } from "../player/Player";
import { buildSong, canRead, type Song } from "../song";
import type { JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { Failure, UploadAnother } from "./Failure";
import { POLL_MS, backoff, retryText, stageText } from "./progress";

export interface SongApi {
  getJob: (jobId: string) => Promise<JobView>;
  getDocument: (jobId: string) => Promise<TabDocument>;
}

const API: SongApi = { getJob: (id) => getJob(id), getDocument: (id) => getDocument(id) };
const newAudio = (): MediaLike => new Audio();

interface Poll {
  job: JobView | null;
  missing: boolean;
  reconnecting: boolean;
}

/**
 * Poll the job until it is terminal. A failed poll keeps polling, slower.
 * The client never decides a job has hung: a row can sit at a stale percent
 * while RQ waits to retry it, and a job the system really lost is failed by
 * the api's reconciliation, which these reads trigger.
 */
function useJob(jobId: string, api: SongApi): Poll {
  const [poll, setPoll] = useState<Poll>({ job: null, missing: false, reconnecting: false });
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_MS;
    const check = async () => {
      try {
        const job = await api.getJob(jobId);
        if (cancelled) return;
        delay = POLL_MS;
        setPoll({ job, missing: false, reconnecting: false });
        if (job.status === "succeeded" || job.status === "failed") return;
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.reason === "not_found") {
          setPoll({ job: null, missing: true, reconnecting: false });
          return;
        }
        delay = backoff(delay);
        setPoll((previous) => ({ ...previous, reconnecting: true }));
      }
      timer = setTimeout(() => void check(), delay);
    };
    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, api]);
  return poll;
}

type Loaded =
  | { kind: "loading" }
  | { kind: "ready"; song: Song }
  | { kind: "failed" }
  | { kind: "newer" };

function useSong(jobId: string, ready: boolean, api: SongApi): [Loaded, () => void] {
  const [loaded, setLoaded] = useState<Loaded>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoaded({ kind: "loading" });
    api.getDocument(jobId).then(
      (doc) => {
        if (cancelled) return;
        setLoaded(canRead(doc) ? { kind: "ready", song: buildSong(doc) } : { kind: "newer" });
      },
      () => {
        if (!cancelled) setLoaded({ kind: "failed" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [jobId, ready, api, attempt]);
  return [loaded, () => setAttempt((n) => n + 1)];
}

export interface SongPageProps {
  jobId: string;
  api?: SongApi;
  createMedia?: () => MediaLike;
}

export function SongPage({ jobId, api = API, createMedia = newAudio }: SongPageProps) {
  const { job, missing, reconnecting } = useJob(jobId, api);
  const [loaded, retry] = useSong(jobId, job?.status === "succeeded", api);

  if (missing) {
    return (
      <main className="song-page">
        <Failure reason="not_found" />
        <UploadAnother label="Upload a song" />
      </main>
    );
  }

  return (
    <main className="song-page">
      <h1>{job?.title ?? "Loading…"}</h1>
      {reconnecting && <p role="status">Reconnecting…</p>}
      {job !== null && <JobBody job={job} loaded={loaded} retry={retry} jobId={jobId} createMedia={createMedia} />}
    </main>
  );
}

function JobBody({
  job,
  loaded,
  retry,
  jobId,
  createMedia,
}: {
  job: JobView;
  loaded: Loaded;
  retry: () => void;
  jobId: string;
  createMedia: () => MediaLike;
}) {
  const retrying = retryText(job);
  switch (job.status) {
    case "queued":
      return (
        <div className="progress">
          <p>Waiting for a worker</p>
          {retrying !== null && <p>{retrying}</p>}
        </div>
      );
    case "running":
      return (
        <div className="progress">
          <p>
            {stageText(job.stage)} — {job.percent}%
          </p>
          <progress value={job.percent} max={100} />
          {retrying !== null && <p>{retrying}</p>}
        </div>
      );
    case "failed":
      return (
        <>
          <Failure reason={job.failure?.reason ?? "internal"} detail={job.failure?.message} />
          <UploadAnother />
        </>
      );
    case "succeeded":
      return <Finished loaded={loaded} retry={retry} jobId={jobId} createMedia={createMedia} />;
  }
}

function Finished({
  loaded,
  retry,
  jobId,
  createMedia,
}: {
  loaded: Loaded;
  retry: () => void;
  jobId: string;
  createMedia: () => MediaLike;
}) {
  switch (loaded.kind) {
    case "loading":
      return <p role="status">Loading the tab…</p>;
    case "failed":
      return (
        <div role="alert">
          <p>We couldn't load the tab.</p>
          <button onClick={retry}>Try again</button>
        </div>
      );
    case "newer":
      return (
        <p role="alert">
          This song was processed by a newer version of GuitarVis. Reload the page.
        </p>
      );
    case "ready":
      return <Player song={loaded.song} jobId={jobId} createMedia={createMedia} />;
  }
}
