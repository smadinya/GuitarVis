/**
 * The guitar's scene graph, built from a `Geometry`: rosewood board, maple
 * neck, nickel frets, a bone nut, a dark headstock tilted back with its
 * tuners, wound and plain strings, and the text that names them. Ported from
 * [spike.html](../../../docs/specs/008-3d-guitar/spike.html), which is the
 * reference for every colour and every shape; the positions come from
 * geometry.ts.
 *
 * Nothing here needs WebGL, so it builds on `node`. Text is drawn by an
 * injected painter: a canvas in the browser, a blank texture in a test.
 */
import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  CircleGeometry,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  ExtrudeGeometry,
  Group,
  HemisphereLight,
  type Material,
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  type MeshStandardMaterialParameters,
  type Object3D,
  PlaneGeometry,
  Shape,
  SphereGeometry,
  type Texture,
  Vector3,
} from "three";

import { HEAD_ORIGIN, HEAD_TILT_DEG, WIDE, type Geometry, type Vec3 } from "./geometry";
import { BLUR_OPACITY, STILL_MM, profile } from "./vibration";

/** Draws a line of text as a texture; `aspect` is its width over its height. */
export type TextPainter = (text: string, colour: string) => { texture: Texture; aspect: number };

/** A string's tube is this many segments long, from the nut to the board's end... */
export const SEGMENTS = 160;
/** ...and this many sided. */
export const SIDES = 6;
/** A string's name at its tuner is this tall, in mm. */
export const LABEL_MM = 9;
/** A fret's number below the neck is this tall, in mm. */
export const NUMBER_MM = 7;
/** The gap between the fingerboard's edge and a fret's number, in mm. */
export const NUMBER_GAP = 5;
/** A label sits this far past its tuner's post, along the headstock, in mm. */
export const LABEL_PAST_POST = 11;
export const LABEL_COLOUR = "#f4efe2";
/** A grey that reads on both themes' backgrounds. */
export const NUMBER_COLOUR = "#8a8478";

/** A string's colour, and its blur's. */
const WOUND = 0xd8b04e;
const PLAIN = 0xf2f2f2;

const RING_COS = Array.from({ length: SIDES }, (_, k) => Math.cos((2 * Math.PI * k) / SIDES));
const RING_SIN = Array.from({ length: SIDES }, (_, k) => Math.sin((2 * Math.PI * k) / SIDES));

/**
 * The part of a string over the fingerboard: a tube we reshape in place so it
 * can vibrate, and a translucent ribbon around it, the blur a moving string
 * leaves on the eye. `u` runs from 0 at the nut to 1 at the board's end.
 */
export class VibratingString {
  readonly tube: Mesh;
  readonly blur: Mesh;
  private readonly nut: Vec3;
  private readonly end: Vec3;
  private readonly radius: number;
  private readonly tubePosition: BufferAttribute;
  private readonly blurPosition: BufferAttribute;
  private readonly blurMaterial: MeshBasicMaterial;
  /** True once it has been drawn at rest, until the next time it moves. */
  private still = false;

