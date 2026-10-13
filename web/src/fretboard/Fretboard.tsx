import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { cursorsOf, layout } from "./layout";
import { MarkLayer } from "./marks";
import { neckOf } from "./neck";

const INLAY_R = 3;
const INLAY_PAIR = 5; // fret 12's two dots sit this far either side of its centre

/**
 * The 2D fretboard. React draws the neck, which changes only with the song
 * and the panel's width. The notes are a layer React renders empty and then
 * leaves alone: every frame, layout() gives the marks for that instant and a
 * MarkLayer applies them, so React never renders at frame rate.
 */
export function Fretboard({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<SVGGElement>(null);
  const [width, setWidth] = useState(0);
  const neck = useMemo(() => neckOf(song, width), [song, width]);
  const cursors = useMemo(() => cursorsOf(song), [song]);
  // Read by the frame listener, so a resize moves the marks without
  // resubscribing, which would clear them for a frame.
  const neckRef = useRef(neck);

  // Measured before the first paint, so the neck never shows at width 0. The
  // box is a plain div: its width does not depend on the SVG's.
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (box === null) return;
    const measure = () => setWidth(box.clientWidth);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(box);
    return () => observer?.disconnect();
  }, []);

  useEffect(() => {
    neckRef.current = neck;
    engine.redraw();
  }, [neck, engine]);

  useEffect(() => {
    const layer = layerRef.current;
    if (layer === null) return;
    const marks = new MarkLayer(layer);
    const stop = engine.onFrame((t) => marks.apply(layout(song, cursors, t, neckRef.current)));
    return () => {
      stop();
      marks.dispose();
    };
  }, [song, cursors, engine]);

  const end = neck.wireX[neck.frets];
  return (
    <div ref={boxRef} className="fretboard">
      <svg role="img" aria-label="Fretboard" width={neck.width} height={neck.height}>
        <rect
          className="fret-board"
          x={neck.wireX[0]}
          y={neck.top}
          width={end - neck.wireX[0]}
          height={neck.bottom - neck.top}
        />
        {neck.inlays.map(({ x, double }) =>
          (double ? [x - INLAY_PAIR, x + INLAY_PAIR] : [x]).map((cx) => (
            <circle key={cx} className="fret-inlay" cx={cx} cy={neck.inlayY} r={INLAY_R} />
          )),
        )}
        {neck.wireX.map((x, n) => (
          <line
            key={n}
            className={n === 0 ? "fret-nut" : "fret-wire"}
            x1={x}
            y1={neck.top}
            x2={x}
            y2={neck.bottom}
          />
        ))}
        {neck.strings.map(({ y, weight }, s) => (
          <line key={s} className="fret-string" x1={neck.stringsFrom} y1={y} x2={end} y2={y} strokeWidth={weight} />
        ))}
        {neck.strings.map(({ y, label }, s) => (
          <text key={s} className="fret-label" x={neck.labelX} y={y}>
            {label}
          </text>
        ))}
        {neck.noteX.slice(1).map((x, i) => (
          <text key={i} className="fret-number" x={x} y={neck.numberY}>
            {i + 1}
          </text>
        ))}
        <g ref={layerRef} />
      </svg>
    </div>
  );
}
