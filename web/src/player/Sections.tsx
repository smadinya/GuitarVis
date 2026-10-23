import { useEffect, useState } from "react";

import { samePosition, TrackCursor, type Position } from "../playback/cursor";
import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { Button } from "./Button";
import { distinctSymbols } from "./lane";
import { clock } from "./time";

/** The song's sections, each a jump to its start, with the one playing
 * marked, and under them the chords the song uses, each once. It follows
 * playback through `onFrame` and sets state only when the section changes, so
 * it never renders at frame rate. A section click seeks and nothing else: a
 * loop that is set stays set. */
export function Sections({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const [current, setCurrent] = useState(-1);

  useEffect(() => {
    const cursor = new TrackCursor(song.sections);
    // Null until the first frame, which always sets: after a change of song
    // the state is the old song's, whatever the new one's position is.
    let last: Position | null = null;
    return engine.onFrame((t) => {
      const position = cursor.at(t);
      if (last !== null && samePosition(last, position)) return;
      last = position;
      setCurrent(position.current);
    });
  }, [song, engine]);

  const chords = distinctSymbols(song.chords);
  return (
    <aside className="sections" aria-label="Sections">
      <h2>Sections</h2>
      {song.sections.length === 0 ? (
        <p>No sections found</p>
      ) : (
        <ol>
          {song.sections.map((section, index) => (
            <li key={index}>
              <Button current={index === current} onClick={() => engine.seek(section.t)}>
                {section.label} <span className="time">{clock(section.t)}</span>
              </Button>
            </li>
          ))}
        </ol>
      )}
      {chords.length > 0 && (
        <>
          <h2>Chords</h2>
          <ul className="chord-list">
            {chords.map((symbol) => (
              <li key={symbol}>{symbol}</li>
            ))}
          </ul>
        </>
      )}
    </aside>
  );
}