  constructor(nut: Vec3, end: Vec3, radius: number, material: Material, blurColour: number) {
    this.nut = nut;
    this.end = end;
    this.radius = radius;

    const rings = SEGMENTS + 1;
    const tube = new BufferGeometry();
    const normals = new Float32Array(rings * SIDES * 3);
    const index: number[] = [];
    for (let i = 0; i < rings; i++) {
      for (let k = 0; k < SIDES; k++) {
        const o = (i * SIDES + k) * 3;
        normals[o + 1] = RING_COS[k];
        normals[o + 2] = RING_SIN[k];
        if (i < SEGMENTS) {
          const p = i * SIDES + k;
          const q = i * SIDES + ((k + 1) % SIDES);
          index.push(p, p + SIDES, q, q, p + SIDES, q + SIDES);
        }
      }
    }
    this.tubePosition = new BufferAttribute(new Float32Array(rings * SIDES * 3), 3);
    tube.setIndex(index);
    tube.setAttribute("position", this.tubePosition);
    tube.setAttribute("normal", new BufferAttribute(normals, 3));
    this.tube = new Mesh(tube, material);
    this.tube.name = "string";
    this.tube.frustumCulled = false;

    const ribbon = new BufferGeometry();
    const ribbonIndex: number[] = [];
    for (let i = 0; i < SEGMENTS; i++) ribbonIndex.push(2 * i, 2 * i + 2, 2 * i + 1, 2 * i + 1, 2 * i + 2, 2 * i + 3);
    this.blurPosition = new BufferAttribute(new Float32Array(rings * 2 * 3), 3);
    ribbon.setIndex(ribbonIndex);
    ribbon.setAttribute("position", this.blurPosition);
    this.blurMaterial = new MeshBasicMaterial({
      color: blurColour,
      transparent: true,
      opacity: BLUR_OPACITY,
      depthWrite: false,
      side: DoubleSide,
    });
    this.blur = new Mesh(ribbon, this.blurMaterial);
    this.blur.name = "string-blur";
    this.blur.frustumCulled = false;
    this.blur.renderOrder = 1;

    this.shape(0, 0, 0);
  }

  /**
   * Draw the string for one instant. `amplitude` is the swing's size in mm and
   * `swing` the waveform's value, sin(2πf(t − onset)), from -1 to 1; `opacity`
   * is the string's emphasis, which the blur follows. The blur is there only
   * while the string visibly moves.
   */
  shape(amplitude: number, swing: number, opacity: number): void {
    if (amplitude === 0 && this.still) return;
    this.still = amplitude === 0;

    const { nut, end, radius } = this;
    const tube = this.tubePosition.array as Float32Array;
    const blur = this.blurPosition.array as Float32Array;
    for (let i = 0; i <= SEGMENTS; i++) {
      const u = i / SEGMENTS;
      const x = nut.x + (end.x - nut.x) * u;
      const y = nut.y + (end.y - nut.y) * u;
      const z = nut.z + (end.z - nut.z) * u;
      const reach = amplitude * profile(u);
      const dy = reach * swing;
      for (let k = 0; k < SIDES; k++) {
        const o = (i * SIDES + k) * 3;
        tube[o] = x;
        tube[o + 1] = y + dy + RING_COS[k] * radius;
        tube[o + 2] = z + RING_SIN[k] * radius;
      }
      const o = i * 6;
      const half = reach + radius;
      blur[o] = x;
      blur[o + 1] = y - half;
      blur[o + 2] = z - 0.2;
      blur[o + 3] = x;
      blur[o + 4] = y + half;
      blur[o + 5] = z - 0.2;
    }
    this.tubePosition.needsUpdate = true;
    this.blurPosition.needsUpdate = true;
    this.blur.visible = amplitude > STILL_MM;
    this.blurMaterial.opacity = BLUR_OPACITY * opacity;
  }
}

export interface Model {
  root: Group;
  /** What a double-click can land on: the fingerboard and the neck's back. */
  pickable: Object3D[];
  /** By string. */
  strings: VibratingString[];
  /** Frees every geometry, material and texture the model made. */
  dispose(): void;
}

/** A cylinder from `a` to `b`, open-ended. */
function rod(a: Vector3, b: Vector3, radius: number, material: Material): Mesh {
  const d = new Vector3().subVectors(b, a);
  const mesh = new Mesh(new CylinderGeometry(radius, radius, d.length(), 8, 1, true), material);
  mesh.position.copy(a).addScaledVector(d, 0.5);
  mesh.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), d.clone().normalize());
  return mesh;
}

const toVector = (p: Vec3) => new Vector3(p.x, p.y, p.z);

const standard = (color: number, rest: MeshStandardMaterialParameters) => new MeshStandardMaterial({ color, ...rest });

