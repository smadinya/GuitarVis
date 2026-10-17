/**
 * Where the camera sits: the two views' home poses, the double-click focus
 * pose, the pan clamp and the easing, as pure functions of the geometry. No
 * three.js: the Stage drives a `PerspectiveCamera` and its `OrbitControls`
 * from these numbers, and every rule worth testing about *where* the camera
 * goes is tested here.
 *
 * [spike.html](../../../docs/specs/008-3d-guitar/spike.html) is the reference
 * for every number.
 */
import type { Geometry, Vec3 } from "./geometry";

export type View = "2d" | "3d";

/** Where the camera is, and the point it looks at. */
export interface Pose {
  position: Vec3;
  target: Vec3;
}

/** The vertical field of view, in degrees. */
export const FOV = 22;
export const NEAR = 1;
export const FAR = 6000;
/** The 2D home pose leaves this fraction of room beyond the model. */
export const MARGIN = 0.04;
/** How close, and how far, the controls let the camera get from its target. */
export const MIN_DISTANCE = 35;
export const MAX_DISTANCE = 1800;
/** How far a double-click ends from the spot: in front of it in 2D, back
 * along the view in 3D. */
export const FOCUS_MM: Record<View, number> = { "2d": 260, "3d": 190 };
/** Every camera move the user did not drag takes this long. */
export const TRANSITION_MS = 700;
/** The panel's width over its height, until it is measured. Keep it equal to
 * the `aspect-ratio` of `.guitar` in `styles.css`. */
export const PANEL_ASPECT = 2.8;

/** The 3D home pose: low, in front, off the body end, looking up the neck. */
export const HOME_3D: Pose = {
  position: { x: -560, y: -150, z: 390 },
  target: { x: -110, y: 0, z: 0 },
};

const AHEAD: Vec3 = { x: 0, y: 0, z: 1 };

const copy = (p: Vec3): Vec3 => ({ x: p.x, y: p.y, z: p.z });
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** The pose a view opens on, and "Reset view" returns to. The 2D pose looks
 * straight at the fingerboard and fits the whole model, whatever the aspect. */
export function homePose(view: View, g: Geometry, aspect: number): Pose {
  if (view === "3d") return { position: copy(HOME_3D.position), target: copy(HOME_3D.target) };

  const { min, max } = g.bounds;
  const wide = Number.isFinite(aspect) && aspect > 0 ? aspect : PANEL_ASPECT;
  const tan = Math.tan((FOV / 2) * (Math.PI / 180));
  const x = (min.x + max.x) / 2;
  const y = (min.y + max.y) / 2;
  const distance = Math.max((max.x - min.x) / 2 / (tan * wide), (max.y - min.y) / 2 / tan) * (1 + MARGIN);
  return { position: { x, y, z: distance }, target: { x, y, z: 0 } };
}

/** Where a double-click ends: the spot, moved onto the fingerboard, with the
 * camera `FOCUS_MM` away from it. */
export function focusPose(view: View, hit: Vec3, current: Pose, g: Geometry): Pose {
  const x = clamp(hit.x, g.boardEnd, 0);
  const reach = g.halfWidth(x);
  const target: Vec3 = { x, y: clamp(hit.y, -reach, reach), z: 0 };

  let direction = AHEAD;
  if (view === "3d") {
    const back = {
      x: current.position.x - current.target.x,
      y: current.position.y - current.target.y,
      z: current.position.z - current.target.z,
    };
    const length = Math.hypot(back.x, back.y, back.z);
    if (Number.isFinite(length) && length > 0) {
      direction = { x: back.x / length, y: back.y / length, z: back.z / length };
    }
  }

  const away = FOCUS_MM[view];
  return {
    position: {
      x: target.x + away * direction.x,
      y: target.y + away * direction.y,
      z: target.z + away * direction.z,
    },
    target,
  };
}

/** A panned target, held within the model's bounds. */
export function clampTarget(target: Vec3, g: Geometry): Vec3 {
  const { min, max } = g.bounds;
  return {
    x: clamp(target.x, min.x, max.x),
    y: clamp(target.y, min.y, max.y),
    z: clamp(target.z, min.z, max.z),
  };
}

/** 0 to 1, slowly at each end. */
export function easeInOut(k: number): number {
  return k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
}

/** Each point of the pose `a`, `k` of the way to the pose `b`. */
export function between(a: Pose, b: Pose, k: number): Pose {
  const mix = (p: Vec3, q: Vec3): Vec3 => ({
    x: p.x * (1 - k) + q.x * k,
    y: p.y * (1 - k) + q.y * k,
    z: p.z * (1 - k) + q.z * k,
  });
  return { position: mix(a.position, b.position), target: mix(a.target, b.target) };
}
