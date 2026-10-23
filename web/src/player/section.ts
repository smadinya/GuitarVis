import { useMemo } from "react";

import { TrackCursor } from "../playback/cursor";
import type { PlaybackEngine } from "../playback/engine";
import { useFollowed } from "../playback/follow";
import type { Song } from "../song";

/**
 * The index of the song's section the playhead is in, or -1 between sections.
 * The sidebar marks it and the transport names it. Both read it from the
 * frames, with a cursor of their own, so they never disagree: the transport's
 * readout moves four times a second, and would trail the sidebar by up to a
 * quarter of one.
 */
export function useCurrentSection(song: Song, engine: PlaybackEngine): number {
  const follow = useMemo(() => {
    const cursor = new TrackCursor(song.sections);
    return (t: number) => cursor.at(t).current;
  }, [song]);
  return useFollowed(engine, follow);
}
