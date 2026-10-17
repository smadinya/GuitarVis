// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybackEngine } from "../playback/engine";
import { buildSong } from "../song";
import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import type { View } from "./camera";
import { Stage } from "./stage";

const FIRST_SONG: TabDocument = firstSongJson;

/** Every box made, removed after each test. */
const boxes: HTMLElement[] = [];

/** A Stage on a canvas inside a box, with a fake renderer. The engine's frames
 * and the stage's own are separate queues, both flushed by hand, and the
 * stage's wall clock moves only when the test says. */
function setUp({ view }: { view: View }) {
  const song = buildSong(FIRST_SONG);
  const engineFrames = new FakeFrames();
  const engine = new PlaybackEngine({
    media: new FakeMedia(),
    jobId: JOB_ID,
    duration: song.duration,
    requestFrame: engineFrames.request,
    cancelFrame: engineFrames.cancel,
  });
  const own = new FakeFrames();
  const renderer = { setPixelRatio: vi.fn(), setSize: vi.fn(), render: vi.fn(), dispose: vi.fn() };

  const box = document.createElement("div");
  const canvas = document.createElement("canvas");
  const overlay = document.createElement("div");
  box.append(canvas, overlay);
  document.body.append(box);
  boxes.push(box);

  let wall = 1000;
  const stage = new Stage({
    canvas,
    overlay,
    song,
    engine,
    renderer,
    view,
    onLost: () => {},
    now: () => wall,
    requestFrame: own.request,
    cancelFrame: own.cancel,
  });

  /** Let `ms` of wall-clock time pass, and run the stage's own frames. */
  const tick = (ms: number) => {
    wall += ms;
    own.flush();
  };
  /** Move the song to `t` and run the engine's frames. */
  const at = (t: number) => {
    engine.seek(t);
    engineFrames.flush();
  };
  return { stage, own, engine, renderer, tick, at };
}

describe("Stage", () => {
  beforeEach(() => {
    // jsdom has no canvas: the painters fall back to blank textures.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  afterEach(() => {
    for (const box of boxes.splice(0)) box.remove();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("draws its own frames while the camera moves, and stops once it arrives", () => {
    const { stage, own, renderer, tick } = setUp({ view: "3d" }); // the engine is paused
    const before = renderer.render.mock.calls.length;

    stage.setView("2d");
    expect(own.pending).toBe(1);
    for (let i = 0; i < 10; i++) tick(100);

    expect(own.pending).toBe(0);
    expect(renderer.render.mock.calls.length - before).toBeGreaterThanOrEqual(7);
    stage.dispose();
  });

  it("leaves the drawing to the engine's frames while the song plays", () => {
    const { stage, own, engine } = setUp({ view: "3d" });

    engine.play();
    expect(engine.getState().playing).toBe(true);
    stage.setView("2d");

    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("jumps instead of animating under reduced motion", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
      addEventListener() {},
      removeEventListener() {},
    }));
    const { stage, own, tick } = setUp({ view: "3d" });

    stage.setView("2d");
    tick(16);

    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("stops drawing once disposed", () => {
    const { stage, renderer, at } = setUp({ view: "3d" });

    stage.dispose();
    const calls = renderer.render.mock.calls.length;
    at(2);

    expect(renderer.render.mock.calls.length).toBe(calls);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
  });
});
