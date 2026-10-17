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
import { Stage } from "./stage";

const FIRST_SONG: TabDocument = firstSongJson;

/** Every box made, removed after each test. */
const boxes: HTMLElement[] = [];

/** A Stage on a canvas inside a box, with a fake renderer. The engine's frames
 * and the stage's own are separate queues, both flushed by hand, and the
 * stage's wall clock moves only when the test says. The box has no size until
 * the test calls `resize`. */
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
  /** Lay the box out at `width` by `height` CSS pixels, and report it. */
  const resize = (width: number, height: number) => {
    Object.defineProperty(box, "clientWidth", { configurable: true, value: width });
    Object.defineProperty(box, "clientHeight", { configurable: true, value: height });
    observed();
  };
  /** The 2D home pose at the box's aspect `width / height`. */
  const home2d = (width: number, height: number) => homePose("2d", geometryOf(song), width / height);
  return { stage, canvas, own, engine, renderer, tick, at, resize, home2d };
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

  it("stops drawing once disposed", () => {
    const { stage, renderer, at } = setUp({ view: "3d" });

    stage.dispose();
    const calls = renderer.render.mock.calls.length;
    at(2);

    expect(renderer.render.mock.calls.length).toBe(calls);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
  });
});
