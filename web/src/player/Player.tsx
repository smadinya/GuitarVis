import { useEffect, useState } from "react";

import type { MediaLike } from "../playback/clock";
import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { TabStrip } from "../tab/TabStrip";
import { Controls } from "./Controls";
import { useTransportKeys } from "./keys";
import { Warnings } from "./Warnings";

export interface PlayerProps {
  song: Song;
  jobId: string;
  /** Must be stable across renders: a new function makes a new engine. */
  createMedia: () => MediaLike;
}

/** One engine per song; every view subscribes to it. Phase 5's fretboards
 * are more onFrame listeners beside the TabStrip. */
export function Player({ song, jobId, createMedia }: PlayerProps) {
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);

  useEffect(() => {
    const created = new PlaybackEngine({ media: createMedia(), jobId, duration: song.duration });
    setEngine(created);
    return () => created.dispose();
  }, [song, jobId, createMedia]);

  useTransportKeys(engine);

  if (engine === null) return null;
  return (
    <section className="player">
      <Warnings warnings={song.warnings} />
      <TabStrip song={song} engine={engine} />
      <Controls engine={engine} />
    </section>
  );
}
