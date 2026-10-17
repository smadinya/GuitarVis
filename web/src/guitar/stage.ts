/**
 * The guitar's renderer, camera, controls and frame loop, outside React.
 *
 * Each engine frame runs the spec's *Rendering* steps: what sounds now, the
 * dots for it, each string's swing, the overlay's text, and a draw. The engine
 * emits frames while the song plays. While paused, or while an audio source
 * loads even with Play pressed, it emits one after each change. The camera and
 * a dot's pulse need frames of their own then, so the stage requests them
 * itself, at the engine's last time, and stops once nothing moves. It never
 * calls `engine.redraw()`, which would make every view redraw.
 *
 * The two views share one camera and one `OrbitControls`; the view sets what
 * the controls may do. In 2D the stage also clears the modifiers from a mouse
 * press, so a shift-drag pans as any drag does. Every number about where the
 * camera goes is in camera.ts.
 */
import {
  Color,
  MOUSE,
  PerspectiveCamera,
  Raycaster,
  Scene,
  type Spherical,
  TOUCH,
  Vector2,
  type Vector3,
  type WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import {
  FAR,
  FOV,
  MAX_DISTANCE,
  MIN_DISTANCE,
  NEAR,
  PANEL_ASPECT,
  TRANSITION_MS,
  between,
  clampTarget,
  easeInOut,
  focusPose,
  homePose,
  type Pose,
  type View,
} from "./camera";
import { geometryOf, type Geometry, type Vec3 } from "./geometry";
import { buildModel, type Model } from "./model";
import { NoteLayer } from "./notes";
import { cursorsOf, sounding, type Cursors, type Message } from "./sounding";
import { dotPainter, paintText, readPalette, type Palette } from "./textures";
import { envelope, swing } from "./vibration";

/** What the stage needs of three's WebGLRenderer, so a test can stand in for it. */
export type Renderer = Pick<WebGLRenderer, "setPixelRatio" | "setSize" | "render" | "dispose">;

export interface StageOptions {
  canvas: HTMLCanvasElement;
  /** The message's DOM node, over the canvas. */
  overlay: HTMLElement;
  song: Song;
  engine: PlaybackEngine;
  renderer: Renderer;
  view: View;
  /** Called with true when the WebGL context is lost, and false once it is back. */
  onLost: (lost: boolean) => void;
  /** Wall-clock ms: performance.now(), injectable for tests. */
  now?: () => number;
  requestFrame?: (callback: () => void) => number;
  cancelFrame?: (id: number) => void;
}

/** A camera move the user did not drag. */
interface Tween {
  from: Pose;
  to: Pose;
  /** Wall-clock ms. */
  start: number;
}

/** Past this many device pixels per CSS pixel, the cost outruns the gain. */
const MAX_PIXEL_RATIO = 2;
/** Device pixels per CSS pixel now. Browser zoom changes it. */
const deviceRatio = () => window.devicePixelRatio || 1;
const DAMPING = 0.08;
/** OrbitControls' own test for a move: a squared distance, in mm². */
const EPS = 1e-6;
const DARK = "(prefers-color-scheme: dark)";
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/** What the controls may do in each view. 2D never tilts: a drag pans. */
const CONTROLS: Record<
  View,
  { rotate: boolean; mouse: OrbitControls["mouseButtons"]; touch: OrbitControls["touches"] }
> = {
  "2d": {
    rotate: false,
    mouse: { LEFT: MOUSE.PAN, MIDDLE: MOUSE.PAN, RIGHT: MOUSE.PAN },
    touch: { ONE: TOUCH.PAN, TWO: TOUCH.DOLLY_PAN },
  },
  "3d": {
    rotate: true,
    mouse: { LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN },
    touch: { ONE: TOUCH.ROTATE, TWO: TOUCH.DOLLY_PAN },
  },
};

/**
 * Drop the motion the controls still owe from a drag. OrbitControls keeps a
 * drag's momentum in private fields and spends it only in update(), which
 * the stage does not call while a tween runs: without this, the momentum
 * would be spent once the camera arrives, tilting 2D and sliding a reset or a
 * double-click off its pose.
 *
 * OrbitControls has no public way to do this. These are the fields update()
 * carries from one call to the next in three 0.186.1
 * (examples/jsm/controls/OrbitControls.js): the rotation and pan still owed,
 * and a zoom not yet applied (which update() already resets as it ends:
 * cleared here too, in case a gesture left one between calls). Recheck them
 * on a three upgrade. The momentum tests in stage.test.ts fail if the
 * rotation's or the pan's field moves.
 */
function stopMomentum(controls: OrbitControls): void {
  const owed = controls as unknown as {
    _sphericalDelta: Spherical;
    _panOffset: Vector3;
    _scale: number;
    _performCursorZoom: boolean;
  };
  owed._sphericalDelta.set(0, 0, 0);
  owed._panOffset.set(0, 0, 0);
  owed._scale = 1;
  owed._performCursorZoom = false;
}

/** Whether the camera is somewhere else in `b` than in `a`, beyond rounding. */
function apart(a: Pose, b: Pose): boolean {
  const far = (p: Vec3, q: Vec3) => (p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2 > EPS;
  return far(a.position, b.position) || far(a.target, b.target);
}

export class Stage {
  private readonly canvas: HTMLCanvasElement;
  private readonly overlay: HTMLElement;
  private readonly song: Song;
  private readonly engine: PlaybackEngine;
  private readonly renderer: Renderer;
  private readonly onLost: (lost: boolean) => void;
  private readonly now: () => number;
  private readonly requestFrame: (callback: () => void) => number;
  private readonly cancelFrame: (id: number) => void;

  private readonly g: Geometry;
  private readonly model: Model;
  private readonly scene = new Scene();
  private readonly notes: NoteLayer;
  private readonly cursors: Cursors;
  private readonly camera: PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly raycaster = new Raycaster();
  /** Undo every listener and observer the stage added. */
  private readonly unlisten: Array<() => void> = [];
  private readonly stop: () => void;

  private view: View;
  private palette: Palette;
  /** Reduced motion: no vibration, no pulse, and camera moves jump. */
  private still = false;
  /** Whether the user has moved the camera since it was last sent home. */
  private touched = false;
  /** Where the camera was as the user's gesture began, or null between gestures. */
  private gesture: Pose | null = null;
  private tween: Tween | null = null;
  /** The engine's last song time, which the stage's own frames draw at. */
  private t: number;
  /** The stage's own pending animation frame. */
  private frame: number | null = null;
  private disposed = false;
  /** What the overlay shows, so a frame writes to the DOM only what changed. */
  private readonly shown = { visible: false, text: "", chord: false, opacity: "" };

  constructor(options: StageOptions) {
    this.canvas = options.canvas;
    this.overlay = options.overlay;
    this.song = options.song;
    this.engine = options.engine;
    this.renderer = options.renderer;
    this.onLost = options.onLost;
    this.now = options.now ?? (() => performance.now());
    this.requestFrame = options.requestFrame ?? ((callback) => requestAnimationFrame(() => callback()));
    this.cancelFrame = options.cancelFrame ?? ((id) => cancelAnimationFrame(id));
    this.view = options.view;
    this.t = this.engine.getState().time;

    this.g = geometryOf(this.song);
    this.model = buildModel(this.g, paintText);
    this.scene.add(this.model.root);
    this.palette = readPalette(this.canvas);
    this.scene.background = new Color(this.palette.background);
    this.notes = new NoteLayer(this.scene, this.g, dotPainter(() => this.palette));
    this.cursors = cursorsOf(this.song);

    // The overlay may hold a previous stage's message: start it from what
    // `shown` says.
    this.overlay.hidden = true;
    this.overlay.textContent = "";
    this.overlay.className = "guitar-message";
    this.overlay.style.opacity = "";

    this.camera = new PerspectiveCamera(FOV, PANEL_ASPECT, NEAR, FAR);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = DAMPING;
    this.controls.zoomToCursor = true;
    this.controls.minDistance = MIN_DISTANCE;
    this.controls.maxDistance = MAX_DISTANCE;
    this.applyView();
    // After the controls, whose constructor points the camera at the origin.
    this.place(this.home());

    const box = this.canvas.parentElement;
    if (box !== null && typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => this.resize());
      observer.observe(box);
      this.unlisten.push(() => observer.disconnect());
    }
    this.resize();
    this.followRatio();
    this.still = this.watch(REDUCED_MOTION, (matches) => {
      this.still = matches;
      this.wake();
    });
    this.watch(DARK, () => this.recolour());

    if (box !== null) this.listen(box, "pointerdown", (event) => this.unmodify(event as PointerEvent), true);
    this.listen(this.canvas, "dblclick", (event) => this.focus(event as MouseEvent));
    this.listen(this.canvas, "webglcontextlost", () => this.onLost(true));
    this.listen(this.canvas, "webglcontextrestored", () => {
      this.onLost(false);
      this.wake();
    });

    // OrbitControls sends `start` on any press or wheel, moving or not, so a
    // gesture touches the camera only once the camera leaves where the gesture
    // began. A `change` alone is not enough. One comes while damping runs on
    // after a release, and one when update() catches up with a pose the stage
    // placed, which a click's own frames can bring.
    const onStart = () => {
      this.gesture = this.pose();
      this.tween = null;
      this.wake();
    };
    const onChange = () => {
      if (this.gesture !== null && apart(this.gesture, this.pose())) this.touched = true;
      this.wake();
    };
    const onEnd = () => {
      this.gesture = null;
    };
    this.controls.addEventListener("start", onStart);
    this.controls.addEventListener("change", onChange);
    this.controls.addEventListener("end", onEnd);
    this.unlisten.push(() => {
      this.controls.removeEventListener("start", onStart);
      this.controls.removeEventListener("change", onChange);
      this.controls.removeEventListener("end", onEnd);
    });

    this.stop = this.engine.onFrame((t) => {
      this.t = t;
      if (this.draw(t)) this.wake();
    });
  }

  /** Switch views, and move to the new view's home. */
  setView(view: View): void {
    if (this.disposed || view === this.view) return;
    this.view = view;
    this.applyView();
    this.touched = false;
    this.goTo(this.home());
  }

  /** Move to the current view's home. */
  resetView(): void {
    if (this.disposed) return;
    this.touched = false;
    this.goTo(this.home());
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
    if (this.frame !== null) this.cancelFrame(this.frame);
    this.frame = null;
    for (const unlisten of this.unlisten.splice(0)) unlisten();
    this.controls.dispose();
    // Disconnecting leaves an inline `cursor: auto`, which would beat the
    // stylesheet's grab for the next stage on this canvas.
    this.canvas.style.removeProperty("cursor");
    this.notes.dispose();
    this.model.dispose();
    this.renderer.dispose();
  }

  /** One frame at song time `t`. Returns whether anything is still moving. */
  private draw(t: number): boolean {
    const now = this.now();
    const moving = this.stepCamera(now);
    const { notes, message } = sounding(this.song, this.cursors, t);
    const pulsing = this.notes.apply(notes, now, !this.still);
    const byString = new Map(notes.map((note) => [note.string, note]));
    this.model.strings.forEach((string, s) => {
      const note = byString.get(s);
      const a = note === undefined || this.still ? 0 : envelope(note, t);
      string.shape(a, note === undefined ? 0 : swing(note, t), note?.opacity ?? 1);
    });
    this.show(message);
    this.renderer.render(this.scene, this.camera);
    return moving || pulsing;
  }

  /** Ask for one frame of the stage's own. While the engine emits frames it
   * draws every one, so then there is no need. */
  private wake(): void {
    if (this.disposed || this.frame !== null || this.engine.emittingFrames()) return;
    this.frame = this.requestFrame(() => {
      this.frame = null;
      if (this.draw(this.t)) this.wake();
    });
  }

  /** Move the camera for this frame. Returns whether it is still moving. */
  private stepCamera(now: number): boolean {
    const tween = this.tween;
    if (tween !== null) {
      const k = this.still ? 1 : Math.min(1, Math.max(0, (now - tween.start) / TRANSITION_MS));
      this.place(between(tween.from, tween.to, easeInOut(k)));
      if (k < 1) return true;
      this.tween = null;
      return false;
    }

    const moved = this.controls.update();
    // Panning keeps the target over the model. The camera moves with it, so
    // the view slides rather than swings.
    const { target } = this.controls;
    const held = clampTarget(target, this.g);
    const dx = held.x - target.x;
    const dy = held.y - target.y;
    const dz = held.z - target.z;
    if (dx !== 0 || dy !== 0 || dz !== 0) {
      target.set(held.x, held.y, held.z);
      this.camera.position.set(this.camera.position.x + dx, this.camera.position.y + dy, this.camera.position.z + dz);
    }
    return moved;
  }

  /** Animate to `pose`: over TRANSITION_MS, or at once under reduced motion. */
  private goTo(pose: Pose): void {
    stopMomentum(this.controls);
    this.tween = { from: this.pose(), to: pose, start: this.now() };
    this.wake();
  }

  private home(): Pose {
    return homePose(this.view, this.g, this.camera.aspect);
  }

  private pose(): Pose {
    const { position } = this.camera;
    const { target } = this.controls;
    return {
      position: { x: position.x, y: position.y, z: position.z },
      target: { x: target.x, y: target.y, z: target.z },
    };
  }

  private place({ position, target }: Pose): void {
    this.camera.position.set(position.x, position.y, position.z);
    this.controls.target.set(target.x, target.y, target.z);
    this.camera.lookAt(this.controls.target);
    // The stage's move is not the user's, even during a gesture.
    if (this.gesture !== null) this.gesture = this.pose();
  }

  private applyView(): void {
    const { rotate, mouse, touch } = CONTROLS[this.view];
    this.controls.enableRotate = rotate;
    this.controls.mouseButtons = { ...mouse };
    this.controls.touches = { ...touch };
  }

  /** A double-click on the neck moves the camera to that spot. */
  private focus(event: MouseEvent): void {
    const box = this.canvas.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return;
    const ndc = new Vector2(
      ((event.clientX - box.left) / box.width) * 2 - 1,
      -((event.clientY - box.top) / box.height) * 2 + 1,
    );
    // The camera may have moved since the last draw updated its matrix.
    this.camera.updateMatrixWorld();
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.model.pickable, false)[0];
    if (hit === undefined) return;
    this.touched = true;
    this.goTo(focusPose(this.view, hit.point, this.pose(), this.g));
  }

  /**
   * In 2D, a mouse drag with shift, ctrl or meta held pans like any other.
   * OrbitControls would make the press a rotation, which 2D turns off. So the
   * press stops here, and a copy without the modifiers goes to the canvas in
   * its place; this listener lets the copy through. The drag's moves and its
   * release reach the controls unchanged.
   */
  private unmodify(event: PointerEvent): void {
    if (this.view !== "2d" || event.pointerType !== "mouse" || event.target !== this.canvas) return;
    if (!event.shiftKey && !event.ctrlKey && !event.metaKey) return;
    event.stopPropagation();
    this.canvas.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerId: event.pointerId,
        pointerType: event.pointerType,
        isPrimary: event.isPrimary,
        button: event.button,
        buttons: event.buttons,
        clientX: event.clientX,
        clientY: event.clientY,
        screenX: event.screenX,
        screenY: event.screenY,
        pressure: event.pressure,
        altKey: event.altKey,
      }),
    );
  }

  /** Until the user moves the camera, a resize re-frames the home pose. A
   * transition under way is then heading home (a double-click's marks the
   * camera touched), so it heads for the new home instead. */
  private resize(): void {
    const box = this.canvas.parentElement;
    if (box === null) return;
    const width = box.clientWidth;
    const height = box.clientHeight;
    if (width === 0 || height === 0) return;
    this.renderer.setPixelRatio(Math.min(deviceRatio(), MAX_PIXEL_RATIO));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (!this.touched) {
      if (this.tween !== null) this.tween.to = this.home();
      else this.place(this.home());
    }
    this.wake();
  }

  private recolour(): void {
    this.palette = readPalette(this.canvas);
    this.scene.background = new Color(this.palette.background);
    this.notes.repaint();
    this.wake();
  }

  /** Set the overlay's message, touching the DOM only for what changed. */
  private show(message: Message | null): void {
    const { overlay, shown } = this;
    const visible = message !== null;
    if (visible !== shown.visible) {
      overlay.hidden = !visible;
      shown.visible = visible;
    }
    if (message === null) return;
    if (message.text !== shown.text) {
      overlay.textContent = message.text;
      shown.text = message.text;
    }
    if (message.chord !== shown.chord) {
      overlay.className = message.chord ? "guitar-message chord" : "guitar-message";
      shown.chord = message.chord;
    }
    const opacity = String(message.opacity);
    if (opacity !== shown.opacity) {
      overlay.style.opacity = opacity;
      shown.opacity = opacity;
    }
  }

  /** Resize when the pixel ratio changes with no change of size, as when the
   * window moves to another monitor. A query matches one ratio, so each change
   * sets up the query for the new ratio. */
  private followRatio(): void {
    if (typeof matchMedia !== "function") return;
    let stop = () => {};
    const follow = () => {
      const list = matchMedia(`(resolution: ${deviceRatio()}dppx)`);
      const listener = () => {
        stop();
        follow();
        this.resize();
      };
      list.addEventListener("change", listener);
      stop = () => list.removeEventListener("change", listener);
    };
    follow();
    this.unlisten.push(() => stop());
  }

  /** Follow a media query, if the browser has them. Returns whether it matches now. */
  private watch(query: string, onChange: (matches: boolean) => void): boolean {
    if (typeof matchMedia !== "function") return false;
    const list = matchMedia(query);
    const listener = () => onChange(list.matches);
    list.addEventListener("change", listener);
    this.unlisten.push(() => list.removeEventListener("change", listener));
    return list.matches;
  }

  private listen(target: EventTarget, type: string, listener: (event: Event) => void, capture = false): void {
    target.addEventListener(type, listener, capture);
    this.unlisten.push(() => target.removeEventListener(type, listener, capture));
  }
}
