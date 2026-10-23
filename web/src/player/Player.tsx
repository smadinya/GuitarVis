import { lazy, Suspense, useEffect, useState } from "react";

import type { MediaLike } from "../playback/clock";
import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { TabStrip } from "../tab/TabStrip";
import { Controls } from "./Controls";
import { GuitarBoundary, GuitarChunkError } from "./GuitarBoundary";
import { useTransportKeys } from "./keys";
import { useStoredView, ViewSwitch } from "./ViewSwitch";
import { Warnings } from "./Warnings";

/** three.js is about 150 kB gzipped, so the guitar is its own chunk, fetched
 * when a song first shows: the upload page never downloads it. A fetch that
 * fails is marked as such, so the boundary can tell it from a bug. */
const Guitar = lazy(() =>
  import("../guitar/Guitar")
    .catch((error: unknown) => {
      throw new GuitarChunkError(error);
    })
    .then((module) => ({ default: module.Guitar })),
);

export interface PlayerProps {
  song: Song;
  jobId: string;
  /** Must be stable across renders: a new function makes a new engine. */
  createMedia: () => MediaLike;
}

/** One engine per song; every view subscribes to it. The guitar sits above
 * the tab strip; each is one more onFrame listener. The page chooses the view
 * here, beside the engine, so a switch never rebuilds the engine: "Tab only"
 * unmounts the guitar, and the audio plays on. */
export function Player({ song, jobId, createMedia }: PlayerProps) {
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);
  const [view, setView] = useStoredView();

  useEffect(() => {
    const created = new PlaybackEngine({ media: createMedia(), jobId, duration: song.duration });
    setEngine(created);
    return () => created.dispose();
  }, [song, jobId, createMedia]);

  useTransportKeys(engine);

  if (engine === null) return null;
  return (
    <section className="player">
      <ViewSwitch view={view} onChange={setView} />
      <Warnings warnings={song.warnings} />
      {view !== "tab" && (
        <GuitarBoundary>
          <Suspense fallback={<div className="guitar" />}>
            <Guitar song={song} engine={engine} view={view} />
          </Suspense>
        </GuitarBoundary>
      )}
      <TabStrip song={song} engine={engine} />
      <Controls engine={engine} />
    </section>
  );
}
