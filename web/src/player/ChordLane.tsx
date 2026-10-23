import { useEffect, useMemo, useRef, useState } from "react";

import { samePosition, TrackCursor, type Position } from "../playback/cursor";
import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { cellState, laneCells } from "./lane";

/** Before the first frame nothing has played: no chord is current, and the
 * first is next. */
const START: Position = { current: -1, next: 0 };

/** The song's chords as a row of cells under the guitar: the ones played, the
 * one sounding and the ones to come, each faded by how sure the analysis was,
 * and the row kept scrolled to the playhead. It follows playback through
 * `onFrame` and sets state only when the chord changes, so it never renders at
 * frame rate. A song with no chords draws nothing. */
export function ChordLane({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const cells = useMemo(() => laneCells(song.chords), [song]);
  const [position, setPosition] = useState(START);
  const laneRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const cursor = new TrackCursor(song.chords);
    // Null until the first frame, which always sets: after a change of song
    // the state is the old song's, whatever the new one's position is.
    let last: Position | null = null;
    return engine.onFrame((t) => {
      const position = cursor.at(t);
      if (last !== null && samePosition(last, position)) return;
      last = position;
      setPosition(position);
    });
  }, [song, engine]);

  // Centre the current cell, or between chords the one coming. Set the lane's
  // own scrollLeft: scrollIntoView would scroll the page as well whenever the
  // lane is off screen.
  useEffect(() => {
    const lane = laneRef.current;
    const index = position.current >= 0 ? position.current : Math.min(position.next, cells.length - 1);
    const cell = lane?.children[index];
    if (lane === null || !(cell instanceof HTMLElement)) return;
    lane.scrollLeft = cell.offsetLeft + cell.offsetWidth / 2 - lane.clientWidth / 2;
  }, [position, cells]);

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
