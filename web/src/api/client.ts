/**
 * The api, from the browser. Every call resolves to a typed result or
 * rejects with an ApiError carrying a Reason, never a bare string.
 *
 * Paths are relative: the client is served from the api's origin (in
 * development, through the Vite proxy), so there is no CORS.
 */
import type { FailureView, JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { isReason, type Reason, type ServerReason } from "./messages";

/** Mirrors the api's default GUITARVIS_MAX_UPLOAD_MB, so a file far too big
 * is refused before it is sent. The api's own limit still decides. */
export const MAX_UPLOAD_BYTES = 150 * 1024 * 1024;

export class ApiError extends Error {
  /** The HTTP status, or null when no answer came back. */
  readonly status: number | null;
  readonly reason: Reason;

  constructor(status: number | null, reason: Reason, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
  }
}

export type Fetch = (path: string, init?: RequestInit) => Promise<Response>;

const browserFetch: Fetch = (path, init) => fetch(path, init);

export interface Upload {
  job: JobView;
  /** False when the api already had this file: 200 rather than 202. */
  created: boolean;
}

export async function getJob(jobId: string, fetcher: Fetch = browserFetch): Promise<JobView> {
  return knownReasons((await getJson(`/jobs/${encodeURIComponent(jobId)}`, fetcher)) as WireJob);
}

export async function getDocument(
  jobId: string,
  fetcher: Fetch = browserFetch,
): Promise<TabDocument> {
  return (await getJson(`/jobs/${encodeURIComponent(jobId)}/document`, fetcher)) as TabDocument;
}

/**
 * POST /jobs. Through XMLHttpRequest, not fetch: only XHR reports upload
 * progress, and a WAV can be tens of megabytes. Aborting `signal` stops the
 * upload, which then rejects as unreachable.
 */
export function createJob(
  file: File,
  onProgress: (fraction: number) => void = () => {},
  signal?: AbortSignal,
): Promise<Upload> {
  if (signal?.aborted) return Promise.reject(noAnswer());
  if (file.size > MAX_UPLOAD_BYTES) {
    // Sent anyway, the api would refuse it early and close the connection,
    // and some browsers report that as a network error, not as a 413.
    return Promise.reject(new ApiError(413, "too_large", "That file is over the upload limit."));
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/jobs");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(noAnswer());
    xhr.onabort = () => reject(noAnswer());
    xhr.onload = () => {
      if (xhr.status !== 200 && xhr.status !== 202) {
        reject(errorFrom(xhr.status, xhr.responseText));
        return;
      }
      try {
        const job = knownReasons(JSON.parse(xhr.responseText) as WireJob);
        resolve({ job, created: xhr.status === 202 });
      } catch {
        reject(new ApiError(xhr.status, "unreachable", "The answer was not JSON."));
      }
    };
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

/**
 * The ApiError for an error response. The api always answers with its error
 * body. A response without one came from something in between, a proxy
 * with the api down, say, so it counts as no answer from the api, except a
 * bare 413, which any proxy may send for an oversized upload.
 */
export function errorFrom(status: number, body: string): ApiError {
  const detail = errorDetail(body);
  if (detail !== null) {
    // A reason this build does not know (a newer api) reads as internal.
    const reason = isReason(detail.reason) ? detail.reason : "internal";
    return new ApiError(status, reason, detail.message);
  }
  if (status === 413) return new ApiError(status, "too_large", "That file is too large.");
  return new ApiError(status, "unreachable", `No answer from the api (HTTP ${status}).`);
}

/**
 * A JobView as it arrives. The generated type says a failure's reason is one
 * this build knows; the wire makes no such promise, since a newer api may add
 * a reason, so here it is a plain string until knownReasons has checked it.
 */
type WireJob = Omit<JobView, "failure"> & {
  failure: (Omit<FailureView, "reason"> & { reason: string }) | null;
};

/**
 * The job, with a failure reason this build has no text for read as
 * internal and the server's message kept, as errorFrom does for an error
 * body. Without this an unknown reason would index MESSAGES and find nothing.
 */
function knownReasons(job: WireJob): JobView {
  const { failure } = job;
  if (!failure) return { ...job, failure: null };
  const reason = isServerReason(failure.reason) ? failure.reason : "internal";
  return { ...job, failure: { ...failure, reason } };
}

/** "unreachable" is the client's own reason: no server sends it, so a job
 * that claims it is as unknown as any other word. */
function isServerReason(value: string): value is ServerReason {
  return isReason(value) && value !== "unreachable";
}

async function getJson(path: string, fetcher: Fetch): Promise<unknown> {
  let response: Response;
  let body: string;
  try {
    response = await fetcher(path, { headers: { Accept: "application/json" } });
    body = await response.text();
  } catch {
    throw noAnswer();
  }
  if (!response.ok) throw errorFrom(response.status, body);
  try {
    return JSON.parse(body);
  } catch {
    throw new ApiError(response.status, "unreachable", "The answer was not JSON.");
  }
}

function noAnswer(): ApiError {
  return new ApiError(null, "unreachable", "No answer from the server.");
}

function errorDetail(body: string): { reason: string; message: string } | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || !("error" in parsed)) return null;
  const error: unknown = parsed.error;
  if (typeof error !== "object" || error === null) return null;
  if (!("reason" in error) || !("message" in error)) return null;
  const { reason, message } = error;
  return typeof reason === "string" && typeof message === "string" ? { reason, message } : null;
}
