/**
 * Song time, smooth enough to draw from.
 *
 * Media time is coarse in some browsers, and a strip that steps visibly reads
 * as out of sync even when it is not. MediaClock extrapolates between media
 * updates and corrects itself from the element whenever it can.
 */

/**
 * The part of an HTMLMediaElement the playback code uses, so tests can drive
 * a fake one. An HTMLAudioElement satisfies it.
 */
export interface MediaLike {
  src: string;
  currentTime: number;
  readonly duration: number;
  readonly paused: boolean;
  readonly ended: boolean;
  playbackRate: number;
  defaultPlaybackRate: number;
  preservesPitch: boolean;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
}

/** Song seconds, now. */
export interface Clock {
  now(): number;
}

/** A clock a test sets by hand. */
export class FakeClock implements Clock {
  t = 0;

  now(): number {
    return this.t;
  }
}

/** How far extrapolation may drift from media time before it snaps back. */
export const MAX_DRIFT_SEC = 0.05;

const ANCHORING_EVENTS = [
  "timeupdate",
  "seeked",
  "ratechange",
  "play",
  "pause",
  "waiting",
  "playing",
] as const;

export class MediaClock implements Clock {
  private readonly media: MediaLike;
  private readonly perf: () => number;
  private readonly listeners: Array<[string, () => void]>;
  private anchorTime = 0; // media seconds at the anchor
  private anchorAt = 0; // perf() milliseconds at the anchor
  private waiting = false;
  private last = 0;
  private mayGoBack = true;

  /** `perf` is performance.now(), injected so tests control it. */
  constructor(media: MediaLike, perf: () => number = () => performance.now()) {
    this.media = media;
    this.perf = perf;
    this.listeners = ANCHORING_EVENTS.map((type) => [type, () => this.observe(type)]);
    for (const [type, listener] of this.listeners) media.addEventListener(type, listener);
    this.anchor();
  }

  now(): number {
    const media = this.media.currentTime;
    let t = media;
    if (!this.media.paused && !this.waiting) {
      const elapsed = (this.perf() - this.anchorAt) / 1000;
      t = this.anchorTime + elapsed * this.media.playbackRate;
      if (Math.abs(t - media) > MAX_DRIFT_SEC) {
        this.anchor();
        t = media;
      }
    }
    // Small corrections never run the strip backwards. A seek may.
    if (t < this.last && !this.mayGoBack) t = this.last;
    this.mayGoBack = false;
    this.last = t;
    return t;
  }

  /** A seek is under way: let the next reading go backwards. */
  jump(): void {
    this.mayGoBack = true;
    this.anchor();
  }

  dispose(): void {
    for (const [type, listener] of this.listeners) this.media.removeEventListener(type, listener);
  }

  private observe(type: (typeof ANCHORING_EVENTS)[number]): void {
    if (type === "waiting") this.waiting = true;
    if (type === "playing" || type === "pause") this.waiting = false;
    if (type === "seeked") this.mayGoBack = true;
    this.anchor();
  }

  private anchor(): void {
    this.anchorTime = this.media.currentTime;
    this.anchorAt = this.perf();
  }
}
