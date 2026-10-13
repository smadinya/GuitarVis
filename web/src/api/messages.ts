/**
 * The one map from a failure reason to what the user reads.
 *
 * Typed against the generated api types: a reason added on the server
 * regenerates src/types/api.ts, and this file then fails to compile until the
 * new reason has text. That is the mechanism behind CONVENTIONS' "adding a
 * reason means updating the UI mapping".
 */
import type { ErrorDetail, FailureReason } from "../types/api";

/** Every reason the api can send. */
export type ServerReason = ErrorDetail["reason"];
/** Those, plus the client's own: a request that got no answer from the api. */
export type Reason = ServerReason | "unreachable";

export interface Message {
  headline: string;
  action: string;
}

/** The reasons a job itself can fail with. */
const JOB_MESSAGES: Record<FailureReason, Message> = {
  unsupported_format: {
    headline: "We couldn't read that file as audio.",
    action: "Try an MP3, WAV, FLAC or M4A file.",
  },
  no_guitar_detected: {
    headline: "We couldn't hear a guitar in that song.",
    action: "Try a song where the guitar is clearly audible.",
  },
  too_long: {
    headline: "That recording is too long.",
    action: "Upload a single song, up to ten minutes long.",
  },
  fetch_failed: {
    headline: "We couldn't fetch that audio.",
    action: "Upload the file itself instead.",
  },
  internal: {
    headline: "Something went wrong on our side.",
    action: "Try again in a few minutes.",
  },
};

export const MESSAGES: Record<Reason, Message> = {
  ...JOB_MESSAGES,
  too_large: {
    headline: "That file is too large.",
    action: "Upload a smaller file. A compressed format such as MP3 helps.",
  },
  too_many_jobs: {
    headline: "You already have songs processing.",
    action: "Wait for one to finish, then try again.",
  },
  not_found: {
    headline: "We couldn't find that song.",
    action: "Upload it again.",
  },
  not_ready: {
    headline: "That song isn't ready yet.",
    action: "Wait a moment, then reload the page.",
  },
  unreachable: {
    headline: "We couldn't reach GuitarVis.",
    action: "Check your connection, then try again.",
  },
};

export function isReason(value: unknown): value is Reason {
  return typeof value === "string" && Object.hasOwn(MESSAGES, value);
}

/** Whether a failed job's reason is one this build knows. */
export function isFailureReason(value: unknown): value is FailureReason {
  return typeof value === "string" && Object.hasOwn(JOB_MESSAGES, value);
}
