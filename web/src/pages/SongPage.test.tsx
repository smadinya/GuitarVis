// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { MESSAGES } from "../api/messages";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID, jobView } from "../test/jobs";
import type { JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { SongPage, type SongApi } from "./SongPage";
import { MAX_POLL_MS, POLL_MS } from "./progress";

const FIRST_SONG: TabDocument = firstSongJson;
const media = new FakeMedia();
const createMedia = () => media;

/** Answers getJob from a script, one entry per poll; the last repeats. */
function scripted(
  answers: Array<JobView | ApiError>,
  document: () => Promise<TabDocument> = async () => FIRST_SONG,
) {
  const calls = { job: 0, document: 0 };
  const api: SongApi = {
    getJob: async () => {
      const answer = answers[Math.min(calls.job, answers.length - 1)];
      calls.job += 1;
      if (answer instanceof ApiError) throw answer;
      return answer;
    },
    getDocument: () => {
      calls.document += 1;
      return document();
    },
  };
  return { api, calls };
}

async function settle() {
  await act(async () => {});
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function text(): string {
  return document.body.textContent ?? "";
}

describe("SongPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("moves through queued, running and retrying, then mounts the player", async () => {
    const { api } = scripted([
      jobView({ status: "queued" }),
      jobView({ status: "running", stage: "separation", percent: 12, attempts: 1 }),
      jobView({ status: "running", stage: "transcription", percent: 40, attempts: 2 }),
      jobView({ status: "succeeded", percent: 100, attempts: 2 }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();
    expect(text()).toContain("Waiting for a worker");
    await wait(POLL_MS);
    expect(text()).toContain("Isolating the guitar — 12%");
    expect(text()).not.toContain("Retrying");
    await wait(POLL_MS);
    expect(text()).toContain("Transcribing notes — 40%");
    expect(text()).toContain("Retrying — attempt 2 of 3");
    await wait(POLL_MS);

    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Guitar only" })).toBeTruthy();
    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/mix`);
  });

  it("stops polling once the job is finished", async () => {
    const { api, calls } = scripted([jobView({ status: "succeeded" })]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    await wait(POLL_MS * 5);

    expect(calls.job).toBe(1);
    expect(calls.document).toBe(1);
  });

  it("reads an unknown stage as Working", async () => {
    const { api } = scripted([jobView({ status: "running", stage: "mastering", percent: 90 })]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain("Working — 90%");
  });

  it("shows a failure's mapped text, the server's words, and a way out", async () => {
    const { api } = scripted([
      jobView({
        status: "failed",
        failure: {
          reason: "no_guitar_detected",
          message: "No clear guitar part was found in this recording.",
          stage: "separation",
        },
      }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain(MESSAGES.no_guitar_detected.headline);
    expect(text()).toContain(MESSAGES.no_guitar_detected.action);
    expect(text()).toContain("No clear guitar part was found in this recording.");
    expect(screen.getByRole("link", { name: "Upload another song" })).toBeTruthy();
  });

  it("says when there is no such song", async () => {
    const { api, calls } = scripted([new ApiError(404, "not_found", "There is no job with that id.")]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();
    await wait(MAX_POLL_MS);

    expect(text()).toContain(MESSAGES.not_found.headline);
    expect(screen.getByRole("link", { name: "Upload a song" })).toBeTruthy();
    expect(calls.job).toBe(1);
  });

  it("keeps polling, slower, through a lost connection, and recovers", async () => {
    const lost = new ApiError(null, "unreachable", "No answer from the server.");
    const { api, calls } = scripted([
      jobView({ status: "running", stage: "separation", percent: 5 }),
      lost,
      lost,
      jobView({ status: "running", stage: "separation", percent: 30 }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    await wait(POLL_MS);
    expect(text()).toContain("Reconnecting…");
    expect(text()).toContain("Isolating the guitar — 5%"); // the last answer stays up
    await wait(POLL_MS);
    expect(calls.job).toBe(2); // the next poll waits twice as long
    await wait(POLL_MS);
    expect(calls.job).toBe(3);
    await wait(POLL_MS * 4);

    expect(calls.job).toBe(4);
    expect(text()).not.toContain("Reconnecting…");
    expect(text()).toContain("Isolating the guitar — 30%");
  });

  it("refuses a document from a newer schema", async () => {
    const { api } = scripted([jobView({ status: "succeeded" })], async () => ({
      ...FIRST_SONG,
      schema_version: 2,
    }));
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain("processed by a newer version of GuitarVis");
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
  });

  it("treats a document it cannot build as one that will not load", async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on("unhandledRejection", onUnhandled);
    // No `source`: canRead passes, then buildSong throws reading source.title.
    const broken = { ...FIRST_SONG, source: undefined } as unknown as TabDocument;
    const { api } = scripted([jobView({ status: "succeeded" })], async () => broken);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();
    await wait(0);
    process.off("unhandledRejection", onUnhandled);

    expect(text()).toContain("We couldn't load the tab.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(text()).not.toContain("Loading the tab");
    expect(unhandled).toEqual([]);
  });

  it("offers a retry when the document will not load", async () => {
    let fail = true;
    const { api } = scripted([jobView({ status: "succeeded" })], async () => {
      if (fail) throw new ApiError(null, "unreachable", "No answer.");
      return FIRST_SONG;
    });
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    fail = false;
    await act(async () => screen.getByRole("button", { name: "Try again" }).click());

    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
  });
});
