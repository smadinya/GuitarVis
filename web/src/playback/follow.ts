import { useEffect, useState } from "react";

import type { PlaybackEngine } from "./engine";

/** "Nothing derived yet", apart from any value a view may legitimately hold. */
const NONE = Symbol("none");

/**
 * A value that follows the playhead: `follow(t)` read at every frame, held in
 * state, and set only when the new value differs from the last by `same`. A
 * view that shows the current chord or section calls this, and so renders when
 * the chord or section changes and never at frame rate.
 *
 * The playhead is read once when the view subscribes, as well as in the
 * state's first value, so a view that mounts mid-song, or is handed another
 * song, is right before its first frame arrives. One `onFrame` subscription
 * per call, released on unmount.
 *
 * `follow` is what a view derives from the time, and it must be stable: build
 * it in `useMemo`, over the song. A cursor it keeps is then the view's own, as
 * NoteCursor and TrackCursor are meant to be, and a new function (another
 * song) subscribes again and derives again from the same playhead. `same`
 * defaults to identity, right for numbers, strings and items of one list.
 */
export function useFollowed<V>(
  engine: PlaybackEngine,
  follow: (t: number) => V,
  same: (a: V, b: V) => boolean = Object.is,
): V {
  const [value, setValue] = useState(() => follow(engine.getState().time));

  useEffect(() => {
    // Nothing until the first update, which always runs: after a change of
    // song the state is the old song's, whatever the new one's position is.
    let last: V | typeof NONE = NONE;
    const update = (t: number) => {
      const next = follow(t);
      if (last !== NONE && same(last, next)) return;
      last = next;
      // The state may already hold what this reads (the first update, on a
      // mount): keeping that value spares a render for nothing.
      setValue((current) => (same(current, next) ? current : next));
    };
    // onFrame asks for a frame, but it comes later, and until it does the
    // state would show the last song's position.
    update(engine.getState().time);
    return engine.onFrame(update);
  }, [engine, follow, same]);

  return value;
}
