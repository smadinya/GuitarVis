/**
 * The engine every component test drives: over a FakeMedia, with its animation
 * frames run by hand, so a test decides when a frame draws.
 */
import { act } from "@testing-library/react";

import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { FakeFrames, FakeMedia } from "./fakeMedia";
import { JOB_ID } from "./jobs";

/**
 * An engine over FakeMedia that has reported `duration`, with its frames run
 * by hand. `duration` defaults to the song's, and matters because `seek`
 * clamps to the engine's own duration.
 */
export function fakeEngine(song: Song, options: { duration?: number; media?: FakeMedia } = {}) {
  const media = options.media ?? new FakeMedia();
  const frames = new FakeFrames();
  const duration = options.duration ?? song.duration;
  const engine = new PlaybackEngine({
    media,
    jobId: JOB_ID,
    duration,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  media.loadMetadata(duration);
  return {
    engine,
    media,
    frames,
    /** Seek to t and run the frames that draw it, inside act(). */
    at: (t: number) => {
      act(() => {
        engine.seek(t);
        frames.flush();
      });
    },
  };
}
