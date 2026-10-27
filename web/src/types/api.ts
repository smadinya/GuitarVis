/* GENERATED FILE — do not edit.
 * Source: schema/api.schema.json (from apps/api schemas.py).
 * Regenerate with `make schema`.
 */

export type ApiBody = JobView | ErrorBody | Features | LinkRequest;
/**
 * Why a job failed, in terms the UI can turn into actionable text.
 *
 * The user needs to know whether to try a different file, a different song,
 * or come back later.
 */
export type FailureReason =
  | "unsupported_format"
  | "no_guitar_detected"
  | "too_long"
  | "fetch_failed"
  | "link_unusable"
  | "links_disabled"
  | "internal";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type HttpReason = "too_large" | "too_many_jobs" | "not_found" | "not_ready" | "unsupported_link";

/**
 * `failure` is set only when `status` is failed; `stage` only while running.
 *
 * `source_url` is the link a link job was made from, in canonical form, and
 * null for an upload.
 */
export interface JobView {
  attempts: number;
  created_at: string;
  duration_sec: number;
  failure: FailureView | null;
  id: string;
  percent: number;
  source_url: string | null;
  stage: string | null;
  status: JobStatus;
  title: string;
  updated_at: string;
}
/**
 * Why a job failed. Only a FailureReason: the HttpReason values describe
 * a request, never a job.
 */
export interface FailureView {
  message: string;
  reason: FailureReason;
  stage: string | null;
}
/**
 * Every error the api answers with. `error_body` builds each one from
 * this model, so the generated client types describe exactly what is sent.
 */
export interface ErrorBody {
  error: ErrorDetail;
}
export interface ErrorDetail {
  message: string;
  reason: FailureReason | HttpReason;
}
/**
 * GET /features: what this api has switched on, so the client shows only
 * what will work. Read from the api's own settings at start.
 */
export interface Features {
  url_ingestion: boolean;
}
/**
 * POST /jobs/from-url's body: one link, as the user pasted it.
 */
export interface LinkRequest {
  url: string;
}
