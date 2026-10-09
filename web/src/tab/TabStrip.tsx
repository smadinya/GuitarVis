import { useEffect, useRef } from "react";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { layout, rowsOf, type DrawOp, type Font, type Paint } from "./layout";

/** layout() sizes chord labels, section labels and fret numbers at GLYPH_W
 * (7 px) a character. Those fonts are monospace at 12 px (about 7.2 px), so
 * the estimate holds. Only the large chord, shown over an unclear passage,
 * runs wider, at about 8.4 px. The message is centred and is not measured. */
const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const FONTS: Record<Font, string> = {
  fret: `12px ${MONO}`,
  fretBold: `bold 13px ${MONO}`,
  chord: `bold 12px ${MONO}`,
  chordLarge: `bold 14px ${MONO}`,
  label: `12px ${MONO}`,
  message: "15px system-ui, sans-serif",
};

type Palette = Record<Paint, string>;

/** Colours come from the --tab-* custom properties in styles.css. Listing
 * each paint, rather than looping over a list of them, makes tsc check that
 * none is missing. */
function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const read = (paint: Paint) => style.getPropertyValue(`--tab-${paint}`).trim() || "#888";
  return {
    background: read("background"),
    text: read("text"),
    muted: read("muted"),
    accent: read("accent"),
    string: read("string"),
    bar: read("bar"),
    playhead: read("playhead"),
    loop: read("loop"),
    hidden: read("hidden"),
  };
}

function paint(
  context: CanvasRenderingContext2D,
  ops: DrawOp[],
  palette: Palette,
  width: number,
  height: number,
): void {
  context.globalAlpha = 1;
  context.fillStyle = palette.background;
  context.fillRect(0, 0, width, height);
  context.textBaseline = "middle";
  for (const op of ops) {
    context.globalAlpha = op.alpha;
    switch (op.kind) {
      case "rect":
        context.fillStyle = palette[op.paint];
        context.fillRect(op.x, op.y, op.w, op.h);
        break;
      case "line":
        context.strokeStyle = palette[op.paint];
        context.lineWidth = op.width;
        context.beginPath();
        context.moveTo(op.x1, op.y1);
        context.lineTo(op.x2, op.y2);
        context.stroke();
        break;
      case "text":
        context.fillStyle = palette[op.paint];
        context.font = FONTS[op.font];
        context.textAlign = op.align;
        context.fillText(op.text, op.x, op.y);
        break;
    }
  }
  context.globalAlpha = 1;
}

/**
 * The scrolling tab: a canvas repainted from the engine's frames. All the
 * logic is in layout(); this only scales for the display and paints. With no
 * 2D context (jsdom, or a browser without canvas) it paints nothing.
 */
export function TabStrip({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const height = rowsOf(song).height;

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d") ?? null;
    if (canvas === null || context === null) return;

    let width = 0;
    let palette = readPalette(canvas);
    const resize = () => {
      width = canvas.clientWidth;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      palette = readPalette(canvas);
      engine.redraw();
    };
    resize();

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(canvas);
    const scheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    scheme?.addEventListener("change", resize);
    const stop = engine.onFrame((t) => {
      paint(context, layout(song, t, { width, height }, engine.getState().loop), palette, width, height);
    });

    return () => {
      stop();
      observer?.disconnect();
      scheme?.removeEventListener("change", resize);
    };
  }, [song, engine, height]);

  // The bitmap's width is set from the CSS width, so the CSS width must not
  // depend on the bitmap's: with the canvas's intrinsic sizing, each resize
  // pass would multiply it by the display's pixel ratio. Hence width here,
  // not in the stylesheet. The bitmap's height is `height` device-independent
  // pixels, so `height` must be the content box's: content-box, because the
  // global border-box would count a border or padding in it and resample every
  // frame. For the same reason .tab-strip draws its frame with a box-shadow,
  // not a border, which would also overflow the 100% width here.
  return (
    <canvas
      ref={canvasRef}
      className="tab-strip"
      style={{ display: "block", boxSizing: "content-box", width: "100%", height }}
      aria-label="Tab"
    />
  );
}
