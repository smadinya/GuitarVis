/**
 * The keyed updater, for three.js: 007's `MarkLayer` with meshes for nodes. A
 * note's key is stable across frames, so its mesh is made once, updated while
 * the key lasts, and removed when the key is gone. Every onset has its own
 * key, which is what makes each pluck pulse.
 *
 * A fretted note is a filled dot and an open string a ring, both lying on the
 * board. Text is drawn by an injected painter: a canvas in the browser, a blank
 * texture in a test. Nothing here needs WebGL.
 */
import { Mesh, MeshBasicMaterial, type Object3D, PlaneGeometry, type Texture } from "three";

import type { Geometry } from "./geometry";
import type { SoundingNote } from "./sounding";

/** A new mark swells to this many times its size... */
export const PULSE_SCALE = 1.5;
/** ...and settles over this long, in wall-clock ms. */
export const PULSE_MS = 220;

/** Draws a dot or a ring for a note's name. Each result is shared and owned by the layer. */
export type DotPainter = (name: string, open: boolean) => Texture;

/** A mark's mesh: one material each, because opacity differs per note. */
type MarkMesh = Mesh<PlaneGeometry, MeshBasicMaterial>;

interface Live {
  mesh: MarkMesh;
  r: number;
  /** The `wallMs` of the `apply` that made it. */
  born: number;
}

export class NoteLayer {
  /** 2 by 2, so a mesh's scale is its radius. */
  private readonly plane = new PlaneGeometry(2, 2);
  /** By `${name}|${open}`: every mark that shares a name shares a texture. */
  private readonly textures = new Map<string, Texture>();
  private readonly live = new Map<string, Live>();

  constructor(
    private readonly parent: Object3D,
    private readonly g: Geometry,
    private readonly paint: DotPainter,
  ) {}

  /**
   * Put this frame's notes on the neck. `wallMs` is wall-clock time, because a
   * pulse is a reaction to the eye and not to the song. Returns whether any
   * pulse is still running, so the caller knows to ask for another frame.
   */
  apply(notes: readonly SoundingNote[], wallMs: number, pulse: boolean): boolean {
    const seen = new Set<string>();
    let pulsing = false;
    for (const note of notes) {
      seen.add(note.key);
      let entry = this.live.get(note.key);
      if (entry === undefined) {
        entry = this.make(note, wallMs);
        this.live.set(note.key, entry);
      }
      const { mesh, r, born } = entry;
      mesh.material.opacity = note.opacity;

      const k = Math.min(1, (wallMs - born) / PULSE_MS);
      const size = pulse ? r * (1 + (PULSE_SCALE - 1) * (1 - k) ** 2) : r;
      mesh.scale.set(size, size, 1);
      if (pulse && k < 1) pulsing = true;
    }
    for (const [key, { mesh }] of this.live) {
      if (seen.has(key)) continue;
      mesh.removeFromParent();
      mesh.material.dispose(); // the texture is shared, and stays
      this.live.delete(key);
    }
    return pulsing;
  }

  /** The colour scheme changed: paint every name again, and give each mark its new texture. */
  repaint(): void {
    this.disposeTextures();
    for (const { mesh } of this.live.values()) {
      const { name, open } = mesh.userData as { name: string; open: boolean };
      mesh.material.map = this.texture(name, open);
      mesh.material.needsUpdate = true;
    }
  }

  /** Remove every mark, and free what the layer made. */
  dispose(): void {
    for (const { mesh } of this.live.values()) {
      mesh.removeFromParent();
      mesh.material.dispose();
    }
    this.live.clear();
    this.disposeTextures();
    this.plane.dispose();
  }

  private make(note: SoundingNote, wallMs: number): Live {
    const { at, r, open } = this.g.mark(note.string, note.fret);
    const material = new MeshBasicMaterial({
      map: this.texture(note.name, open),
      transparent: true,
      depthWrite: false,
    });
    const mesh: MarkMesh = new Mesh(this.plane, material);
    mesh.name = open ? "ring" : "dot";
    mesh.userData = { name: note.name, open };
    mesh.position.set(at.x, at.y, at.z);
    mesh.renderOrder = 2;
    this.parent.add(mesh);
    return { mesh, r, born: wallMs };
  }

  private texture(name: string, open: boolean): Texture {
    const key = `${name}|${open}`;
    let texture = this.textures.get(key);
    if (texture === undefined) {
      texture = this.paint(name, open);
      this.textures.set(key, texture);
    }
    return texture;
  }

  private disposeTextures(): void {
    for (const texture of this.textures.values()) texture.dispose();
    this.textures.clear();
  }
}
