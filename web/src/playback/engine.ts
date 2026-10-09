/**
 * The PlaybackEngine: the one owner of the audio, and the one source of the
 * current time.
 *
 * It owns a single media element. Native time-stretching exists only on media
 * elements, which is what makes slow-down nearly free (ADR 0008). Views never
 * touch the element: they draw from `onFrame`, and the controls read
 * `getState` through useSyncExternalStore.
 */
import { MediaClock, type MediaLike } from "./clock";

export type Source = "mix" | "guitar";
export const RATES = [0.5, 0.75, 1] as const;
export type Rate = (typeof RATES)[number];

export const SEEK_STEP_SEC = 5;
export const MIN_LOOP_SEC = 0.5;
/** Consecutive media errors before the engine stops retrying. */
export const MAX_FAILURES = 3;
/** The time readout in the state moves in steps of about this (about 4 Hz). */
const READOUT_SEC = 0.25;

/** Loop points in song seconds. Both set means a loop. */
export interface LoopPoints {
  a: number | null;
  b: number | null;
}

export interface EngineState {
  playing: boolean;
  rate: Rate;
  source: Source;
  loop: LoopPoints;
  duration: number;
  buffering: boolean;
  error: "connection_lost" | null;
  /** The current time, updated about four times a second. Draw from onFrame. */
  time: number;
}

export interface EngineOptions {
  media: MediaLike;
  jobId: string;
  /** source.duration_sec, used until the media reports its own. */
  duration: number;
  /** performance.now(), injectable for tests. */
  now?: () => number;
  requestFrame?: (callback: () => void) => number;
  cancelFrame?: (id: number) => void;
}

/** The api path, never the presigned URL it redirects to: requesting the
 * path again is how an expired URL is replaced. */
export function audioUrl(jobId: string, source: Source): string {
  return `/jobs/${encodeURIComponent(jobId)}/audio/${source}`;
}

interface Pending {
  at: number;
  resume: boolean;
}

export class PlaybackEngine {
  /** Whether the browser can change speed without changing pitch. */
  readonly canStretch: boolean;
  private readonly media: MediaLike;
  private readonly jobId: string;
  private readonly clock: MediaClock;
  private readonly requestFrame: (callback: () => void) => number;
  private readonly cancelFrame: (id: number) => void;
  private readonly frameListeners = new Set<(t: number) => void>();
  private readonly stateListeners = new Set<() => void>();
  private readonly unlisten: Array<() => void> = [];
  private state: EngineState;
  private frame: number | null = null;
  /** A source being loaded: where to seek once it has metadata, and whether to play. */
  private pending: Pending | null = null;
  private failures = 0;
  /** The time at the last loop check. */
  private previous = 0;
  private disposed = false;

  constructor(options: EngineOptions) {
    this.media = options.media;
    this.jobId = options.jobId;
    this.canStretch = "preservesPitch" in this.media || "webkitPreservesPitch" in this.media;
    this.clock = new MediaClock(this.media, options.now);
    this.requestFrame =
      options.requestFrame ?? ((callback) => requestAnimationFrame(() => callback()));
    this.cancelFrame = options.cancelFrame ?? ((id) => cancelAnimationFrame(id));
    this.state = {
      playing: false,
      rate: 1,
      source: "mix",
      loop: { a: null, b: null },
      duration: options.duration,
      buffering: false,
      error: null,
      time: 0,
    };

    this.listen("loadedmetadata", () => this.onMetadata());
    this.listen("durationchange", () => this.syncDuration());
    this.listen("canplay", () => {
      this.failures = 0;
      this.update({ buffering: false });
    });
    this.listen("waiting", () => this.update({ buffering: true }));
    this.listen("playing", () => this.update({ buffering: false }));
    this.listen("play", () => this.syncPlaying());
    this.listen("pause", () => this.syncPlaying());
    this.listen("ended", () => this.onEnded());
    // Animation frames stop in a background tab; timeupdate does not, so the
    // loop holds there too.
    this.listen("timeupdate", () => this.tick());
    this.listen("error", () => this.onError());

    this.applyRate(1);
    this.load(0, false);
  }

  // --- for views and controls --------------------------------------------

  /** Call `listener` with the time on every frame while playing, and once
   * after any change while paused. Every listener gets the same t. */
  onFrame(listener: (t: number) => void): () => void {
    this.frameListeners.add(listener);
    this.redraw();
    return () => this.frameListeners.delete(listener);
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  };

  readonly getState = (): EngineState => this.state;

  /** Ask for one frame, e.g. after the canvas changed size. */
  redraw(): void {
    if (this.frame === null && !this.disposed) {
      this.frame = this.requestFrame(() => this.runFrame());
    }
  }

  // --- transport ------------------------------------------------------------

  play(): void {
    if (this.state.error !== null) return;
    if (this.pending !== null) {
      this.pending.resume = true;
      this.syncPlaying();
      return;
    }
    if (this.media.ended) this.seek(0);
    this.media.play().catch(() => this.syncPlaying());
  }

  pause(): void {
    if (this.pending !== null) {
      this.pending.resume = false;
      this.syncPlaying();
      return;
    }
    this.media.pause();
  }

  toggle(): void {
    if (this.state.playing) this.pause();
    else this.play();
  }

