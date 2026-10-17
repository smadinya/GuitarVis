import { useEffect, useRef, useState, type MouseEvent } from "react";
import { WebGLRenderer } from "three";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import type { View } from "./camera";
import { Stage, type Renderer } from "./stage";

export const NO_WEBGL = "The guitar needs WebGL, which this browser has turned off.";
/** Where the chosen view is remembered. */
export const VIEW_KEY = "guitarvis.guitar-view";

const VIEWS: Array<[View, string]> = [
  ["2d", "2D"],
  ["3d", "3D"],
];

export interface GuitarProps {
  song: Song;
  engine: PlaybackEngine;
  /** Makes the renderer; a test passes a fake, because jsdom has no WebGL. */
  createRenderer?: (canvas: HTMLCanvasElement) => Renderer;
}

/** At module level, so the default is one function on every render, and the
 * Stage is not rebuilt each time. */
const webGLRenderer = (canvas: HTMLCanvasElement): Renderer => new WebGLRenderer({ canvas, antialias: true });

/** The remembered view; a first visit, or storage that is off, gets 3D. */
function readView(): View {
  try {
    const stored = localStorage.getItem(VIEW_KEY);
    return stored === "2d" || stored === "3d" ? stored : "3d";
  } catch {
    return "3d";
  }
}

function writeView(view: View): void {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // Storage is off: the choice lasts until the page closes.
  }
}

/** A clicked button does not keep focus, so Space stays play/pause rather
 * than clicking the last button again. Keyboard focus still works. */
function keepFocus(event: MouseEvent) {
  event.preventDefault();
}

/**
 * The guitar panel. React renders its chrome: the canvas's box, the message
 * overlay, the view toggle and "Reset view". Everything per frame is the
 * Stage's, so React renders only on mount, on a view toggle, and when WebGL
 * is lost or comes back.
 */
export function Guitar({ song, engine, createRenderer = webGLRenderer }: GuitarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Stage | null>(null);
  const [view, setView] = useState<View>(readView);
  // Read when a Stage is made, so a view change moves the camera rather than
  // rebuilding the Stage.
  const viewRef = useRef(view);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const overlay = overlayRef.current;
    if (canvas === null || overlay === null) return;
    let renderer: Renderer;
    try {
      renderer = createRenderer(canvas);
    } catch {
      setUnavailable(true);
      return;
    }
    const stage = new Stage({ canvas, overlay, song, engine, renderer, view: viewRef.current, onLost: setUnavailable });
    stageRef.current = stage;
    return () => {
      stageRef.current = null;
      stage.dispose();
    };
  }, [song, engine, createRenderer]);

  useEffect(() => {
    viewRef.current = view;
    stageRef.current?.setView(view);
    writeView(view);
  }, [view]);

  const reset = () => stageRef.current?.resetView();

  return (
    <div className="guitar">
      <canvas ref={canvasRef} role="img" aria-label="Guitar" />
      <div ref={overlayRef} className="guitar-message" hidden />
      {unavailable ? (
        <p className="guitar-unavailable">{NO_WEBGL}</p>
      ) : (
        <>
          <div className="guitar-views" role="group" aria-label="View">
            {VIEWS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={view === value}
                onMouseDown={keepFocus}
                onClick={() => setView(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <button type="button" className="guitar-reset" onMouseDown={keepFocus} onClick={reset}>
            Reset view
          </button>
        </>
      )}
    </div>
  );
}
