// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NO_WEBGL } from "../guitar/Guitar";
import { buildSong } from "../song";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Player } from "./Player";

const FIRST_SONG: TabDocument = firstSongJson;

function mount(fields: Partial<TabDocument> = {}, media = new FakeMedia()) {
  const createMedia = () => media;
  render(<Player song={buildSong({ ...FIRST_SONG, ...fields })} jobId={JOB_ID} createMedia={createMedia} />);
  act(() => media.loadMetadata(13.871));
  return media;
}

function press(key: string, target: Element | Window = window) {
  act(() => {
    fireEvent.keyDown(target, { key });
  });
}

describe("Player", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // The chosen view persists, so one test's choice must not reach the next.
    localStorage.clear();
  });

  it("shows its header, with the title, before its engine exists", () => {
    // Effects do not run in a server render, so this is the render before the
    // engine effect has: the one a song page would paint if it dropped its own
    // title as soon as the document was ready.
    const html = renderToString(
      <Player song={buildSong(FIRST_SONG)} jobId={JOB_ID} createMedia={() => new FakeMedia()} />,
    );

    expect(html).toMatch(/<h1>Test<\/h1>/);
    expect(html).not.toContain("Transport");
  });

  it("plays and pauses on Space, and seeks on the arrows", () => {
    const media = mount();

    press(" ");
    expect(media.paused).toBe(false);
    press("ArrowRight");
    expect(media.currentTime).toBeCloseTo(5, 1); // plus the moment it has been playing
    press("ArrowLeft");
    expect(media.currentTime).toBeCloseTo(0, 1);
    press(" ");
    expect(media.paused).toBe(true);
  });

  it("leaves keys typed into a text field alone", () => {
    const media = mount();
    const field = document.createElement("input");
    document.body.append(field);

    press(" ", field);
    press("ArrowRight", field);

    expect(media.paused).toBe(true);
    expect(media.currentTime).toBe(0);
    field.remove();
  });

  it("leaves Space to a button that has keyboard focus", () => {
    const media = mount();

    press(" ", screen.getByRole("button", { name: "Guitar only" }));

    expect(media.paused).toBe(true);
  });

  it("sizes the tab strip's canvas to its container, whatever the stylesheet says", () => {
    mount();

    // The painter sets the bitmap's width from the CSS width. A canvas left
    // at its intrinsic width would grow on every resize pass on a 2x display.
    const strip = screen.getByLabelText("Tab");

    expect(strip.style.width).toBe("100%");
    expect(strip.style.display).toBe("block");
  });

  it("makes the canvas's CSS height the bitmap's height, so no frame is resampled", () => {
    mount();

    // `* { box-sizing: border-box }` would make the inline height include any
    // border, leaving the content box shorter than the bitmap.
    const strip = screen.getByLabelText("Tab");

    expect(strip.style.boxSizing).toBe("content-box");
    expect(strip.style.height).toMatch(/^\d+px$/);
  });

  it("shows the guitar above the tab strip", async () => {
    mount();

    const guitar = await screen.findByRole("img", { name: "Guitar" });
    const strip = screen.getByLabelText("Tab");

    expect(guitar.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lays out the header, then warnings, guitar, chord lane and tab strip, with the sections after them, and the transport last", async () => {
    mount({ warnings: ["w"] });
    const order = [
      screen.getByRole("heading", { level: 1 }),
      screen.getByRole("complementary", { name: "Warnings" }),
      await screen.findByRole("img", { name: "Guitar" }),
      screen.getByRole("list", { name: "Chord lane" }),
      screen.getByLabelText("Tab"),
      screen.getByRole("complementary", { name: "Sections" }),
      screen.getByRole("region", { name: "Transport" }),
    ];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("keeps playing from its controls when the guitar has no WebGL", async () => {
    const media = mount();

    await screen.findByText(NO_WEBGL); // jsdom has none

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(media.paused).toBe(false);
  });

  it("shows the document's warnings", () => {
    mount({ warnings: ["Chord detection failed, so this tab has no chords."] });
    expect(screen.getByRole("complementary", { name: "Warnings" }).textContent).toContain(
      "Chord detection failed",
    );
  });

  it("shows no warnings box for a clean document", () => {
    mount({ warnings: [] });

    expect(screen.queryByRole("complementary", { name: "Warnings" })).toBeNull();
  });

  it("keeps the audio playing on one engine through a switch to Tab only and back", async () => {
    const media = mount();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    // The guitar's chunk loads lazily: without waiting for it, the null check
    // below would hold whether or not Tab only had unmounted anything.
    await screen.findByRole("img", { name: "Guitar" });
    const loads = media.loads.length;

    fireEvent.click(screen.getByRole("button", { name: "Tab only" }));
    expect(screen.queryByRole("img", { name: "Guitar" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "3D" }));
    await screen.findByRole("img", { name: "Guitar" });

    expect(media.paused).toBe(false);
    expect(media.loads).toHaveLength(loads);
  });

  it("keeps the chord lane in Tab only", async () => {
    mount();
    // Wait for the guitar, or the null check below holds whatever Tab only does.
    await screen.findByRole("img", { name: "Guitar" });

    fireEvent.click(screen.getByRole("button", { name: "Tab only" }));

    expect(screen.getByRole("list", { name: "Chord lane" })).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Guitar" })).toBeNull();
  });
});
