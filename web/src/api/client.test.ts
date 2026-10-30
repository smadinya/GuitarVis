import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeXhr, lastXhr } from "../test/fakeXhr";
import { JOB_ID, errorBody, jobView } from "../test/jobs";
import {
  ApiError,
  MAX_UPLOAD_BYTES,
  createJob,
  createJobFromUrl,
  errorFrom,
  getDocument,
  getFeatures,
  getJob,
  type Fetch,
} from "./client";
import { MESSAGES, isReason, type Reason } from "./messages";

function answering(status: number, body: unknown): Fetch {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return async () => new Response(text, { status });
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the call to reject");
}

describe("errorFrom", () => {
  it.each<[number, string, Reason]>([
    [404, "not_found", "not_found"],
    [409, "not_ready", "not_ready"],
    [413, "too_large", "too_large"],
    [422, "unsupported_format", "unsupported_format"],
    [429, "too_many_jobs", "too_many_jobs"],
    [500, "internal", "internal"],
    [503, "internal", "internal"],
  ])("maps a %i carrying %s", (status, sent, reason) => {
    const error = errorFrom(status, JSON.stringify(errorBody(sent, "Words.")));

    expect(error).toMatchObject({ status, reason, message: "Words." });
  });

  it("treats an answer without the api's error body as no answer", () => {
    expect(errorFrom(502, "<html>Bad gateway</html>").reason).toBe("unreachable");
    expect(errorFrom(500, "").reason).toBe("unreachable");
  });

  it("reads a bare 413 from a proxy as too large", () => {
    expect(errorFrom(413, "<html>Request Entity Too Large</html>").reason).toBe("too_large");
  });

  it("reads a reason this build does not know as internal, keeping the message", () => {
    const error = errorFrom(500, JSON.stringify(errorBody("brand_new", "Newer words.")));

    expect(error).toMatchObject({ reason: "internal", message: "Newer words." });
  });
});

describe("getJob and getDocument", () => {
  it("return what the api sent", async () => {
    await expect(getJob(JOB_ID, answering(200, jobView()))).resolves.toEqual(jobView());
    await expect(getDocument(JOB_ID, answering(200, { notes: [] }))).resolves.toEqual({
      notes: [],
    });
  });

  it("ask for the job's own paths", async () => {
    const paths: string[] = [];
    const recording: Fetch = async (path) => {
      paths.push(path);
      return new Response("{}");
    };

    await getJob(JOB_ID, recording);
    await getDocument(JOB_ID, recording);

    expect(paths).toEqual([`/jobs/${JOB_ID}`, `/jobs/${JOB_ID}/document`]);
  });

  it("reject with the mapped reason", async () => {
    const error = await rejection(getJob(JOB_ID, answering(404, errorBody("not_found"))));

    expect(error).toMatchObject({ status: 404, reason: "not_found" });
  });

  it("reject as unreachable when no answer comes back", async () => {
    const offline: Fetch = async () => {
      throw new TypeError("Failed to fetch");
    };

    const error = await rejection(getJob(JOB_ID, offline));

    expect(error).toMatchObject({ status: null, reason: "unreachable" });
  });
});

describe("a failed job's reason", () => {
  /** What a newer api might send: a reason this build has no text for. */
  const failedWith = (reason: string) => ({
    ...jobView({ status: "failed" }),
    failure: { reason, message: "Newer words.", stage: "transcription" },
  });

  it("reads as internal from getJob when this build does not know it, keeping the message", async () => {
    const job = await getJob(JOB_ID, answering(200, failedWith("brand_new")));

    expect(job.failure).toEqual({
      reason: "internal",
      message: "Newer words.",
      stage: "transcription",
    });
  });

  it("reads as internal when it is the client's own reason, which no server sends", async () => {
    const job = await getJob(JOB_ID, answering(200, failedWith("unreachable")));

    expect(job.failure?.reason).toBe("internal");
  });

  it("reads as internal when it is one only a request can have", async () => {
    const job = await getJob(JOB_ID, answering(200, failedWith("not_found")));

    expect(job.failure?.reason).toBe("internal");
  });

  it("is left alone when this build knows it", async () => {
    const job = await getJob(JOB_ID, answering(200, failedWith("no_guitar_detected")));

    expect(job.failure).toEqual({
      reason: "no_guitar_detected",
      message: "Newer words.",
      stage: "transcription",
    });
  });
});

