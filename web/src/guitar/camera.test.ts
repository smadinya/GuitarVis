import { PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import type { Note, TabDocument } from "../types/tabDocument";
import {
  FAR,
  FOV,
  HOME_3D,
  MARGIN,
  NEAR,
  PANEL_ASPECT,
  between,
  clampTarget,
  easeInOut,
  focusPose,
  homePose,
  type Pose,
} from "./camera";
import { geometryOf, type Vec3 } from "./geometry";

const STANDARD = ["E2", "A2", "D3", "G3", "B3", "E4"];

function note(fret: number): Note {
  return { id: `n${fret}`, t: 1, dur: 0.5, midi: 40 + fret, string: 0, fret, confidence: 0.95 };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: { tuning: STANDARD },
    timing: {},
    notes: [note(0), note(5)],
    ...fields,
  };
}

const g = geometryOf(buildSong(doc()));

/** Where `p` lands on screen, in normalised device coordinates. */
function project(pose: Pose, aspect: number, p: Vec3): Vector3 {
  const camera = new PerspectiveCamera(FOV, aspect, NEAR, FAR);
  camera.position.copy(pose.position);
  camera.lookAt(pose.target.x, pose.target.y, pose.target.z);
  camera.updateMatrixWorld();
  return new Vector3(p.x, p.y, p.z).project(camera);
}

const corners = (z: number) =>
  [g.bounds.min, g.bounds.max].flatMap((a) => [g.bounds.min, g.bounds.max].map((b) => ({ x: a.x, y: b.y, z })));

describe("the camera's poses", () => {
  it("frames the whole model in 2D, edge to edge, at wide and narrow aspects", () => {
    for (const aspect of [1.4, 2.8, 4]) {
      const pose = homePose("2d", g, aspect);
      const front = corners(0).map((c) => project(pose, aspect, c));
      for (const p of [...front, ...corners(g.bounds.min.z).map((c) => project(pose, aspect, c))]) {
        expect(Math.abs(p.x)).toBeLessThanOrEqual(1);
        expect(Math.abs(p.y)).toBeLessThanOrEqual(1);
      }
      const fill = Math.max(...front.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)]));
      expect(fill).toBeCloseTo(1 / (1 + MARGIN), 2);
    }
  });

  it("always looks along −z in 2D", () => {
    const poses = [homePose("2d", g, 2.8), focusPose("2d", { x: -200, y: 10, z: 0 }, HOME_3D, g)];
    for (const { position, target } of poses) {
      expect([position.x, position.y]).toEqual([target.x, target.y]);
      expect(position.z).toBeGreaterThan(target.z);
    }
  });

  it("stays finite before the panel is measured", () => {
    for (const aspect of [0, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(homePose("2d", g, aspect)).toEqual(homePose("2d", g, PANEL_ASPECT));
    }
  });

  it("opens 3D on the spike's three-quarter view", () => {
    expect(homePose("3d", g, 2.8)).toEqual(HOME_3D);
  });

  it("keeps a panned target over the model", () => {
    expect(clampTarget({ x: -2000, y: 500, z: 80 }, g)).toEqual({ x: g.bounds.min.x, y: g.bounds.max.y, z: g.bounds.max.z });
    expect(clampTarget({ x: -100, y: 5, z: 0 }, g)).toEqual({ x: -100, y: 5, z: 0 });
  });

  it("focuses on the fingerboard: 260 mm in front in 2D, 190 mm back along the view in 3D", () => {
    const onTheNeckBack = { x: -200, y: 60, z: -8 };
    const flat = focusPose("2d", onTheNeckBack, HOME_3D, g);
    expect(flat.target).toEqual({ x: -200, y: g.halfWidth(-200), z: 0 });
    expect(flat.position).toEqual({ x: -200, y: g.halfWidth(-200), z: 260 });

    const turned = focusPose("3d", onTheNeckBack, HOME_3D, g);
    const away = new Vector3().subVectors(turned.position, turned.target);
    const before = new Vector3().subVectors(HOME_3D.position, HOME_3D.target);
    expect(away.length()).toBeCloseTo(190, 9);
    expect(away.normalize().dot(before.normalize())).toBeCloseTo(1, 9);
  });

  it("eases in and out, from one pose to the other", () => {
    expect([0, 0.5, 1].map(easeInOut)).toEqual([0, 0.5, 1]);
    expect(easeInOut(0.25)).toBeLessThan(0.25);
    expect(easeInOut(0.75)).toBeGreaterThan(0.75);
    const home = homePose("2d", g, 2.8);
    expect(between(home, HOME_3D, 0)).toEqual(home);
    expect(between(home, HOME_3D, 1)).toEqual(HOME_3D);
  });
});
