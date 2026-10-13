import { describe, expect, it } from "vitest";

import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import { MAX_FAILURES, PlaybackEngine } from "./engine";

const JOB = "5f0c6c2e-0000-4000-8000-000000000001";
const MIX = `/jobs/${JOB}/audio/mix`;
const GUITAR = `/jobs/${JOB}/audio/guitar`;

function setup() {
  const media = new FakeMedia();
  const frames = new FakeFrames();
  let ms = 0;
  const engine = new PlaybackEngine({
    media,
    jobId: JOB,
    duration: 200,
    now: () => ms,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  const seen: number[] = [];
  engine.onFrame((t) => seen.push(t));
  /** Let song time pass while playing, as the element and the clock see it. */
  const play = (seconds: number) => {
    ms += seconds * 1000 * media.playbackRate;
    media.advance(seconds);
    frames.flush();
  };
  return { media, frames, engine, seen, play };
}

/** An engine with the mix loaded, playing from `at`. */
function playingAt(at: number) {
  const fixture = setup();
  fixture.media.loadMetadata(200);
  fixture.engine.seek(at);
  fixture.engine.play();
  fixture.frames.flush();
  return fixture;
}

describe("loading", () => {
  it("starts on the mix, paused, with pitch preserved", () => {
    const { media, engine } = setup();

    expect(media.src).toBe(MIX);
    expect(media.preservesPitch).toBe(true);
    expect(media.webkitPreservesPitch).toBe(true);
    expect(engine.getState()).toMatchObject({ playing: false, source: "mix", rate: 1 });
    expect(engine.canStretch).toBe(true);
  });

  it("uses the document's duration until the media reports its own", () => {
    const { media, engine } = setup();
    expect(engine.getState().duration).toBe(200);

    media.loadMetadata(201.5);

    expect(engine.getState().duration).toBe(201.5);
  });
});

describe("the first load", () => {
  it("draws the sought time before the media has any", () => {
    const { media, engine, frames, seen } = setup();
    frames.flush();

    engine.seek(30);
    frames.flush();

    expect(seen.at(-1)).toBe(30);
    media.loadMetadata(200);
    expect(media.currentTime).toBe(30);
  });

  it("plays when metadata arrives if play was pressed before it", () => {
    const { media, engine } = setup();

    engine.play();

    expect(engine.getState().playing).toBe(true);
    expect(media.paused).toBe(true); // nothing to play yet
    media.loadMetadata(200);
    expect(media.paused).toBe(false);
    expect(engine.getState().playing).toBe(true);
  });

  it("stays paused when pause follows play before metadata arrives", () => {
    const { media, engine } = setup();

    engine.play();
    engine.pause();
    media.loadMetadata(200);

    expect(media.paused).toBe(true);
    expect(engine.getState().playing).toBe(false);
  });
});

describe("speed", () => {
  it("sets the rate and the default rate together, and keeps pitch", () => {
    const { media, engine } = setup();
    media.preservesPitch = false;

    engine.setRate(0.5);

    expect(media.playbackRate).toBe(0.5);
    expect(media.defaultPlaybackRate).toBe(0.5);
    expect(media.preservesPitch).toBe(true);
    expect(engine.getState().rate).toBe(0.5);
  });
});

describe("the mix and guitar toggle", () => {
  it("keeps the time, the play state and the rate", () => {
    const { media, engine, play } = playingAt(40);
    engine.setRate(0.75);
    play(2);

    engine.setSource("guitar");

    expect(media.src).toBe(GUITAR);
    expect(engine.getState()).toMatchObject({ source: "guitar", playing: true });
    media.loadMetadata(200);
    expect(media.currentTime).toBe(42);
    expect(media.paused).toBe(false);
    expect(media.playbackRate).toBe(0.75);
  });

  it("holds the strip still while the other file loads", () => {
    const { media, engine, frames, seen, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    frames.flush();

    expect(media.currentTime).toBe(0); // the load algorithm reset it
    expect(seen.at(-1)).toBe(42);
  });

  it("keeps a paused song paused", () => {
    const { media, engine } = setup();
    media.loadMetadata(200);
    engine.seek(90);

    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(media.currentTime).toBe(90);
    expect(media.paused).toBe(true);
    expect(engine.getState().playing).toBe(false);
  });

  it("survives a second toggle before the first file has loaded", () => {
    const { media, engine, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.setSource("mix");
    media.loadMetadata(200);

    expect(media.src).toBe(MIX);
    expect(media.currentTime).toBe(42);
    expect(media.paused).toBe(false);
  });

  it("seeks within a file that is still loading", () => {
    const { media, engine } = playingAt(40);

    engine.setSource("guitar");
    engine.seek(10);
    media.loadMetadata(200);

    expect(media.currentTime).toBe(10);
  });

  it("draws the sought time, not the new file's zero, while it loads", () => {
    const { engine, frames, seen, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.seek(10);
    frames.flush();

    expect(seen.at(-1)).toBe(10);
    expect(engine.getState().time).toBe(10);
  });

  it("keeps the strip still through the events the element fires during the swap", () => {
    const { media, engine, frames, seen, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    media.emit("seeked"); // the element's time is 0 here, and the clock may now go backwards
    media.emit("timeupdate");
    frames.flush();

    expect(media.currentTime).toBe(0);
    expect(seen.at(-1)).toBe(42);
    expect(engine.getState().time).toBe(42);
  });

  it("keeps a seek made during one load through a toggle back", () => {
    const { media, engine, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.seek(10);
    engine.setSource("mix");
    media.loadMetadata(200);

    expect(media.src).toBe(MIX);
    expect(media.currentTime).toBe(10);
    expect(media.paused).toBe(false);
  });

  it("keeps a seek made during a load through a media error", () => {
    const { media, engine, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.seek(10);
    media.emit("error");
    media.loadMetadata(200);

    expect(media.loads.at(-1)).toBe(GUITAR);
    expect(media.currentTime).toBe(10);
    expect(media.paused).toBe(false);
  });

  it("stays paused when pause is pressed while the other file loads", () => {
    const { media, engine, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.pause();
    media.loadMetadata(200);

    expect(media.currentTime).toBe(42);
    expect(media.paused).toBe(true);
    expect(engine.getState().playing).toBe(false);
  });

  it("goes on drawing frames once the other file has loaded", () => {
    const { media, engine, frames } = playingAt(40);
    engine.setSource("guitar");
    frames.flush(); // a frame runs while the file loads, and does not ask for another
    frames.flush();
    expect(frames.pending).toBe(0);

    media.loadMetadata(200);

    expect(engine.getState().playing).toBe(true);
    expect(frames.pending).toBe(1);
  });

  it("does not throw when the browser refuses to resume", async () => {
    const { media, engine } = playingAt(40);
    engine.setSource("guitar");
    media.refusePlay = new Error("NotAllowedError");

    media.loadMetadata(200);
    await Promise.resolve();

    expect(engine.getState().playing).toBe(false);
  });
});

describe("expired audio URLs", () => {
  it("asks the api again on a media error, and resumes where it was", () => {
    const { media, engine, play } = playingAt(100);
    play(3);

    media.emit("error");

    expect(media.loads).toEqual([MIX, MIX]);
    media.loadMetadata(200);
    expect(media.currentTime).toBe(103);
    expect(media.paused).toBe(false);
    expect(engine.getState().error).toBeNull();
  });

  it(`gives up after ${MAX_FAILURES} failures in a row`, () => {
    const { media, engine } = playingAt(100);

    for (let i = 0; i < MAX_FAILURES; i++) media.emit("error");

    expect(media.loads).toHaveLength(MAX_FAILURES); // the first load, then two retries
    expect(engine.getState()).toMatchObject({ error: "connection_lost", playing: false });
    engine.play();
    expect(media.paused).toBe(true);
  });

  it("counts only consecutive failures", () => {
    const { media, engine } = playingAt(100);

    for (let i = 0; i < MAX_FAILURES * 2; i++) {
      media.emit("error");
      media.loadMetadata(200);
      media.advance(10); // recovered: playback went on past where it resumed
    }

    expect(engine.getState().error).toBeNull();
    expect(media.loads).toHaveLength(MAX_FAILURES * 2 + 1);
  });

  it("recovers from a single error long after the last one", () => {
    const { media, engine } = playingAt(100);

    media.emit("error");
    media.loadMetadata(200);
    media.advance(900); // a 15-minute session on the fresh URL
    media.emit("error"); // the next URL expires
    media.loadMetadata(200);

    expect(engine.getState().error).toBeNull();
    expect(media.loads).toEqual([MIX, MIX, MIX]);
    expect(media.currentTime).toBe(1000);
  });

  it("recovers each time inside a loop too short to get two seconds past the error", () => {
    const { media, engine, play } = playingAt(30);
    engine.setLoopPoint("a");
    engine.seek(31.5);
    engine.setLoopPoint("b");
    engine.seek(30);

    // Three URLs expire during one practice session on a 1.5 s loop.
    for (let expiry = 0; expiry < MAX_FAILURES; expiry++) {
      play(1);
      media.emit("error");
      media.loadMetadata(200);
      for (let pass = 0; pass < 6; pass++) play(0.5); // round the loop, never past B
    }

    expect(engine.getState().error).toBeNull();
    expect(media.currentTime).toBeGreaterThanOrEqual(30);
    expect(media.currentTime).toBeLessThan(31.5);
  });

  it("does not count a seek forwards as playback", () => {
    const { media, engine } = playingAt(100);

    for (let i = 0; i < MAX_FAILURES - 1; i++) {
      media.emit("error");
      media.loadMetadata(200);
      engine.seekBy(5); // the user skips ahead, and it fails again straight away
      media.advance(0.25);
    }
    media.emit("error");

    expect(engine.getState().error).toBe("connection_lost");
  });

  it("gives up on an error that comes back at the same place, however often it loads", () => {
    const { media, engine } = playingAt(100);

    // A truncated file: it loads fine, and fails again where it failed before.
    for (let i = 0; i < MAX_FAILURES - 1; i++) {
      media.emit("error");
      media.loadMetadata(200); // canplay fires, and does not count as recovery
      media.advance(0.25); // one timeupdate, hardly any playback
    }
    media.emit("error");

    expect(engine.getState().error).toBe("connection_lost");
    expect(media.loads).toHaveLength(MAX_FAILURES); // the first load, then two retries
    engine.play();
    expect(media.paused).toBe(true);
  });
});

describe("a file that will not play", () => {
  /** Three errors on the mix, as for a format the browser cannot decode. */
  function failedMix(at: number) {
    const fixture = playingAt(at);
    for (let i = 0; i < MAX_FAILURES; i++) fixture.media.emit("error");
    expect(fixture.engine.getState().error).toBe("connection_lost");
    return fixture;
  }

  it("can be left by choosing the other track", () => {
    const { media, engine } = failedMix(100);

    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(media.loads.at(-1)).toBe(GUITAR);
    expect(engine.getState()).toMatchObject({ source: "guitar", error: null });
    expect(media.currentTime).toBe(100);
  });

  it("plays the other track if the song was playing when the mix failed", () => {
    const { media, engine } = failedMix(100);
    expect(engine.getState().playing).toBe(false);

    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(engine.getState().playing).toBe(true);
    expect(media.paused).toBe(false);
  });

  it("leaves a song that was paused paused", () => {
    const { media, engine } = setup();
    media.loadMetadata(200);
    engine.seek(40);
    for (let i = 0; i < MAX_FAILURES; i++) media.emit("error");

    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(media.currentTime).toBe(40);
    expect(media.paused).toBe(true);
    expect(engine.getState().playing).toBe(false);
  });

  it("gives the other track a fresh count of failures", () => {
    const { media, engine } = failedMix(100);
    engine.setSource("guitar");

    media.emit("error");
    media.emit("error");

    expect(engine.getState().error).toBeNull();
    media.emit("error");
    expect(engine.getState().error).toBe("connection_lost");
  });

  it("keeps a seek made while it was retrying, once it gives up", () => {
    const { media, engine, frames, seen, play } = playingAt(100);
    play(3);
    media.emit("error");
    engine.seek(30);
    for (let i = 1; i < MAX_FAILURES; i++) media.emit("error");
    expect(engine.getState().error).toBe("connection_lost");

    frames.flush();

    expect(seen.at(-1)).toBe(30);
    expect(engine.getState().time).toBe(30);
    engine.setSource("guitar");
    media.loadMetadata(200);
    expect(media.currentTime).toBe(30);
  });

  it("can be sought while it has given up", () => {
    const { media, engine, frames, seen } = failedMix(100);

    engine.seek(60);
    frames.flush();
    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(seen.at(-1)).toBe(60);
    expect(media.currentTime).toBe(60);
  });

  it("holds the strip at the failing position until another track is chosen", () => {
    const { media, engine, frames, seen, play } = playingAt(100);
    play(3);
    for (let i = 0; i < MAX_FAILURES; i++) media.emit("error");

    frames.flush();

    expect(media.currentTime).toBe(0); // the failed load reset the element
    expect(seen.at(-1)).toBe(103);
    expect(engine.getState().playing).toBe(false);
  });
});

describe("the A/B loop", () => {
  function looping() {
    const fixture = playingAt(10);
    fixture.engine.setLoopPoint("a");
    fixture.engine.seek(20);
    fixture.engine.setLoopPoint("b");
    fixture.engine.seek(15);
    fixture.frames.flush();
    return fixture;
  }

  it("jumps back to A when playback crosses B", () => {
    const { media, engine, play } = looping();

    play(4.9);
    expect(media.currentTime).toBeCloseTo(19.9);
    play(0.2);

    expect(media.currentTime).toBe(10);
    expect(engine.getState().loop).toEqual({ a: 10, b: 20 });
  });

  it("holds from timeupdate alone, as in a background tab", () => {
    const { media } = looping();

    media.advance(5.1); // no animation frame runs

    expect(media.currentTime).toBe(10);
  });

  it("is released by seeking past B", () => {
    const { media, engine, play } = looping();

    engine.seek(25);
    play(1);

    expect(media.currentTime).toBe(26);
  });

  it("is entered by seeking before A and playing into it", () => {
    const { media, engine, play } = looping();

    engine.seek(5);
    for (let i = 0; i < 16; i++) play(1);

    expect(media.currentTime).toBeGreaterThanOrEqual(10);
    expect(media.currentTime).toBeLessThan(20);
  });

  it("refuses points less than half a second apart", () => {
    const { engine } = playingAt(10);
    engine.setLoopPoint("a");
    engine.seek(10.4);

    expect(engine.setLoopPoint("b")).toBe(false);
    expect(engine.getState().loop).toEqual({ a: 10, b: null });
  });

  it("accepts B before A, looping the span between them", () => {
    const { media, engine, play } = playingAt(20);
    engine.setLoopPoint("a");
    engine.seek(10);
    engine.setLoopPoint("b");

    for (let i = 0; i < 11; i++) play(1);

    expect(media.currentTime).toBeLessThan(20);
  });

  it("keeps looping when B is the very end of the song", () => {
    const { media, engine } = playingAt(190);
    engine.setLoopPoint("a");
    engine.seek(200);
    engine.setLoopPoint("b");
    engine.seek(195);

    media.end();

    expect(media.currentTime).toBe(190);
    expect(media.paused).toBe(false);
  });

  it("clears", () => {
    const { engine } = looping();

    engine.clearLoop();

    expect(engine.getState().loop).toEqual({ a: null, b: null });
  });
});

describe("the end, and frames", () => {
  it("pauses at the end, and plays again from zero", () => {
    const { media, engine } = playingAt(150);

    media.end();
    expect(engine.getState().playing).toBe(false);
    engine.play();

    expect(media.currentTime).toBe(0);
    expect(media.paused).toBe(false);
  });

  it("runs frames while playing and stops when paused", () => {
    const { engine, frames, play } = playingAt(0);
    play(1);
    expect(frames.pending).toBe(1);

    engine.pause();
    frames.flush();
    frames.flush();

    expect(frames.pending).toBe(0);
  });

  it("draws one frame after a seek while paused", () => {
    const { media, engine, frames, seen } = setup();
    media.loadMetadata(200);
    frames.flush();

    engine.seek(30);
    frames.flush();

    expect(seen.at(-1)).toBe(30);
    expect(frames.pending).toBe(0);
  });

  it("gives every frame listener the same time", () => {
    const { engine, frames, play } = playingAt(5);
    const other: number[] = [];
    engine.onFrame((t) => other.push(t));
    const seen: number[] = [];
    engine.onFrame((t) => seen.push(t));

    play(0.5);
    frames.flush();

    expect(seen).toEqual(other.slice(-seen.length));
  });

  it("updates the time readout about four times a second, not every frame", () => {
    const { engine, play } = playingAt(0);
    let updates = 0;
    engine.subscribe(() => updates++);

    for (let i = 0; i < 60; i++) play(1 / 60);

    expect(updates).toBeGreaterThanOrEqual(3);
    expect(updates).toBeLessThanOrEqual(5);
  });

  it("shows the exact time in the readout once paused", () => {
    const { engine, frames, play } = playingAt(64.8);
    play(0.22); // less than a readout step

    engine.pause();
    frames.flush();

    expect(engine.getState().time).toBeCloseTo(65.02);
  });

  it("lets go of the element when disposed", () => {
    const { media, engine, frames } = playingAt(5);

    engine.dispose();

    expect(media.paused).toBe(true);
    expect(media.listenerCount()).toBe(0);
    expect(frames.pending).toBe(0);
  });

  it("stops the download when disposed", () => {
    const { media, engine } = setup();
    expect(media.fetching).toBe(true);

    engine.dispose();

    expect(media.src).toBe("");
    expect(media.fetching).toBe(false);
  });

  it("asks only for metadata until it plays", () => {
    const { media } = setup();

    expect(media.preload).toBe("metadata");
  });
});
