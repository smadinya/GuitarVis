import { useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

import {
  RATES,
  SEEK_STEP_SEC,
  type PlaybackEngine,
  type Rate,
  type Source,
} from "../playback/engine";

const SOURCES: Array<[Source, string]> = [
  ["mix", "Full mix"],
  ["guitar", "Guitar only"],
];

/** The label of the track the player is not on. */
function otherSource(source: Source): string {
  return SOURCES.find(([candidate]) => candidate !== source)?.[1] ?? "the other track";
}

/** A clicked button does not keep focus, so Space stays play/pause rather
 * than clicking the last button again. Keyboard focus still works. */
function keepFocus(event: MouseEvent) {
  event.preventDefault();
}

function Button({
  onClick,
  pressed,
  label,
  children,
}: {
  onClick: () => void;
  pressed?: boolean;
  label?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onMouseDown={keepFocus}
      onClick={onClick}
      aria-pressed={pressed}
      aria-label={label}
    >
      {children}
    </button>
  );
}

export function Controls({ engine }: { engine: PlaybackEngine }) {
  const state = useSyncExternalStore(engine.subscribe, engine.getState);
  const { a, b } = state.loop;

  return (
    <div className="controls">
      <div className="group">
        <Button onClick={() => engine.toggle()}>{state.playing ? "Pause" : "Play"}</Button>
        <Button onClick={() => engine.seekBy(-SEEK_STEP_SEC)} label="Back 5 seconds">
          −5 s
        </Button>
        <Button onClick={() => engine.seekBy(SEEK_STEP_SEC)} label="Forward 5 seconds">
          +5 s
        </Button>
        <span className="time">
          {clock(state.time)} / {clock(state.duration)}
        </span>
        {state.buffering && <span role="status">Buffering…</span>}
      </div>

      {engine.canStretch && (
        <div className="group" role="group" aria-label="Speed">
          {RATES.map((rate: Rate) => (
            <Button key={rate} pressed={state.rate === rate} onClick={() => engine.setRate(rate)}>
              {rate}×
            </Button>
          ))}
        </div>
      )}

      <div className="group" role="group" aria-label="Loop">
        <Button pressed={a !== null} onClick={() => engine.setLoopPoint("a")} label="Set loop start">
          A
        </Button>
        <Button pressed={b !== null} onClick={() => engine.setLoopPoint("b")} label="Set loop end">
          B
        </Button>
        <Button onClick={() => engine.clearLoop()} label="Clear loop">
          ×
        </Button>
      </div>

      <div className="group" role="group" aria-label="Audio">
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

      {state.error === "connection_lost" && (
        <div role="alert">
          <p>
            We couldn't play this audio. Try {otherSource(state.source)}, or reload the page.
          </p>
          <button type="button" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      )}
    </div>
  );
}

/** m:ss */
export function clock(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
