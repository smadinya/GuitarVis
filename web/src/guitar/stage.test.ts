// @vitest-environment jsdom
import { MOUSE, type PerspectiveCamera, Vector3 } from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlaybackEngine } from "../playback/engine";
import { buildSong } from "../song";
import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { HOME_3D, homePose, type Pose, type View } from "./camera";
import { geometryOf } from "./geometry";
import { LOST_GRACE_MS, Stage } from "./stage";

const FIRST_SONG: TabDocument = firstSongJson;

/** Every box made, removed after each test. */
const boxes: HTMLElement[] = [];

/** Stands in for three's WebGLRenderer: jsdom has no WebGL. */
function fakeRenderer() {
  return { setPixelRatio: vi.fn(), setSize: vi.fn(), render: vi.fn(), dispose: vi.fn(), forceContextLoss: vi.fn() };
}

/** A Stage on a canvas inside a box, with a fake renderer. The engine's frames
 * and the stage's own are separate queues, both flushed by hand, and the
 * stage's wall clock moves only when the test says. The box has no size until
 * the test calls `resize`. */
function setUp({ view }: { view: View }) {
  const song = buildSong(FIRST_SONG);
  const engineFrames = new FakeFrames();
  const media = new FakeMedia();
  const engine = new PlaybackEngine({
    media,
    jobId: JOB_ID,
    duration: song.duration,
    requestFrame: engineFrames.request,
    cancelFrame: engineFrames.cancel,
  });
  const own = new FakeFrames();
  const renderer = fakeRenderer();
  const onLost = vi.fn();
  const onFailed = vi.fn();

  const box = document.createElement("div");
  const canvas = document.createElement("canvas");
  const overlay = document.createElement("div");
  box.append(canvas, overlay);
  document.body.append(box);
  boxes.push(box);

  // jsdom has no ResizeObserver. This one hands its callback to `resize`.
  let observed = () => {};
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        observed = callback;
      }
      observe() {}
      disconnect() {}
    },
  );

  let wall = 1000;
  const stage = new Stage({
    canvas,
    overlay,
    song,
    engine,
    renderer,
    view,
    onLost,
    onFailed,
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
  /** Lay the box out at `width` by `height` CSS pixels, and report it. */
  const resize = (width: number, height: number) => {
    Object.defineProperty(box, "clientWidth", { configurable: true, value: width });
    Object.defineProperty(box, "clientHeight", { configurable: true, value: height });
    observed();
  };
  /** The 2D home pose at the box's aspect `width / height`. */
  const home2d = (width: number, height: number) => homePose("2d", geometryOf(song), width / height);
  return {
    stage,
    canvas,
    overlay,
    own,
    engine,
    engineFrames,
    media,
    renderer,
    onLost,
    onFailed,
    tick,
    at,
    resize,
    home2d,
  };
}

/** The stage's camera and controls, which only a test reaches into. */
function insides(stage: Stage) {
  return stage as unknown as { camera: PerspectiveCamera; controls: OrbitControls };
}

/** The camera's pose now, copied. */
function poseOf(stage: Stage): Pose {
  const { camera, controls } = insides(stage);
  return { position: camera.position.clone(), target: controls.target.clone() };
}

type Modifiers = Pick<PointerEventInit, "shiftKey" | "ctrlKey" | "metaKey">;

/** A left-button mouse drag, 60 px to the right, as a browser sends it. jsdom
 * has no pointer capture and lays nothing out, and OrbitControls scales a pan
 * by the canvas's height, so the canvas gets both first. */
function drag(canvas: HTMLCanvasElement, modifiers: Modifiers) {
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();
  Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 300 });
  const send = (type: string, clientX: number, buttons: number) =>
    canvas.dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        pointerId: 1,
        pointerType: "mouse",
        isPrimary: true,
        button: 0,
        buttons,
        clientX,
        clientY: 100,
        ...modifiers,
      }),
    );
  send("pointerdown", 100, 1);
  send("pointermove", 160, 1);
  send("pointerup", 160, 0);
}

/** Every press that reaches the canvas, where OrbitControls listens. */
function pressesOn(canvas: HTMLCanvasElement): PointerEvent[] {
  const presses: PointerEvent[] = [];
  canvas.addEventListener("pointerdown", (event) => presses.push(event));
  return presses;
}

