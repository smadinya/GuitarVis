import { lazy, Suspense, useEffect, useState } from "react";

import type { MediaLike } from "../playback/clock";
import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { TabStrip } from "../tab/TabStrip";
import { ChordLane } from "./ChordLane";
import { GuitarBoundary, GuitarChunkError } from "./GuitarBoundary";
import { Header } from "./Header";
import { useTransportKeys } from "./keys";
import { Sections } from "./Sections";
import { Transport } from "./Transport";
import { useStoredView } from "./ViewSwitch";
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

/** One engine per song; every view subscribes to it. The header shows from
 * the first render, and the rest once the engine exists: the song page drops
 * its own title as soon as the document is ready, so a player that painted
 * nothing until its effect ran would blink the title out for a frame. The
 * guitar sits above the chord lane and the tab strip, with the sections
 * beside them; each is one more onFrame listener. The transport is docked
 * below them all. The page
 * chooses the view here, beside the engine, so a switch never rebuilds the
 * engine: "Tab only" unmounts the guitar, and the audio plays on. The lane
 * stays, since it is not three.js. */
export function Player({ song, jobId, createMedia }: PlayerProps) {
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);
  const [view, setView] = useStoredView();

  useEffect(() => {
    const created = new PlaybackEngine({ media: createMedia(), jobId, duration: song.duration });
    setEngine(created);
    return () => created.dispose();
  }, [song, jobId, createMedia]);

  useTransportKeys(engine);

  return (
    <section className="player">
      <Header song={song} engine={engine} view={view} onView={setView} />
      {engine !== null && (
        <>
          <div className="player-body">
            <div className="player-main">
              <Warnings warnings={song.warnings} />
              {view !== "tab" && (
                <GuitarBoundary>
                  <Suspense fallback={<div className="guitar" />}>
                    <Guitar song={song} engine={engine} view={view} />
                  </Suspense>
                </GuitarBoundary>
              )}
              <ChordLane song={song} engine={engine} />
              <TabStrip song={song} engine={engine} />
            </div>
            <Sections song={song} engine={engine} />
          </div>
          <Transport song={song} engine={engine} />
        </>
      )}
    </section>
  );
}
