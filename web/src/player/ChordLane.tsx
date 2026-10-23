import { useEffect, useMemo, useRef } from "react";

import { samePosition, TrackCursor } from "../playback/cursor";
import type { PlaybackEngine } from "../playback/engine";
import { useFollowed } from "../playback/follow";
import type { Song } from "../song";
import { cellState, laneCells } from "./lane";

/** The song's chords as a row of cells under the guitar: the ones played, the
 * one sounding and the ones to come, each faded by how sure the analysis was,
 * and the row kept scrolled to the playhead. It follows playback through
 * `onFrame` and sets state only when the chord changes, so it never renders at
 * frame rate. A song with no chords draws nothing. */
export function ChordLane({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const cells = useMemo(() => laneCells(song.chords), [song]);
  const follow = useMemo(() => {
    const cursor = new TrackCursor(song.chords);
    return (t: number) => cursor.at(t);
  }, [song]);
  const position = useFollowed(engine, follow, samePosition);
  const laneRef = useRef<HTMLOListElement>(null);

  // The cell to keep in the middle: the current one, or between chords the
  // one coming.
  const target = position.current >= 0 ? position.current : Math.min(position.next, cells.length - 1);

  // Centre the current cell. Set the lane's own scrollLeft: scrollIntoView
  // would scroll the page as well whenever the lane is off screen.
  useEffect(() => {
    const lane = laneRef.current;
    const cell = lane?.children[target];
    if (lane === null || !(cell instanceof HTMLElement)) return;
    lane.scrollLeft = cell.offsetLeft + cell.offsetWidth / 2 - lane.clientWidth / 2;
  }, [target, cells]);

  if (cells.length === 0) return null;
  return (
    <ol className="chord-lane" aria-label="Chord lane" ref={laneRef}>
      {cells.map((cell, index) => {
        const state = cellState(index, position);
        return (
          <li
            key={index}
            className="chord-cell"
            data-state={state}
            aria-current={state === "current" ? "true" : undefined}
          >
            {/* The symbol fades, not the cell, so the lane stays one unbroken row. */}
            <span style={{ opacity: cell.opacity }}>{cell.symbol}</span>
          </li>
        );
      })}
    </ol>
  );
}
