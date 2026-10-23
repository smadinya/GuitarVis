import { useEffect, useState } from "react";

import { CHORD_THRESHOLDS, FADED, emphasis, isHidden } from "../confidence";
import { TrackCursor, inWindow } from "../playback/cursor";
import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import type { Chord } from "../types/tabDocument";

/** What the overlay draws: the chord sounding, the one after it, and whether
 * the playhead is inside a hidden passage. */
interface Shown {
  now: Chord | null;
  next: Chord | null;
  hidden: boolean;
}

/** Chords are compared by identity: they come from one sorted list. */
function sameShown(a: Shown, b: Shown): boolean {
  return a.now === b.now && a.next === b.next && a.hidden === b.hidden;
}

/** The chord now, in the guitar's top-left, and the one after it. Hidden
 * inside a hidden passage, where the guitar shows the chord itself in the
 * middle of the panel. Both are faded by confidence as the chord lane fades
 * its cells, and never hidden for being weak.
 *
 * It follows playback through `onFrame` and sets state only when the chord,
 * the next chord or the hidden state changes, so it never renders at frame
 * rate. A song with no chords draws nothing. */
export function NowNext({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  // Before the first frame nothing has played: no chord is current, and the
  // first is next.
  const [shown, setShown] = useState<Shown>({ now: null, next: song.chords[0] ?? null, hidden: false });

  useEffect(() => {
    const cursor = new TrackCursor(song.chords);
    // Null until the first update, which always sets: after a change of song
    // the state is the old song's, whatever the new one's position is.
    let last: Shown | null = null;
    const update = (t: number) => {
      const position = cursor.at(t);
      const next: Shown = {
        now: song.chords[position.current] ?? null,
        next: song.chords[position.next] ?? null,
        hidden: isHidden(inWindow(song.hidden, t, t, (p) => p.from, (p) => p.to), t),
      };
      if (last !== null && sameShown(last, next)) return;
      last = next;
      setShown(next);
    };
    // Mounted at a paused playhead no frame comes, so read where it stands.
    update(engine.getState().time);
    return engine.onFrame(update);
  }, [song, engine]);

  if (song.chords.length === 0) return null;
  const { now, next, hidden } = shown;
  return (
    <div className="guitar-chords" hidden={hidden}>
      {now !== null && (
        <span className="now" style={{ opacity: emphasis(now.confidence, CHORD_THRESHOLDS) }}>
          {now.symbol}
        </span>
      )}
      {next !== null && (
        <span className="next" style={{ opacity: emphasis(next.confidence, CHORD_THRESHOLDS) }}>
          next {next.symbol}
        </span>
      )}
    </div>
  );
}

/** What the dots mean: sounding, and less sure. There is no "Next": the
 * approach rings stay dropped, as spec 007 decided. */
export function Legend() {
  return (
    <ul className="guitar-legend" aria-label="Legend">
      <li>
        <span className="legend-dot" />
        Sounding
      </li>
      <li>
        <span className="legend-dot" style={{ opacity: FADED }} />
        Less sure
      </li>
    </ul>
  );
}
