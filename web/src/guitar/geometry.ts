/**
 * Every dimension and position on the guitar, in millimetres, as a pure
 * function of the song. No three.js: the scene, the camera poses and the note
 * dots are all built from these numbers, and every rule worth testing about
 * where something sits is tested here.
 *
 * Axes as in the spec's *The model*: the nut is at x = 0 and the neck runs
 * toward -x, the headstock is at +x, the fingerboard faces +z, and the lowest
 * string is on top (+y). The fingerboard's top face is z = 0.
 * [spike.html](../../../docs/specs/008-3d-guitar/spike.html) is the reference
 * for every number.
 */
import { stringLabels } from "../labels";
import type { Song } from "../song";

/** Scale length: the nut to the twelfth wire is half of it. */
export const SCALE = 650;
/** How much wider than a real guitar everything is across the neck. Lengths
 * along the neck stay real. */
export const WIDE = 1.7;
/** The fewest frets a neck has. */
export const MIN_FRETS = 20;
/** How far the fingerboard runs past its last wire. */
export const BOARD_TAIL = 10;
/** Where an open string's mark sits, past the nut. */
export const OPEN_X = 12;
/** A dot's radius as a fraction of the gap between strings. */
export const DOT_FILL = 0.49;
/** How far a mark sits above its string. */
export const LIFT = 1;
export const INLAY_FRETS: readonly number[] = [3, 5, 7, 9, 12, 15, 17, 19, 21];

/** The headstock tilts back by this much. */
export const HEAD_TILT_DEG = 13;
/** Where the headstock's own frame sits in the world. */
export const HEAD_ORIGIN: Vec3 = { x: 5, y: 0, z: -3.5 };
/** The outline's far end along the headstock's x. */
export const HEAD_LENGTH = 192;
/** The headstock's back, with its bevel, below its face. */
export const HEAD_DEPTH = 14.2;

/** String radii, the lowest of six first. */
export const GAUGES: readonly number[] = [0.62, 0.52, 0.43, 0.36, 0.3, 0.26];
/** The tuner buttons' outer edge, from the centreline. */
export const REACH = WIDE * 64 + 7;

/** Head-local x of the nearest and the furthest tuner post from the nut. */
const POST_FROM = 50;
const POST_SPAN = 96;
/** Head-local y of a post is this far out, either side. */
const POST_OUT = WIDE * 33;
/** A post's top stands this far above the headstock's face. */
const POST_TOP = 10.5;

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Box {
  min: Vec3;
  max: Vec3;
}

export interface Tuner {
  string: number;
  /** +1 on the upper (+y) side of the headstock, -1 on the lower. */
  side: 1 | -1;
  /** Head-local, on the face. */
  post: Vec3;
  /** The post's top, in world coordinates. */
  top: Vec3;
}

export interface Mark {
  at: Vec3;
  r: number;
  open: boolean;
}

export interface Geometry {
  /** F: the number of frets, and of wires past the nut. */
  frets: number;
  /** The number of strings. */
  strings: number;
  labels: string[];
  /** F + 1 entries, the nut first. */
  wireX: number[];
  /** Where the fingerboard ends, past wire F. */
  boardEnd: number;
  /** 0 at the nut to 1 at the fingerboard's end. */
  along(x: number): number;
  /** The fingerboard's half-width. */
  halfWidth(x: number): number;
  /** String 0 is the lowest-pitched and sits on top. */
  stringY(string: number, x: number): number;
  /** The strings' height above the fingerboard. */
  stringZ(x: number): number;
  /** Where a note on this fret sits along the neck. */
  noteX(fret: number): number;
  mark(string: number, fret: number): Mark;
  inlays: Vec3[];
  /** By string. */
  tuners: Tuner[];
  /** By string. */
  gauges: number[];
  /** By string. */
  wound: boolean[];
  headToWorld(p: Vec3): Vec3;
  /** Everything a mark, a post top or an inlay can reach. */
  bounds: Box;
}

const THETA = (HEAD_TILT_DEG * Math.PI) / 180;
const COS = Math.cos(THETA);
const SIN = Math.sin(THETA);

