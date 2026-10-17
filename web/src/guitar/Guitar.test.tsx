// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
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
import type { Renderer } from "./stage";

const FIRST_SONG: TabDocument = firstSongJson;

/** Three weak notes in a row hide their passage; an Am sounds over it. */
const HIDDEN_AM: TabDocument = {
  ...FIRST_SONG,
  notes: [1, 1.3, 1.6].map((t, i) => ({ id: `w${i}`, t, dur: 0.25, midi: 57, string: 2, fret: 7, confidence: 0.05 })),
  chords: [{ t: 1, dur: 1, symbol: "Am", confidence: 0.9 }],
};

/** Stands in for three's WebGLRenderer: jsdom has no WebGL. */
function fakeRenderer() {
  return { setPixelRatio: vi.fn(), setSize: vi.fn(), render: vi.fn(), dispose: vi.fn() };
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
  const view = render(<Guitar song={song} engine={engine} createRenderer={createRenderer} />);
  /** Move the song to `t` and run the frame that draws it. */
  const at = (t: number) => {
    engine.seek(t);
    frames.flush();
  };
  return { engine, renderer, view, at };
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
    vi.restoreAllMocks();
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
    expect(screen.getByText(GUITAR_FAILED)).toBeTruthy();
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
  });

  it("says so while the WebGL context is lost, and clears it once restored", () => {
    mount();
    const canvas = screen.getByRole("img", { name: "Guitar" });

    fireEvent(canvas, new Event("webglcontextlost"));
    expect(screen.getByText(NO_WEBGL)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reset view" })).toBeNull();

    fireEvent(canvas, new Event("webglcontextrestored"));
    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(button("Reset view")).toBeTruthy();
  });

  it("clears the WebGL message when a new song rebuilds the Stage", () => {
    const renderer = fakeRenderer();
    const createRenderer = () => renderer;
    const { engine, view } = mount(FIRST_SONG, renderer, createRenderer);

    fireEvent(screen.getByRole("img", { name: "Guitar" }), new Event("webglcontextlost"));
    expect(screen.getByText(NO_WEBGL)).toBeTruthy();

    // The old Stage, and its restore listener, go with the old song.
    view.rerender(<Guitar song={buildSong(FIRST_SONG)} engine={engine} createRenderer={createRenderer} />);

    expect(screen.queryByText(NO_WEBGL)).toBeNull();
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
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
