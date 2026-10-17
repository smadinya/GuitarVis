import { useEffect, useRef, useState, type MouseEvent } from "react";
import { WebGLRenderer } from "three";

import { GUITAR_FAILED } from "../labels";
import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import type { View } from "./camera";
import { Stage, type Renderer } from "./stage";

/** True when WebGL is off, when only WebGL 1 exists (three needs 2), and when
 * the context stays lost. */
export const NO_WEBGL = "The guitar needs WebGL 2, which this browser does not have available.";
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
 * Stage's, so React renders only on mount, on a view toggle, when WebGL stays
 * lost or comes back, and when a draw throws. A throw's message wins over
 * the WebGL one.
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
  const [failed, setFailed] = useState(false);

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
    let stage: Stage;
    try {
      stage = new Stage({
        canvas,
        overlay,
        song,
        engine,
        renderer,
        view: viewRef.current,
        onLost: setUnavailable,
        onFailed: () => setFailed(true),
      });
    } catch (error) {
      // A bug, not missing WebGL: the boundary says so. The Stage has undone
      // its own setup, and left the renderer to this effect. The boundary
      // replaces this subtree, canvas and all, so the context goes too.
      renderer.dispose();
      renderer.forceContextLoss();
      throw error;
    }
    // A loss or a throw the old Stage reported is not this one's to show.
    setUnavailable(false);
    setFailed(false);
    stageRef.current = stage;
    return () => {
      stageRef.current = null;
      stage.dispose();
      // Release the context only once the canvas has left the page. React
      // detaches a deleted subtree's DOM before it runs passive-effect
      // cleanups, so on a real unmount the canvas is already detached. On a
      // rebuild (a new song, engine or createRenderer) and on StrictMode's
      // rehearsed unmount it stays, and the next renderer gets its context:
      // released here, that context would come to it already lost. After
      // dispose, nothing listens for the loss, and three's forceContextLoss
      // needs only the context, which dispose leaves.
      if (!canvas.isConnected) renderer.forceContextLoss();
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
      {failed || unavailable ? (
        <p className="guitar-unavailable">{failed ? GUITAR_FAILED : NO_WEBGL}</p>
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
