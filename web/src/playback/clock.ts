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
  preload: string;
  play(): Promise<void>;
  pause(): void;
  load(): void;
  removeAttribute(name: string): void;
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

/** How far extrapolation may drift from a new media reading before it snaps to it. */
export const MAX_DRIFT_SEC = 0.05;
/**
 * How far extrapolation may run past the last media reading. Some browsers
 * update media time only as often as timeupdate fires, which the HTML spec
 * lets fall 250 ms apart, so the strip must be free to run that far on its
 * own. Past it, the element has stalled without saying so, and the strip
 * waits for it.
 */
export const MAX_LEAD_SEC = 0.25 + MAX_DRIFT_SEC;

/** Events that mark a break in playback: the clock starts again from the
 * element's time. timeupdate is not one of them: it is only a reading. */
const ANCHORING_EVENTS = ["seeked", "ratechange", "play", "pause", "waiting", "playing"] as const;

export class MediaClock implements Clock {
  private readonly media: MediaLike;
  private readonly perf: () => number;
  private readonly listeners: Array<[string, () => void]>;
  private anchorTime = 0; // media seconds at the anchor
  private anchorAt = 0; // perf() milliseconds at the anchor
  private reading = 0; // the media time last read
  private waiting = false;
  private last = 0;
  private mayGoBack = true;

  /** `perf` is performance.now(), injected so tests control it. */
  constructor(media: MediaLike, perf: () => number = () => performance.now()) {
    this.media = media;
    this.perf = perf;
    this.listeners = [
      ...ANCHORING_EVENTS.map((type): [string, () => void] => [type, () => this.observe(type)]),
      ["timeupdate", () => this.read()],
    ];
    for (const [type, listener] of this.listeners) media.addEventListener(type, listener);
    this.anchor();
  }

  now(): number {
    if (this.media.paused || this.waiting) {
      // Exactly what is heard, so a pause or a stall leaves the strip where
      // the audio stopped, not where extrapolation had got to.
      const t = this.media.currentTime;
      this.mayGoBack = false;
      this.last = t;
      return t;
    }
    this.read();
    let t = Math.min(this.extrapolate(), this.reading + MAX_LEAD_SEC);
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

  /**
   * Take a new media reading, if there is one. A reading can be up to 250 ms
   * old, and is never ahead of where playback really is. So one ahead of the
   * extrapolation corrects it, and one behind it does so only past the drift
   * allowance. An unchanged reading says nothing.
   */
  private read(): void {
    const media = this.media.currentTime;
    if (media === this.reading) return;
    this.reading = media;
    const error = media - this.extrapolate();
    if (error > 0 || error < -MAX_DRIFT_SEC) this.anchor();
  }

  private extrapolate(): number {
    const elapsed = (this.perf() - this.anchorAt) / 1000;
    return this.anchorTime + elapsed * this.media.playbackRate;
  }

  private anchor(): void {
    this.anchorTime = this.media.currentTime;
    this.anchorAt = this.perf();
    this.reading = this.anchorTime;
  }
}