/** Head-local to world: three's `rotation.y` by the tilt, then the origin. */
function headToWorld(p: Vec3): Vec3 {
  return {
    x: HEAD_ORIGIN.x + p.x * COS + p.z * SIN,
    y: HEAD_ORIGIN.y + p.y,
    z: HEAD_ORIGIN.z - p.x * SIN + p.z * COS,
  };
}

/** The wire n's x, for n from 0, the nut. Written to give +0 at the nut. */
function wire(n: number): number {
  return SCALE * (2 ** (-n / 12) - 1);
}

/** The number of frets: twenty, or the song's highest. */
function fretsOf(song: Song): number {
  return song.notes.reduce((most, note) => Math.max(most, note.fret), MIN_FRETS);
}

export function geometryOf(song: Song): Geometry {
  const frets = fretsOf(song);
  const n = song.tuning.length;
  const wireX = Array.from({ length: frets + 1 }, (_, i) => wire(i));
  const boardEnd = wireX[frets] - BOARD_TAIL;

  const along = (x: number) => Math.min(1, Math.max(0, x / boardEnd));
  const halfWidth = (x: number) => WIDE * (22 + 6.5 * along(x));
  /** From the centre to an outer string. */
  const spread = (x: number) => WIDE * (17.5 + 7 * along(x));
  const gap = (x: number) => (2 * spread(x)) / Math.max(1, n - 1);
  const stringY = (s: number, x: number) => (n > 1 ? spread(x) * (1 - (2 * s) / (n - 1)) : 0);
  const stringZ = (x: number) => 2.8 + 1.6 * along(x);
  const noteX = (fret: number) => (fret === 0 ? OPEN_X : (wireX[fret - 1] + wireX[fret]) / 2);

  const upper = Math.ceil(n / 2);
  const tuners: Tuner[] = Array.from({ length: n }, (_, s) => {
    const side = s < upper ? 1 : -1;
    const posts = side === 1 ? upper : n - upper;
    const i = side === 1 ? s : n - 1 - s;
    const x = POST_FROM + (posts > 1 ? (POST_SPAN * i) / (posts - 1) : 0);
    const y = side * POST_OUT;
    return { string: s, side, post: { x, y, z: 0 }, top: headToWorld({ x, y, z: POST_TOP }) };
  });

  function mark(s: number, fret: number): Mark {
    if (fret >= 1) {
      const x = noteX(fret);
      return {
        at: { x, y: stringY(s, x), z: stringZ(x) + LIFT },
        r: DOT_FILL * gap(x),
        open: false,
      };
    }
    // An open string is a ring on the string's way from the nut to its post.
    const { top } = tuners[s];
    const [y0, z0] = [stringY(s, 0), stringZ(0)];
    const t = OPEN_X / top.x;
    return {
      at: { x: OPEN_X, y: y0 + t * (top.y - y0), z: z0 + t * (top.z - z0) + LIFT },
      r: DOT_FILL * gap(0),
      open: true,
    };
  }

  const inlays: Vec3[] = INLAY_FRETS.filter((f) => f <= frets).flatMap((f) => {
    const x = noteX(f);
    return f === 12
      ? [
          { x, y: 0.6 * spread(x), z: 0.05 },
          { x, y: -0.6 * spread(x), z: 0.05 },
        ]
      : [{ x, y: 0, z: 0.05 }];
  });

  // Count from the highest string: the thinnest first, then up the gauges.
  const gauges = Array.from({ length: n }, (_, s) => {
    const fromTop = Math.min(n - 1 - s, GAUGES.length - 1);
    return GAUGES[GAUGES.length - 1 - fromTop];
  });

  const farEnd = (z: number) => headToWorld({ x: HEAD_LENGTH, y: 0, z });
  const bounds: Box = {
    min: { x: boardEnd, y: -REACH, z: farEnd(-HEAD_DEPTH).z },
    max: { x: farEnd(0).x, y: REACH, z: stringZ(boardEnd) + LIFT },
  };

  return {
    frets,
    strings: n,
    labels: stringLabels(song.tuning),
    wireX,
    boardEnd,
    along,
    halfWidth,
    stringY,
    stringZ,
    noteX,
    mark,
    inlays,
    tuners,
    gauges,
    wound: Array.from({ length: n }, (_, s) => s < n / 2),
    headToWorld,
    bounds,
  };
}