/** A matchMedia whose queries never match, and whose listeners the test fires. */
function stubMatchMedia() {
  const listeners = new Map<string, Set<() => void>>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    addEventListener(_type: string, listener: () => void) {
      listeners.set(query, (listeners.get(query) ?? new Set()).add(listener));
    },
    removeEventListener(_type: string, listener: () => void) {
      listeners.get(query)?.delete(listener);
    },
  }));
  return {
    fire(query: string) {
      for (const listener of [...(listeners.get(query) ?? [])]) listener();
    },
    count(query: string) {
      return listeners.get(query)?.size ?? 0;
    },
    total() {
      return [...listeners.values()].reduce((sum, set) => sum + set.size, 0);
    },
  };
}

/** Every DOM listener added from now on and not removed since. */
function liveListeners() {
  const live: Array<{ target: EventTarget; type: string; listener: unknown; capture: boolean }> = [];
  const captures = (options?: boolean | EventListenerOptions) =>
    typeof options === "boolean" ? options : options?.capture === true;
  const add = EventTarget.prototype.addEventListener;
  const remove = EventTarget.prototype.removeEventListener;
  vi.spyOn(EventTarget.prototype, "addEventListener").mockImplementation(function (
    this: EventTarget,
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ) {
    live.push({ target: this, type, listener, capture: captures(options) });
    add.call(this, type, listener, options);
  });
  vi.spyOn(EventTarget.prototype, "removeEventListener").mockImplementation(function (
    this: EventTarget,
    type: string,
    listener: EventListenerOrEventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ) {
    const i = live.findIndex(
      (l) => l.target === this && l.type === type && l.listener === listener && l.capture === captures(options),
    );
    if (i !== -1) live.splice(i, 1);
    remove.call(this, type, listener, options);
  });
  return live;
}

/** Fake only the timers. The stage's frames and clock are its own, injected. */
function fakeTimers() {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
}

function expectPose(stage: Stage, pose: Pose) {
  const now = poseOf(stage);
  for (const axis of ["x", "y", "z"] as const) {
    expect(now.position[axis]).toBeCloseTo(pose.position[axis], 3);
    expect(now.target[axis]).toBeCloseTo(pose.target[axis], 3);
  }
}

