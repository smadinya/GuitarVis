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
      media.loadMetadata(200); // recovered: canplay resets the count
    }

    expect(engine.getState().error).toBeNull();
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
    const { engine, frames, seen } = setup();
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

  it("lets go of the element when disposed", () => {
    const { media, engine, frames } = playingAt(5);

    engine.dispose();

    expect(media.paused).toBe(true);
    expect(media.listenerCount()).toBe(0);
    expect(frames.pending).toBe(0);
  });
});