export function buildModel(g: Geometry, paintText: TextPainter): Model {
  const root = new Group();
  const textures: Texture[] = [];

  root.add(new HemisphereLight(0xffffff, 0x8a7a66, 1.3));
  const sun = new DirectionalLight(0xffffff, 1.7);
  sun.position.set(-150, 250, 500);
  root.add(sun);
  const rim = new DirectionalLight(0xffffff, 0.6);
  rim.position.set(300, -200, -300);
  root.add(rim);

  const mat = {
    board: standard(0x5b3524, { roughness: 0.8 }),
    neck: standard(0xdcb684, { roughness: 0.5, side: DoubleSide }),
    fret: standard(0xe9e9e9, { metalness: 0.25, roughness: 0.3 }),
    nut: standard(0xf4efe2, { roughness: 0.4 }),
    inlay: standard(0xf6f3ec, { roughness: 0.3 }),
    head: standard(0x2a1b13, { roughness: 0.3 }),
    chrome: standard(0xdedede, { metalness: 0.3, roughness: 0.25 }),
    button: standard(0xf3ecdc, { roughness: 0.35 }),
  };

  /** A plane of text, facing +z, `height` tall. */
  function text(label: string, colour: string, height: number, name: string): Mesh {
    const { texture, aspect } = paintText(label, colour);
    textures.push(texture);
    const material = new MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false });
    const mesh = new Mesh(new PlaneGeometry(height * aspect, height), material);
    mesh.name = name;
    return mesh;
  }

  const length = -g.boardEnd;

  // Fingerboard: a box, tapered. Its top face is z = 0.
  const boardGeo = new BoxGeometry(length, 2, 6, 40, 1, 1);
  boardGeo.translate(-length / 2, 0, -3);
  const boardPosition = boardGeo.attributes.position;
  for (let k = 0; k < boardPosition.count; k++) {
    boardPosition.setY(k, boardPosition.getY(k) * g.halfWidth(boardPosition.getX(k)));
  }
  boardGeo.computeVertexNormals();
  const board = new Mesh(boardGeo, mat.board);
  board.name = "board";
  root.add(board);

  // Neck back: half a tapered cylinder behind the fingerboard.
  const neckGeo = new CylinderGeometry(
    g.halfWidth(g.boardEnd) + 1,
    g.halfWidth(0) + 1,
    length + 5,
    48,
    1,
    false,
    Math.PI / 2,
    Math.PI,
  );
  neckGeo.rotateZ(Math.PI / 2);
  neckGeo.scale(1, 1, 0.9 / WIDE);
  neckGeo.translate((5 - length) / 2, 0, -6);
  const neck = new Mesh(neckGeo, mat.neck);
  neck.name = "neck";
  root.add(neck);

  // Frets, nut, inlays.
  for (let n = 1; n <= g.frets; n++) {
    const x = g.wireX[n];
    const wire = new Mesh(new BoxGeometry(2.2, 2 * g.halfWidth(x) - 0.6, 2.4), mat.fret);
    wire.name = "wire";
    wire.position.set(x, 0, 0);
    root.add(wire);
  }
  const nut = new Mesh(new BoxGeometry(5, 2 * g.halfWidth(0) + 1, 9), mat.nut);
  nut.name = "nut";
  nut.position.set(2.5, 0, -1.5);
  root.add(nut);
  const inlayGeo = new CircleGeometry(3.6, 32);
  for (const at of g.inlays) {
    const inlay = new Mesh(inlayGeo, mat.inlay);
    inlay.name = "inlay";
    inlay.position.set(at.x, at.y, at.z);
    root.add(inlay);
  }

  // Fret numbers, under the neck.
  for (let n = 1; n <= g.frets; n++) {
    const x = g.noteX(n);
    const number = text(String(n), NUMBER_COLOUR, NUMBER_MM, "fret-number");
    number.position.set(x, -(g.halfWidth(x) + NUMBER_GAP + NUMBER_MM / 2), 0);
    root.add(number);
  }

  // Headstock, tilted back, its tuners split between the two sides.
  const head = new Group();
  head.name = "headstock";
  head.position.set(HEAD_ORIGIN.x, HEAD_ORIGIN.y, HEAD_ORIGIN.z);
  head.rotation.y = MathUtils.degToRad(HEAD_TILT_DEG);
  root.add(head);
  const Y = (v: number) => v * WIDE;
  const outline = new Shape();
  outline.moveTo(0, Y(-23));
  outline.lineTo(28, Y(-41));
  outline.lineTo(168, Y(-45));
  outline.quadraticCurveTo(188, Y(-46), 189, Y(-26));
  outline.lineTo(191, Y(30));
  outline.quadraticCurveTo(192, Y(49), 172, Y(49));
  outline.lineTo(28, Y(43));
  outline.lineTo(0, Y(23));
  outline.closePath();
  const headGeo = new ExtrudeGeometry(outline, {
    depth: 13,
    bevelEnabled: true,
    bevelSize: 1.2,
    bevelThickness: 1.2,
    bevelSegments: 2,
    curveSegments: 16,
  });
  headGeo.translate(0, 0, -13);
  head.add(new Mesh(headGeo, mat.head));

  for (const { string: s, side, post } of g.tuners) {
    const tuner = new Group();
    tuner.name = "tuner";
    tuner.position.set(post.x, post.y, post.z);
    head.add(tuner);

    const add = (mesh: Mesh, y: number, z: number) => {
      mesh.position.set(0, y, z);
      tuner.add(mesh);
      return mesh;
    };
    // The post and its bushing stand on the face, their axes along z.
    add(new Mesh(new CylinderGeometry(2.6, 2.6, 12, 16), mat.chrome), 0, 7.2).rotation.x = Math.PI / 2;
    add(new Mesh(new CylinderGeometry(4.8, 4.8, 1.6, 20), mat.chrome), 0, 1.8).rotation.x = Math.PI / 2;
    // The shaft and the button reach out behind, past the headstock's edge.
    add(new Mesh(new CylinderGeometry(1.6, 1.6, 22, 10), mat.chrome), side * Y(52) - post.y, -7);
    add(new Mesh(new SphereGeometry(7, 20, 14), mat.button), side * Y(64) - post.y, -7).scale.set(0.45, 1, 1.15);

    const label = text(g.labels[s], LABEL_COLOUR, LABEL_MM, "label");
    label.position.set(post.x + LABEL_PAST_POST, post.y, 1.5);
    head.add(label);
  }
  head.updateMatrixWorld(true);

  // Strings: the tube over the board, and a rod from the nut to the post.
  const nutAt = (s: number): Vec3 => ({ x: 0, y: g.stringY(s, 0), z: g.stringZ(0) });
  const endAt = (s: number): Vec3 => ({ x: g.boardEnd, y: g.stringY(s, g.boardEnd), z: g.stringZ(g.boardEnd) });
  const strings = g.tuners.map(({ string: s }) => {
    const wound = g.wound[s];
    const material = standard(wound ? WOUND : PLAIN, {
      metalness: 0.3,
      roughness: wound ? 0.35 : 0.25,
      side: DoubleSide,
    });
    const string = new VibratingString(nutAt(s), endAt(s), g.gauges[s], material, wound ? WOUND : PLAIN);
    root.add(string.tube, string.blur);
    const toPost = rod(toVector(nutAt(s)), toVector(g.tuners[s].top), g.gauges[s], material);
    toPost.name = "string-head";
    root.add(toPost);
    return string;
  });

  return {
    root,
    pickable: [board, neck],
    strings,
    dispose() {
      const parts = new Set<{ dispose(): void }>(textures);
      root.traverse((o) => {
        if (!(o instanceof Mesh)) return;
        parts.add(o.geometry);
        for (const material of Array.isArray(o.material) ? o.material : [o.material]) parts.add(material);
      });
      for (const part of parts) part.dispose();
    },
  };
}
