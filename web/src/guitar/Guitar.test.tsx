// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GUITAR_FAILED } from "../labels";
import { PlaybackEngine } from "../playback/engine";
import { GuitarBoundary } from "../player/GuitarBoundary";
import { buildSong, type Song } from "../song";
import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Guitar, NO_WEBGL, VIEW_KEY } from "./Guitar";
import { LOST_GRACE_MS, type Renderer } from "./stage";

const FIRST_SONG: TabDocument = firstSongJson;

/** Three weak notes in a row hide their passage; an Am sounds over it. */
const HIDDEN_AM: TabDocument = {
  ...FIRST_SONG,
  notes: [1, 1.3, 1.6].map((t, i) => ({ id: `w${i}`, t, dur: 0.25, midi: 57, string: 2, fret: 7, confidence: 0.05 })),
  chords: [{ t: 1, dur: 1, symbol: "Am", confidence: 0.9 }],
};

/** Stands in for three's WebGLRenderer: jsdom has no WebGL. */
function fakeRenderer() {
  return { setPixelRatio: vi.fn(), setSize: vi.fn(), render: vi.fn(), dispose: vi.fn(), forceContextLoss: vi.fn() };
}

/** An engine whose animation frames run only when flushed. */
function engineFor(song: Song) {
  const frames = new FakeFrames();
  const engine = new PlaybackEngine({
    media: new FakeMedia(),
    jobId: JOB_ID,
    duration: song.duration,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  return { engine, frames };
}

function mount(
  doc: TabDocument = FIRST_SONG,
  renderer: ReturnType<typeof fakeRenderer> = fakeRenderer(),
  createRenderer: (canvas: HTMLCanvasElement) => Renderer = () => renderer,
) {
  const song = buildSong(doc);
  const { engine, frames } = engineFor(song);
  // The Stage's own frames are the browser's animation frames: these.
  const own = new FakeFrames();
  vi.stubGlobal("requestAnimationFrame", own.request);
  vi.stubGlobal("cancelAnimationFrame", own.cancel);
  const view = render(<Guitar song={song} engine={engine} createRenderer={createRenderer} />);
  /** Move the song to `t` and run the frames that draw it: the engine's, then
   * the Stage's own, which draws at `t` when one was pending. */
  const at = (t: number) => {
    engine.seek(t);
    frames.flush();
    own.flush();
  };
  return { engine, renderer, view, at };
}

/** Fake only the timers. The animation frames stay the stubs mount() sets. */
function fakeTimers() {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
}

/** Let `ms` pass on the faked timers. */
function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

const button = (name: string) => screen.getByRole("button", { name });
const overlayOf = (container: HTMLElement) => container.querySelector(".guitar-message") as HTMLElement;

describe("Guitar", () => {
  beforeEach(() => {
    // jsdom has no canvas: the painters fall back to blank textures.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("draws each engine frame, and on unmount unsubscribes and disposes the renderer", () => {
    const song = buildSong(FIRST_SONG);
    const { engine, frames } = engineFor(song);
    const stopped = vi.fn();
    const onFrame = engine.onFrame.bind(engine);
    vi.spyOn(engine, "onFrame").mockImplementation((listener) => {
      const stop = onFrame(listener);
      return () => {
        stopped();
        stop();
      };
    });
    const renderer = fakeRenderer();

    const view = render(<Guitar song={song} engine={engine} createRenderer={() => renderer} />);
    engine.seek(1);
    frames.flush();
    expect(engine.onFrame).toHaveBeenCalledTimes(1);
    expect(renderer.render).toHaveBeenCalled();

    view.unmount();
    expect(stopped).toHaveBeenCalledTimes(1);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);
  });

  it("opens in 3D on a first visit", () => {
    mount();

    expect(button("3D").getAttribute("aria-pressed")).toBe("true");
    expect(button("2D").getAttribute("aria-pressed")).toBe("false");
  });

  it("switches views from the toggle, and remembers the choice", () => {
    const { view } = mount();

    fireEvent.click(button("2D"));
    expect(button("2D").getAttribute("aria-pressed")).toBe("true");
    expect(button("3D").getAttribute("aria-pressed")).toBe("false");
    expect(localStorage.getItem(VIEW_KEY)).toBe("2d");

    view.unmount();
    mount();
    expect(button("2D").getAttribute("aria-pressed")).toBe("true");
  });

  it("opens in 3D when the browser's storage throws, and still switches", () => {
    const denied = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(denied);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(denied);

    mount();
    expect(button("3D").getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(button("2D"));
    expect(button("2D").getAttribute("aria-pressed")).toBe("true");
  });

  it("ignores a stored view it does not know", () => {
    localStorage.setItem(VIEW_KEY, "4d");

    mount();

    expect(button("3D").getAttribute("aria-pressed")).toBe("true");
  });

  it("keeps a mouse click on the toggle from taking focus", () => {
    mount();

    // fireEvent returns false when a handler called preventDefault.
    expect(fireEvent.mouseDown(button("2D"))).toBe(false);
    expect(fireEvent.mouseDown(button("Reset view"))).toBe(false);
  });

  it("says the guitar needs WebGL when the renderer cannot be made, and offers no camera buttons", () => {
    const renderer = fakeRenderer();
    const noWebGL = () => {
      throw new Error("Error creating WebGL context.");
    };

    expect(() => mount(FIRST_SONG, renderer, noWebGL)).not.toThrow();

    expect(screen.getByText(NO_WEBGL)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reset view" })).toBeNull();
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
    expect(screen.getByRole("img", { name: "Guitar" })).toBeTruthy();
  });

  it("disposes the renderer when the Stage throws, and leaves the error to the boundary, not to WebGL", () => {
    // React raises a caught error as an error event first. Handling it keeps
    // jsdom from printing it as uncaught.
    const swallow = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", swallow);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const song = buildSong(FIRST_SONG);
    const { engine } = engineFor(song);
    // The Stage's constructor subscribes to the engine last.
    vi.spyOn(engine, "onFrame").mockImplementation(() => {
      throw new Error("a bug in the Stage");
    });
    const renderer = fakeRenderer();

    try {
      render(
        <GuitarBoundary>
          <Guitar song={song} engine={engine} createRenderer={() => renderer} />
        </GuitarBoundary>,
      );
    } finally {
      window.removeEventListener("error", swallow);
    }

    expect(renderer.dispose).toHaveBeenCalledTimes(1);
    expect(renderer.forceContextLoss).toHaveBeenCalledTimes(1);
    expect(screen.getByText(GUITAR_FAILED)).toBeTruthy();
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
  });

  it("releases the WebGL context when the guitar unmounts, once the renderer is disposed", () => {
    const renderer = fakeRenderer();
    const { view } = mount(FIRST_SONG, renderer);
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();

    view.unmount();

    expect(renderer.forceContextLoss).toHaveBeenCalledTimes(1);
    const [disposed] = renderer.dispose.mock.invocationCallOrder;
    const [released] = renderer.forceContextLoss.mock.invocationCallOrder;
    expect(disposed).toBeLessThan(released);
  });

  it("keeps the WebGL context when a new song rebuilds the Stage on the same canvas", () => {
    const first = fakeRenderer();
    const second = fakeRenderer();
    const renderers = [first, second];
    const createRenderer = () => renderers.shift() ?? fakeRenderer();
    const { engine, view } = mount(FIRST_SONG, first, createRenderer);

    view.rerender(<Guitar song={buildSong(FIRST_SONG)} engine={engine} createRenderer={createRenderer} />);
    expect(first.dispose).toHaveBeenCalledTimes(1);
    expect(first.forceContextLoss).not.toHaveBeenCalled();

    view.unmount();
    expect(first.forceContextLoss).not.toHaveBeenCalled();
    expect(second.forceContextLoss).toHaveBeenCalledTimes(1);
  });

  it("keeps the WebGL context through StrictMode's rehearsed unmount, and releases it on the real one", () => {
    const song = buildSong(FIRST_SONG);
    const { engine } = engineFor(song);
    const made: Array<ReturnType<typeof fakeRenderer>> = [];
    const createRenderer = () => {
      const renderer = fakeRenderer();
      made.push(renderer);
      return renderer;
    };

    const view = render(
      <StrictMode>
        <Guitar song={song} engine={engine} createRenderer={createRenderer} />
      </StrictMode>,
    );
    // Mounted, unmounted and mounted again, on one canvas.
    expect(made).toHaveLength(2);
    expect(made[0].dispose).toHaveBeenCalledTimes(1);
    expect(made[0].forceContextLoss).not.toHaveBeenCalled();
    expect(made[1].forceContextLoss).not.toHaveBeenCalled();

    view.unmount();
    expect(made[0].forceContextLoss).not.toHaveBeenCalled();
    expect(made[1].forceContextLoss).toHaveBeenCalledTimes(1);
  });

  it("says so once the WebGL context has stayed lost for the grace, and clears it once restored", () => {
    fakeTimers();
    mount();
    const canvas = screen.getByRole("img", { name: "Guitar" });

    fireEvent(canvas, new Event("webglcontextlost"));
    wait(LOST_GRACE_MS - 1);
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(button("Reset view")).toBeTruthy();
    wait(1);
    expect(screen.getByText(NO_WEBGL)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reset view" })).toBeNull();

    fireEvent(canvas, new Event("webglcontextrestored"));
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(button("Reset view")).toBeTruthy();
  });

  it("keeps the guitar up through a loss that is restored within the grace", () => {
    fakeTimers();
    mount();
    const canvas = screen.getByRole("img", { name: "Guitar" });

    fireEvent(canvas, new Event("webglcontextlost"));
    wait(LOST_GRACE_MS / 2);
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    fireEvent(canvas, new Event("webglcontextrestored"));
    wait(LOST_GRACE_MS * 2);

    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(button("Reset view")).toBeTruthy();
  });

  it("clears the WebGL message when a new song rebuilds the Stage", () => {
    fakeTimers();
    const renderer = fakeRenderer();
    const createRenderer = () => renderer;
    const { engine, view } = mount(FIRST_SONG, renderer, createRenderer);

    fireEvent(screen.getByRole("img", { name: "Guitar" }), new Event("webglcontextlost"));
    wait(LOST_GRACE_MS);
    expect(screen.getByText(NO_WEBGL)).toBeTruthy();

    // The old Stage, and its restore listener, go with the old song.
    view.rerender(<Guitar song={buildSong(FIRST_SONG)} engine={engine} createRenderer={createRenderer} />);

    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
    expect(button("Reset view")).toBeTruthy();
  });

  it("says the guitar stopped when a draw throws, in place of its buttons", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const renderer = fakeRenderer();
    renderer.render.mockImplementation(() => {
      throw new Error("a bug in the draw");
    });
    const { at } = mount(FIRST_SONG, renderer);

    act(() => at(1));

    expect(screen.getByText(GUITAR_FAILED)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reset view" })).toBeNull();
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
  });

  it("says the guitar stopped, not that WebGL is missing, when a draw throws while the context is lost", () => {
    fakeTimers();
    vi.spyOn(console, "error").mockImplementation(() => {});
    const renderer = fakeRenderer();
    const { at } = mount(FIRST_SONG, renderer);
    fireEvent(screen.getByRole("img", { name: "Guitar" }), new Event("webglcontextlost"));
    wait(LOST_GRACE_MS);
    expect(screen.getByText(NO_WEBGL)).toBeTruthy();

    renderer.render.mockImplementation(() => {
      throw new Error("a bug in the draw");
    });
    act(() => at(1));

    expect(screen.getByText(GUITAR_FAILED)).toBeTruthy();
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
  });

  it("brings the guitar back when a new song rebuilds the Stage after a failure", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const broken = fakeRenderer();
    broken.render.mockImplementation(() => {
      throw new Error("a bug in the draw");
    });
    const renderers = [broken, fakeRenderer()];
    const createRenderer = () => renderers.shift() ?? fakeRenderer();
    const { engine, view, at } = mount(FIRST_SONG, broken, createRenderer);
    act(() => at(1));
    expect(screen.getByText(GUITAR_FAILED)).toBeTruthy();

    view.rerender(<Guitar song={buildSong(FIRST_SONG)} engine={engine} createRenderer={createRenderer} />);

    expect(screen.queryByText(GUITAR_FAILED)).toBeNull();
    expect(button("Reset view")).toBeTruthy();
  });

  it("shows a hidden passage's chord in the overlay, and nothing outside it", () => {
    const { view, at } = mount(HIDDEN_AM);
    const overlay = overlayOf(view.container);

    at(1.2);
    expect(overlay.hidden).toBe(false);
    expect(overlay.textContent).toBe("Am");
    expect(overlay.classList.contains("chord")).toBe(true);
    expect(overlay.style.opacity).toBe("1");

    at(5);
    expect(overlay.hidden).toBe(true);
  });

  it("shows the empty message for a document with no notes", () => {
    const { view, at } = mount({ ...FIRST_SONG, notes: [] });
    const overlay = overlayOf(view.container);

    at(0);

    expect(overlay.hidden).toBe(false);
    expect(overlay.textContent).toBe("No notes to show");
    expect(overlay.classList.contains("chord")).toBe(false);
  });
});
