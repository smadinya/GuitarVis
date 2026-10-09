/** JobViews for tests, shaped by the generated api types. */
import type { JobView } from "../types/api";

export const JOB_ID = "5f0c6c2e-0000-4000-8000-000000000001";

export function jobView(fields: Partial<JobView> = {}): JobView {
  return {
    id: JOB_ID,
    status: "queued",
    stage: null,
    percent: 0,
    attempts: 0,
    title: "Song",
    duration_sec: 13.871,
    failure: null,
    created_at: "2026-10-08T12:00:00Z",
    updated_at: "2026-10-08T12:00:00Z",
    ...fields,
  };
}

export function errorBody(reason: string, message = "From the api."): unknown {
  return { error: { reason, message } };
}
