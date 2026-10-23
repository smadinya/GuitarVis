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

export interface GuitarProps {
  song: Song;
  engine: PlaybackEngine;
  /** Makes the renderer; a test passes a fake, because jsdom has no WebGL. */
  createRenderer?: (canvas: HTMLCanvasElement) => Renderer;
  /** The camera's view. The page chooses it, so a change moves the camera on
   * the same Stage. */
  view?: View;
}

/** At module level, so the default is one function on every render, and the
 * Stage is not rebuilt each time. */
const webGLRenderer = (canvas: HTMLCanvasElement): Renderer => new WebGLRenderer({ canvas, antialias: true });

/** A clicked button does not keep focus, so Space stays play/pause rather
 * than clicking the last button again. Keyboard focus still works. */
function keepFocus(event: MouseEvent) {
  event.preventDefault();
}

/**
 * The guitar panel. React renders its chrome: the canvas's box, the message
 * overlay and "Reset view". Everything per frame is the Stage's, so React
 * renders only on mount, on a view change, when WebGL stays lost or comes
 * back, and when a draw throws. A throw's message wins over the WebGL one.
 */
export function Guitar({ song, engine, createRenderer = webGLRenderer, view = "3d" }: GuitarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Stage | null>(null);
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
          <button type="button" className="guitar-reset" onMouseDown={keepFocus} onClick={reset}>
            Reset view
          </button>
        </>
      )}
    </div>
  );
}