describe("createJob", () => {
  beforeEach(() => {
    FakeXhr.last = null;
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const song = () => new File([new Uint8Array([1, 2, 3])], "song.mp3", { type: "audio/mpeg" });

  it("posts the file as the `file` field", () => {
    void createJob(song());

    const xhr = lastXhr();
    expect([xhr.method, xhr.url]).toEqual(["POST", "/jobs"]);
    expect(xhr.body).toBeInstanceOf(FormData);
    expect((xhr.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("resolves a new job on 202 and an existing one on 200", async () => {
    const created = createJob(song());
    lastXhr().respond(202, jobView());
    const existing = createJob(song());
    lastXhr().respond(200, jobView({ status: "succeeded" }));

    await expect(created).resolves.toEqual({ job: jobView(), created: true });
    await expect(existing).resolves.toMatchObject({ created: false });
  });

  it("reads an existing failed job's unknown reason as internal, keeping the message", async () => {
    const upload = createJob(song());
    lastXhr().respond(200, {
      ...jobView({ status: "failed" }),
      failure: { reason: "brand_new", message: "Newer words.", stage: null },
    });

    const { job, created } = await upload;

    expect(created).toBe(false);
    expect(job.failure).toEqual({ reason: "internal", message: "Newer words.", stage: null });
  });

  it("surfaces upload progress", () => {
    const fractions: number[] = [];
    void createJob(song(), (fraction) => fractions.push(fraction));

    lastXhr().progress(25, 100);
    lastXhr().progress(100, 100);

    expect(fractions).toEqual([0.25, 1]);
  });

  it("rejects with the mapped reason", async () => {
    const upload = createJob(song());
    lastXhr().respond(429, errorBody("too_many_jobs"));

    expect(await rejection(upload)).toMatchObject({ status: 429, reason: "too_many_jobs" });
  });

  it("rejects as unreachable on a network error", async () => {
    const upload = createJob(song());
    lastXhr().fail();

    expect(await rejection(upload)).toMatchObject({ status: null, reason: "unreachable" });
  });

  it("stops the upload when told to", async () => {
    const controller = new AbortController();
    const upload = createJob(song(), undefined, controller.signal);

    controller.abort();

    expect(lastXhr().aborted).toBe(true);
    expect(await rejection(upload)).toMatchObject({ reason: "unreachable" });
  });

  it("does not start an upload it was told to stop before it began", async () => {
    const controller = new AbortController();
    controller.abort();

    expect(await rejection(createJob(song(), undefined, controller.signal))).toMatchObject({
      reason: "unreachable",
    });
    expect(FakeXhr.last).toBeNull();
  });

  it("refuses a file over the limit without sending it", async () => {
    const big = song();
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });

    expect(await rejection(createJob(big))).toMatchObject({ reason: "too_large" });
    expect(FakeXhr.last).toBeNull();
  });
});

describe("createJobFromUrl", () => {
  const LINK = "https://youtu.be/kPdv44HtEoA";

  it("posts the link as JSON in a field named url", async () => {
    const sent: Array<[string, RequestInit | undefined]> = [];
    const recording: Fetch = async (path, init) => {
      sent.push([path, init]);
      return new Response(JSON.stringify(jobView()), { status: 202 });
    };

    await createJobFromUrl(LINK, undefined, recording);

    const [[path, init]] = sent;
    expect([path, init?.method]).toEqual(["/jobs/from-url", "POST"]);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ url: LINK });
  });

  it("resolves a new job on 202 and an existing one on 200", async () => {
    await expect(createJobFromUrl(LINK, undefined, answering(202, jobView()))).resolves.toEqual({
      job: jobView(),
      created: true,
    });
    await expect(
      createJobFromUrl(LINK, undefined, answering(200, jobView({ status: "running" }))),
    ).resolves.toMatchObject({ created: false });
  });

  it.each<[number, string]>([
    [403, "links_disabled"],
    [422, "unsupported_link"],
    [422, "link_unusable"],
    [422, "too_long"],
    [429, "too_many_jobs"],
    [503, "fetch_failed"],
    [504, "fetch_failed"],
    [500, "internal"],
  ])("rejects a %i carrying %s with the server's message", async (status, reason) => {
    const error = await rejection(
      createJobFromUrl(LINK, undefined, answering(status, errorBody(reason, "Server words."))),
    );

    expect(error).toMatchObject({ status, reason, message: "Server words." });
  });

  it("rejects as unreachable when nothing answers, or when told to stop", async () => {
    const offline: Fetch = async () => {
      throw new TypeError("Failed to fetch");
    };
    const controller = new AbortController();
    const listening: Fetch = (_path, init) =>
      new Promise((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
      );

    const stopped = createJobFromUrl(LINK, controller.signal, listening);
    controller.abort();

    expect(await rejection(createJobFromUrl(LINK, undefined, offline))).toMatchObject({
      status: null,
      reason: "unreachable",
    });
    expect(await rejection(stopped)).toMatchObject({ reason: "unreachable" });
  });

  it("reads an answer that is not JSON as no answer", async () => {
    const error = await rejection(createJobFromUrl(LINK, undefined, answering(202, "<html>")));

    expect(error.reason).toBe("unreachable");
  });
});

describe("getFeatures", () => {
  it("says links are on only when the api says true", async () => {
    await expect(getFeatures(answering(200, { url_ingestion: true }))).resolves.toEqual({
      url_ingestion: true,
    });
    for (const body of [{ url_ingestion: false }, { url_ingestion: "yes" }, {}, [], null]) {
      await expect(getFeatures(answering(200, body))).resolves.toEqual({ url_ingestion: false });
    }
  });

  it("asks /features", async () => {
    const paths: string[] = [];
    await getFeatures(async (path) => {
      paths.push(path);
      return new Response("{}");
    });

    expect(paths).toEqual(["/features"]);
  });

  it("rejects like every other call when the api cannot be reached", async () => {
    expect(await rejection(getFeatures(answering(404, "nope")))).toMatchObject({
      reason: "unreachable",
    });
  });
});

describe("MESSAGES", () => {
  it("gives every reason a headline and an action", () => {
    for (const [reason, message] of Object.entries(MESSAGES)) {
      expect(isReason(reason)).toBe(true);
      expect(message.headline.length).toBeGreaterThan(0);
      expect(message.action.length).toBeGreaterThan(0);
    }
    expect(Object.keys(MESSAGES)).toHaveLength(13); // twelve from the api, plus unreachable
    expect(isReason("toString")).toBe(false);
  });
});
