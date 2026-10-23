import { useMemo, useSyncExternalStore } from "react";

import { BackIcon, ForwardIcon, PauseIcon, PlayIcon } from "../icons";
import { TrackCursor } from "../playback/cursor";
import {
  RATES,
  SEEK_STEP_SEC,
  type PlaybackEngine,
  type Rate,
  type Source,
} from "../playback/engine";
import type { Song } from "../song";
import { Button } from "./Button";
import { Scrubber } from "./Scrubber";
import { clock } from "./time";

const SOURCES: Array<[Source, string]> = [
  ["mix", "Full mix"],
  ["guitar", "Guitar only"],
];

/** The label of the track the player is not on. */
function otherSource(source: Source): string {
  return SOURCES.find(([candidate]) => candidate !== source)?.[1] ?? "the other track";
}

/** A loop button's text and accessible name. The point's time appears once it
 * is set, and the name keeps "Set loop start" as its prefix, so a screen
 * reader hears the time as well. */
function loopLabels(letter: "A" | "B", noun: "start" | "end", at: number | null) {
  const label = `Set loop ${noun}`;
  return at === null
    ? { text: letter, label }
    : { text: `${letter} ${clock(at)}`, label: `${label} (${clock(at)})` };
}

/**
 * The bar docked to the bottom of the window: play, back and forward five
 * seconds, the scrubber with the time and the section it is in, the speed, the
 * loop and the choice of audio. An audio error shows above the bar, where the
 * choice that mends it is.
 *
 * It renders from the engine's own state, which changes about four times a
 * second, so the section is read from a cursor in render and costs nothing per
 * frame. The scrubber's knob follows the frames on its own. No part of the bar
 * clips its overflow: the scrubber's preview rises over the track's ends.
 */
export function Transport({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const state = useSyncExternalStore(engine.subscribe, engine.getState);
  const cursor = useMemo(() => new TrackCursor(song.sections), [song]);
  const { current } = cursor.at(state.time);
  const label = current >= 0 ? song.sections[current].label : null;
  const { a, b } = state.loop;
  const start = loopLabels("A", "start", a);
  const end = loopLabels("B", "end", b);

  return (
    <div className="transport" role="region" aria-label="Transport">
      {state.error === "connection_lost" && (
        <div className="transport-error" role="alert">
          <p>
            We couldn't play this audio. Try {otherSource(state.source)}, or reload the page.
          </p>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      )}

      <div className="transport-bar">
        <div className="transport-play">
          <Button onClick={() => engine.seekBy(-SEEK_STEP_SEC)} label="Back 5 seconds">
            <BackIcon />
          </Button>
          <Button
            className="play"
            onClick={() => engine.toggle()}
            label={state.playing ? "Pause" : "Play"}
          >
            {state.playing ? <PauseIcon /> : <PlayIcon />}
          </Button>
          <Button onClick={() => engine.seekBy(SEEK_STEP_SEC)} label="Forward 5 seconds">
            <ForwardIcon />
          </Button>
        </div>

        <div className="transport-scrub">
          <Scrubber engine={engine} sections={song.sections} section={label} />
          <p className="time">
            <span>
              {clock(state.time)}
              {label !== null && ` · ${label}`}
            </span>
            {state.buffering && <span role="status">Buffering…</span>}
            <span>{clock(state.duration)}</span>
          </p>
        </div>

        {engine.canStretch && (
          <div className="segmented" role="group" aria-label="Speed">
            {RATES.map((rate: Rate) => (
              <Button key={rate} pressed={state.rate === rate} onClick={() => engine.setRate(rate)}>
                {rate}×
              </Button>
            ))}
          </div>
        )}

        <div className="loop" role="group" aria-label="Loop">
          <Button pressed={a !== null} onClick={() => engine.setLoopPoint("a")} label={start.label}>
            {start.text}
          </Button>
          <Button pressed={b !== null} onClick={() => engine.setLoopPoint("b")} label={end.label}>
            {end.text}
          </Button>
          <Button onClick={() => engine.clearLoop()} label="Clear loop">
            ×
          </Button>
        </div>

        <div className="segmented" role="group" aria-label="Audio">
          {SOURCES.map(([source, text]) => (
            <Button
              key={source}
              pressed={state.source === source}
              onClick={() => engine.setSource(source)}
            >
              {text}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
