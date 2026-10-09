/** What the song page says while a job runs, and how often it asks. */
import type { JobView } from "../types/api";

export const POLL_MS = 1500;
export const MAX_POLL_MS = 10_000;
/** The api's Retry(max=2): three attempts in all. */
export const MAX_ATTEMPTS = 3;

const STAGES: Record<string, string> = {
  separation: "Isolating the guitar",
  transcription: "Transcribing notes",
  structure: "Finding the beat and chords",
  fretboard: "Working out fingerings",
};

/** `stage` is a plain string in the api, so an unknown one reads "Working". */
export function stageText(stage: string | null): string {
  return (stage !== null && STAGES[stage]) || "Working";
}

export function retryText(job: JobView): string | null {
  return job.attempts > 1 ? `Retrying — attempt ${job.attempts} of ${MAX_ATTEMPTS}` : null;
}

/** After a failed poll, wait twice as long, up to MAX_POLL_MS. */
export function backoff(delay: number): number {
  return Math.min(delay * 2, MAX_POLL_MS);
}