  seek(t: number): void {
    const target = Math.min(Math.max(t, 0), this.state.duration);
    this.previous = target;
    if (this.pending !== null) {
      this.pending.at = target;
    } else {
      this.media.currentTime = target;
      this.clock.jump();
    }
    this.update({ time: target });
    this.redraw();
  }

  seekBy(seconds: number): void {
    this.seek(this.time() + seconds);
  }

  setRate(rate: Rate): void {
    this.applyRate(rate);
    this.update({ rate });
  }

  /** Switch between the mix and the guitar stem, keeping time, play state
   * and rate. Costs a short gap while the other file loads. */
  setSource(source: Source): void {
    if (source === this.state.source || this.state.error !== null) return;
    const resume = this.state.playing;
    const at = this.time();
    this.update({ source });
    this.load(at, resume);
  }

  // --- the A/B loop ---------------------------------------------------------

  /** Set A or B at the current time. Refused, returning false, when it would
   * sit less than MIN_LOOP_SEC from the other point. */
  setLoopPoint(point: "a" | "b"): boolean {
    const t = this.time();
    const other = point === "a" ? this.state.loop.b : this.state.loop.a;
    if (other !== null && Math.abs(t - other) < MIN_LOOP_SEC) return false;
    this.update({ loop: { ...this.state.loop, [point]: t } });
    return true;
  }

  clearLoop(): void {
    this.update({ loop: { a: null, b: null } });
  }

  dispose(): void {
    this.disposed = true;
    if (this.frame !== null) this.cancelFrame(this.frame);
    this.frame = null;
    for (const unlisten of this.unlisten) unlisten();
    this.clock.dispose();
    this.media.pause();
    this.frameListeners.clear();
    this.stateListeners.clear();
  }

  // --- internals ------------------------------------------------------------

  /** The time to draw: held still while a source loads. */
  private time(): number {
    return this.pending?.at ?? this.clock.now();
  }

  private runFrame(): void {
    this.frame = null;
    const t = this.tick();
    for (const listener of this.frameListeners) listener(t);
    if (this.state.playing && this.pending === null) this.redraw();
  }

  /** Enforce the loop, refresh the readout, and return the time. */
  private tick(): number {
    const t = this.time();
    const loop = this.loopRange();
    if (loop !== null && this.pending === null) {
      const [a, b] = loop;
      // Only playback crossing B from inside the loop jumps back. Seeking
      // past B releases the loop; seeking before A plays into it.
      if (this.previous >= a && this.previous < b && t >= b) {
        this.seek(a);
        return a;
      }
    }
    this.previous = t;
    if (Math.abs(t - this.state.time) >= READOUT_SEC) this.update({ time: t });
    return t;
  }

  private loopRange(): [number, number] | null {
    const { a, b } = this.state.loop;
    return a === null || b === null ? null : [Math.min(a, b), Math.max(a, b)];
  }

  private load(at: number, resume: boolean): void {
    this.pending = { at, resume };
    this.media.src = audioUrl(this.jobId, this.state.source);
    this.syncPlaying();
  }

  private onMetadata(): void {
    this.syncDuration();
    const pending = this.pending;
    if (pending === null) return;
    this.pending = null;
    this.media.currentTime = pending.at;
    this.clock.jump();
    this.previous = pending.at;
    if (pending.resume) this.media.play().catch(() => this.syncPlaying());
    this.syncPlaying();
    // The frame loop stops while a source loads. Do not rely on the element's
    // waiting and playing events to start it again.
    this.redraw();
  }

  private onEnded(): void {
    const loop = this.loopRange();
    // A loop whose B is the very end keeps looping.
    if (loop !== null && this.previous >= loop[0] && this.previous <= loop[1]) {
      this.seek(loop[0]);
      this.play();
      return;
    }
    this.syncPlaying();
  }

  /** A network error, most likely an expired presigned URL: ask the api again. */
  private onError(): void {
    const at = this.time();
    const resume = this.state.playing;
    this.failures += 1;
    if (this.failures >= MAX_FAILURES) {
      this.pending = null;
      this.media.pause();
      this.update({ error: "connection_lost", playing: false, buffering: false });
      return;
    }
    this.load(at, resume);
  }

  private applyRate(rate: Rate): void {
    // The load algorithm resets playbackRate to the default on every src
    // change, so both are set, or the toggle would undo a speed change.
    this.media.defaultPlaybackRate = rate;
    this.media.playbackRate = rate;
    this.media.preservesPitch = true;
    if ("webkitPreservesPitch" in this.media) {
      (this.media as { webkitPreservesPitch: boolean }).webkitPreservesPitch = true;
    }
  }

  private syncPlaying(): void {
    this.update({ playing: this.pending?.resume ?? !this.media.paused });
  }

  private syncDuration(): void {
    const duration = this.media.duration;
    if (Number.isFinite(duration) && duration > 0) this.update({ duration });
  }

  private listen(type: string, listener: () => void): void {
    this.media.addEventListener(type, listener);
    this.unlisten.push(() => this.media.removeEventListener(type, listener));
  }

  private update(patch: Partial<EngineState>): void {
    const changed = (Object.keys(patch) as Array<keyof EngineState>).some(
      (key) => patch[key] !== this.state[key],
    );
    if (!changed) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.stateListeners) listener();
    this.redraw();
  }
}
