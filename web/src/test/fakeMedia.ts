/**
 * Test doubles for the playback code: a media element that fires events when
 * told to, and an animation-frame queue flushed by hand.
 */
import type { MediaLike } from "../playback/clock";

export class FakeMedia implements MediaLike {
  currentTime = 0;
  duration = Number.NaN;
  paused = true;
  playbackRate = 1;
  defaultPlaybackRate = 1;
  preservesPitch = false;
  webkitPreservesPitch = false;
  preload = "";
  /** Every src ever set, in order. */
  readonly loads: string[] = [];
  /** Whether the element is fetching a file: from setting src until load()
   * runs with no src. */
  fetching = false;
  /** When set, play() rejects with it, as a browser's autoplay policy may. */
  refusePlay: Error | null = null;
  private source = "";
  private finished = false;
  private readonly listeners = new Map<string, Set<() => void>>();

  /** As in a browser: true only while the position is still at the end. */
  get ended(): boolean {
    return this.finished && this.currentTime >= this.duration;
  }

  get src(): string {
    return this.source;
  }

  set src(value: string) {
    this.source = value;
    this.loads.push(value);
    this.load();
  }

  removeAttribute(name: string): void {
    if (name === "src") this.source = "";
  }

  /** The media load algorithm, as far as the engine can see it. With no src,
   * the element lets go of whatever it was fetching. */
  load(): void {
    this.fetching = this.source !== "";
    this.paused = true;
    this.finished = false;
    this.currentTime = 0;
    this.duration = Number.NaN;
    this.playbackRate = this.defaultPlaybackRate;
    this.emit("emptied");
  }

  play(): Promise<void> {
    if (this.refusePlay !== null) return Promise.reject(this.refusePlay);
    this.paused = false;
    this.finished = false;
    this.emit("play");
    this.emit("playing");
    return Promise.resolve();
  }

  pause(): void {
    if (this.paused) return;
    this.paused = true;
    this.emit("pause");
  }

  addEventListener(type: string, listener: () => void): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: () => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  listenerCount(): number {
    return [...this.listeners.values()].reduce((sum, set) => sum + set.size, 0);
  }

  emit(type: string): void {
    for (const listener of [...(this.listeners.get(type) ?? [])]) listener();
  }

  /** Metadata arrives, then enough data to play. */
  loadMetadata(duration = 180): void {
    this.duration = duration;
    this.emit("durationchange");
    this.emit("loadedmetadata");
    this.emit("canplay");
  }

  /** Playback moves on by `seconds` of song time and reports it. */
  advance(seconds: number): void {
    this.currentTime += seconds;
    this.emit("timeupdate");
  }

  /** Playback reaches the end, as a browser reports it. */
  end(): void {
    this.currentTime = this.duration;
    this.paused = true;
    this.finished = true;
    this.emit("timeupdate");
    this.emit("pause");
    this.emit("ended");
  }
}

/** requestAnimationFrame and cancelAnimationFrame, run by hand. */
export class FakeFrames {
  private readonly queue = new Map<number, () => void>();
  private next = 1;

  readonly request = (callback: () => void): number => {
    const id = this.next++;
    this.queue.set(id, callback);
    return id;
  };

  readonly cancel = (id: number): void => {
    this.queue.delete(id);
  };

  get pending(): number {
    return this.queue.size;
  }

  /** Run the frames queued so far; frames they request wait for the next flush. */
  flush(): void {
    const callbacks = [...this.queue.values()];
    this.queue.clear();
    for (const callback of callbacks) callback();
  }
}