describe("Stage", () => {
  beforeEach(() => {
    // jsdom has no canvas: the painters fall back to blank textures.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  afterEach(() => {
    for (const box of boxes.splice(0)) box.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("pans on a drag with any mouse button in 2D, and never rotates", () => {
    const { stage } = setUp({ view: "2d" });
    const { controls } = insides(stage);

    expect(controls.enableRotate).toBe(false);
    expect(controls.mouseButtons.LEFT).toBe(MOUSE.PAN);
    expect(controls.mouseButtons.MIDDLE).toBe(MOUSE.PAN);
    expect(controls.mouseButtons.RIGHT).toBe(MOUSE.PAN);
    stage.dispose();
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
    const { stage, own, engine, media } = setUp({ view: "3d" });
    media.loadMetadata();

    engine.play();
    expect(engine.getState().playing).toBe(true);
    stage.setView("2d");

    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("draws its own frames while the audio loads, even with Play pressed", () => {
    const { stage, own, engine, renderer, tick } = setUp({ view: "3d" });

    engine.play(); // before the metadata: the engine emits no frames yet
    expect(engine.getState().playing).toBe(true);
    stage.setView("2d");

    expect(own.pending).toBe(1);
    const before = renderer.render.mock.calls.length;
    tick(16);
    expect(renderer.render.mock.calls.length).toBe(before + 1);
    stage.dispose();
  });

  it("draws once a frame when a seek lands during a camera move, in either order", () => {
    const { stage, overlay, own, engine, engineFrames, renderer, tick } = setUp({ view: "3d" });
    const renders = () => renderer.render.mock.calls.length;
    engineFrames.flush(); // at 0, with no message
    stage.setView("2d");
    tick(16);
    expect(own.pending).toBe(1); // the camera is still moving
    expect(overlay.hidden).toBe(true);

    // In one browser frame, the stage's own frame runs first, then the engine's.
    engine.seek(7); // in a hidden passage, where the overlay shows the chord
    let before = renders();
    tick(16);
    engineFrames.flush();
    expect(renders() - before).toBe(1);
    tick(16); // the next own frame draws at 7
    expect(overlay.hidden).toBe(false);

    // The engine's frame runs first, then the stage's own, which draws at 1.
    engine.seek(1);
    before = renders();
    engineFrames.flush();
    tick(16);
    expect(renders() - before).toBe(1);
    expect(overlay.hidden).toBe(true);
    stage.dispose();
  });

  it("hands its frames to the engine's when the song starts during a camera move", () => {
    const { stage, own, engine, engineFrames, media, renderer, tick } = setUp({ view: "3d" });
    const renders = () => renderer.render.mock.calls.length;
    media.loadMetadata();
    engineFrames.flush();
    stage.setView("2d");
    expect(own.pending).toBe(1);

    engine.play();
    const before = renders();
    engineFrames.flush(); // the engine's first frame, with the stage's own still pending
    tick(16);
    expect(renders() - before).toBe(1);
    expect(own.pending).toBe(0);

    engineFrames.flush();
    expect(renders() - before).toBe(2);
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

  it("drops a drag's leftover momentum before moving, so 2D arrives level and stays", () => {
    const { stage, own, tick, at } = setUp({ view: "3d" });
    const { controls, camera } = insides(stage);

    controls.rotateLeft(0.05); // a drag in 3D, released with momentum left
    stage.setView("2d");
    for (let i = 0; i < 8; i++) tick(100);
    at(1);
    for (let i = 0; i < 20; i++) tick(16);

    const looking = camera.getWorldDirection(new Vector3());
    expect(looking.x).toBeCloseTo(0, 6);
    expect(looking.y).toBeCloseTo(0, 6);
    expect(looking.z).toBeCloseTo(-1, 6);
    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("lands a reset after a pan on the home pose, and does not drift off it", () => {
    const { stage, canvas, own, tick, at } = setUp({ view: "3d" });
    const { controls, camera } = insides(stage);
    // OrbitControls scales a pan by the element's height, which jsdom gives as 0.
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 300 });

    controls.pan(60, 0); // a pan, released with momentum left
    stage.resetView();
    for (let i = 0; i < 8; i++) tick(100);
    at(1);
    for (let i = 0; i < 20; i++) tick(16);

    for (const axis of ["x", "y", "z"] as const) {
      expect(controls.target[axis]).toBeCloseTo(HOME_3D.target[axis], 3);
      expect(camera.position[axis]).toBeCloseTo(HOME_3D.position[axis], 3);
    }
    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("re-frames the home pose on a resize after a click that moved nothing", () => {
    const { stage, tick, resize, home2d } = setUp({ view: "2d" });
    const { controls } = insides(stage);
    resize(840, 300);
    tick(16);

    // OrbitControls sends `start` on any press, and `end` on its release.
    controls.dispatchEvent({ type: "start" });
    tick(16);
    controls.dispatchEvent({ type: "end" });
    resize(420, 300);

    expectPose(stage, home2d(420, 300));
    stage.dispose();
  });

  it("keeps the camera on a resize once a drag has moved it", () => {
    const { stage, canvas, tick, resize, home2d } = setUp({ view: "2d" });
    const { controls } = insides(stage);
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 300 });
    resize(840, 300);

    controls.dispatchEvent({ type: "start" });
    controls.pan(60, 0); // what a drag's move calls
    controls.dispatchEvent({ type: "end" });
    for (let i = 0; i < 60; i++) tick(16); // damping runs on after the release
    const kept = poseOf(stage);
    resize(420, 300);

    expectPose(stage, kept);
    expect(kept.position.z).not.toBeCloseTo(home2d(420, 300).position.z, 0);
    stage.dispose();
  });

  it("does not count the controls catching up with a reset as a move", () => {
    const { stage, canvas, own, tick, resize, home2d } = setUp({ view: "2d" });
    const { controls } = insides(stage);
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 300 });
    resize(840, 300);
    controls.pan(60, 0);
    stage.resetView();
    for (let i = 0; i < 8; i++) tick(100);
    // Landed, and the controls have not updated since: their next update()
    // reports the stage's move as a change.
    expect(own.pending).toBe(0);

    controls.dispatchEvent({ type: "start" });
    tick(16);
    controls.dispatchEvent({ type: "end" });
    resize(420, 300);

    expectPose(stage, home2d(420, 300));
    stage.dispose();
  });

  it("does not count a resize during a press as a move", () => {
    const { stage, tick, resize, home2d } = setUp({ view: "2d" });
    const { controls } = insides(stage);
    resize(840, 300);
    tick(16);

    controls.dispatchEvent({ type: "start" });
    resize(420, 300);
    tick(16);
    controls.dispatchEvent({ type: "end" });
    resize(560, 300);

    expectPose(stage, home2d(560, 300));
    stage.dispose();
  });

  it("lands a transition on the new aspect's home when the box resizes during it", () => {
    const { stage, canvas, own, tick, resize, home2d } = setUp({ view: "2d" });
    const { controls } = insides(stage);
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 300 });
    resize(840, 300);
    controls.pan(60, 0);

    stage.resetView();
    tick(100);
    tick(100);
    resize(420, 300);
    for (let i = 0; i < 8; i++) tick(100);

    expectPose(stage, home2d(420, 300));
    expect(own.pending).toBe(0);
    stage.dispose();
  });

  it("reads the pixel ratio again on every resize, up to 2", () => {
    vi.stubGlobal("devicePixelRatio", 1);
    const { stage, renderer, resize } = setUp({ view: "3d" });
    resize(840, 300);
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(1);

    vi.stubGlobal("devicePixelRatio", 1.5); // the browser zooms in
    resize(560, 200);
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(1.5);
    vi.stubGlobal("devicePixelRatio", 3);
    resize(280, 100);
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(2);
    stage.dispose();
  });

  it("follows a pixel ratio that changes with no resize, as on another monitor", () => {
    const media = stubMatchMedia();
    vi.stubGlobal("devicePixelRatio", 1);
    const { stage, renderer, resize } = setUp({ view: "3d" });
    resize(840, 300);

    vi.stubGlobal("devicePixelRatio", 1.5);
    media.fire("(resolution: 1dppx)");
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(1.5);
    expect(media.count("(resolution: 1dppx)")).toBe(0);
    vi.stubGlobal("devicePixelRatio", 3);
    media.fire("(resolution: 1.5dppx)");
    expect(renderer.setPixelRatio).toHaveBeenLastCalledWith(2);

    stage.dispose();
    expect(media.total()).toBe(0);
  });

  it("pans on a drag with shift, ctrl or meta held in 2D", () => {
    for (const modifier of ["shiftKey", "ctrlKey", "metaKey"] as const) {
      const { stage, canvas } = setUp({ view: "2d" });
      const { controls } = insides(stage);
      const presses = pressesOn(canvas);
      const before = controls.target.clone();

      drag(canvas, { [modifier]: true });

      expect(controls.target.distanceTo(before)).toBeGreaterThan(1);
      // The controls see one press, without the modifier.
      expect(presses).toHaveLength(1);
      expect(presses[0][modifier]).toBe(false);
      stage.dispose();
    }
  });

  it("leaves a shift-drag in 3D to the controls, which pan", () => {
    const { stage, canvas } = setUp({ view: "3d" });
    const { controls, camera } = insides(stage);
    const presses = pressesOn(canvas);
    const before = poseOf(stage);

    drag(canvas, { shiftKey: true });

    expect(controls.target.distanceTo(before.target)).toBeGreaterThan(1);
    // A pan moves the camera with the target: the view slides, not swings.
    const offset = camera.position.clone().sub(controls.target);
    const was = new Vector3().copy(before.position).sub(before.target);
    expect(offset.distanceTo(was)).toBeCloseTo(0, 6);
    expect(presses).toHaveLength(1);
    expect(presses[0].shiftKey).toBe(true);
    stage.dispose();
  });

  it("reports a lost context only once it has stayed lost for the grace, and its return after that", () => {
    fakeTimers();
    const { stage, canvas, own, onLost } = setUp({ view: "3d" });

    canvas.dispatchEvent(new Event("webglcontextlost"));
    vi.advanceTimersByTime(LOST_GRACE_MS - 1);
    expect(onLost).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onLost).toHaveBeenCalledTimes(1);
    expect(onLost).toHaveBeenLastCalledWith(true);

    expect(own.pending).toBe(0);
    canvas.dispatchEvent(new Event("webglcontextrestored"));
    expect(onLost).toHaveBeenCalledTimes(2);
    expect(onLost).toHaveBeenLastCalledWith(false);
    expect(own.pending).toBe(1); // and it draws again
    stage.dispose();
  });

  it("reports nothing for a context restored within the grace, and draws again", () => {
    fakeTimers();
    const { stage, canvas, own, onLost } = setUp({ view: "3d" });

    canvas.dispatchEvent(new Event("webglcontextlost"));
    vi.advanceTimersByTime(LOST_GRACE_MS / 2);
    canvas.dispatchEvent(new Event("webglcontextrestored"));
    vi.advanceTimersByTime(LOST_GRACE_MS * 2);

    expect(onLost).not.toHaveBeenCalled();
    expect(own.pending).toBe(1);
    stage.dispose();
  });

  it("reports no loss once disposed during the grace", () => {
    fakeTimers();
    const { stage, canvas, onLost } = setUp({ view: "3d" });

    canvas.dispatchEvent(new Event("webglcontextlost"));
    stage.dispose();
    vi.advanceTimersByTime(LOST_GRACE_MS * 2);

    expect(onLost).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops drawing once disposed", () => {
    const { stage, renderer, at } = setUp({ view: "3d" });

    stage.dispose();
    const calls = renderer.render.mock.calls.length;
    at(2);

    expect(renderer.render.mock.calls.length).toBe(calls);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
  });

  it("stops for good when a draw in an engine frame throws, and the engine's other views carry on", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const { stage, engine, renderer, onFailed, tick, at } = setUp({ view: "3d" });
    renderer.render.mockImplementation(() => {
      throw new Error("a bug in the draw");
    });
    const seen: number[] = [];
    engine.onFrame((t) => seen.push(t)); // after the stage's own listener

    at(1);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(seen.at(-1)).toBe(1);

    const renders = renderer.render.mock.calls.length;
    stage.setView("2d"); // a camera move, which would draw frames of its own
    tick(16);
    at(2);
    expect(renderer.render.mock.calls.length).toBe(renders);
    expect(seen.at(-1)).toBe(2);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(onFailed).toHaveBeenCalledTimes(1);
  });

  it("undoes what it set up when its constructor throws, and leaves the renderer to its owner", () => {
    const media = stubMatchMedia();
    let observing = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {
          observing += 1;
        }
        disconnect() {
          observing = 0;
        }
      },
    );
    const song = buildSong(FIRST_SONG);
    const engine = new PlaybackEngine({ media: new FakeMedia(), jobId: JOB_ID, duration: song.duration });
    // The constructor subscribes to the engine last, after everything else.
    vi.spyOn(engine, "onFrame").mockImplementation(() => {
      throw new Error("a bug in the Stage");
    });
    const box = document.createElement("div");
    const canvas = document.createElement("canvas");
    const overlay = document.createElement("div");
    box.append(canvas, overlay);
    document.body.append(box);
    boxes.push(box);
    const renderer = fakeRenderer();
    const live = liveListeners();

    expect(
      () =>
        new Stage({ canvas, overlay, song, engine, renderer, view: "3d", onLost: vi.fn(), onFailed: vi.fn() }),
    ).toThrow("a bug in the Stage");

    expect(live).toEqual([]);
    expect(media.total()).toBe(0);
    expect(observing).toBe(0);
    expect(renderer.dispose).not.toHaveBeenCalled();
    engine.dispose();
  });

  it("stops for good when a draw in its own frame throws", () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const { stage, own, renderer, onFailed, tick, at } = setUp({ view: "3d" });
    stage.setView("2d");
    expect(own.pending).toBe(1);
    renderer.render.mockImplementation(() => {
      throw new Error("a bug in the draw");
    });

    tick(16);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(own.pending).toBe(0);

    const renders = renderer.render.mock.calls.length;
    tick(16);
    at(2);
    expect(renderer.render.mock.calls.length).toBe(renders);
    expect(onFailed).toHaveBeenCalledTimes(1);
  });
});
