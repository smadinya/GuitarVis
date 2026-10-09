/* GENERATED FILE — do not edit.
 * Source: schema/api.schema.json (from apps/api schemas.py).
 * Regenerate with `make schema`.
 */

export type ApiResponse = JobView | ErrorBody;
/**
 * Why a job failed, in terms the UI can turn into actionable text.
 *
 * The user needs to know whether to try a different file, a different song,
 * or come back later.
 */
export type FailureReason = "unsupported_format" | "no_guitar_detected" | "too_long" | "fetch_failed" | "internal";
export type HttpReason = "too_large" | "too_many_jobs" | "not_found" | "not_ready";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

/**
 * `failure` is set only when `status` is failed; `stage` only while running.
 */
export interface JobView {
  attempts: number;
  created_at: string;
  duration_sec: number;
  failure: FailureView | null;
  id: string;
  percent: number;
  stage: string | null;
  status: JobStatus;
  title: string;
  updated_at: string;
}
export interface FailureView {
  message: string;
  reason: FailureReason | HttpReason;
  stage: string | null;
}
/**
 * Every error the api answers with. `errors.error_body` builds it; this
 * model describes it, for the generated client types and the tests.
 */
export interface ErrorBody {
  error: ErrorDetail;
}
export interface ErrorDetail {
  message: string;
  reason: FailureReason | HttpReason;
}
