// @vitest-environment jsdom
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Transport } from "./Transport";

const FIRST_SONG: TabDocument = firstSongJson;

const SECTIONS = [
  { t: 0, dur: 60, label: "Intro" },
  { t: 60, dur: 60, label: "Verse 1" },
];

function mount(fields: Partial<TabDocument> = {}, options: { duration?: number; media?: FakeMedia } = {}) {
  const song = buildSong({ ...FIRST_SONG, ...fields });
  const fake = fakeEngine(song, options);
  render(<Transport song={song} engine={fake.engine} />);
  return fake;
}
const button = (name: string | RegExp) => screen.getByRole("button", { name });

describe("Transport", () => {
  it("plays and pauses from its button", () => {
    const { media } = mount();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    expect(media.paused).toBe(false);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("sets the speed, and shows which is on", () => {
    const { media } = mount();

    fireEvent.click(screen.getByRole("button", { name: "0.5×" }));

    expect(media.playbackRate).toBe(0.5);
    expect(screen.getByRole("button", { name: "0.5×" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers no speed control where pitch cannot be kept", () => {
    const media = new FakeMedia();
    Reflect.deleteProperty(media, "preservesPitch");
    Reflect.deleteProperty(media, "webkitPreservesPitch");

    mount({}, { media });

    expect(screen.queryByRole("group", { name: "Speed" })).toBeNull();
  });

  it("switches to the guitar stem", () => {
    const { media } = mount();

    fireEvent.click(screen.getByRole("button", { name: "Guitar only" }));

    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/guitar`);
  });

  it("says when the audio cannot be played, and offers the other track and a reload", () => {
    const { media } = mount();

    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });

    const alert = screen.getByRole("alert").textContent;
    expect(alert).toContain("We couldn't play this audio.");
    expect(alert).toContain("Try Guitar only, or reload the page.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("suggests the mix when the guitar is what failed", () => {
    const { media } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Guitar only" }));
    act(() => media.loadMetadata(13.871));

    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });

    expect(screen.getByRole("alert").textContent).toContain("Try Full mix, or reload the page.");
  });

  it("keeps the audio toggle usable in the error state, and clears the alert with it", () => {
    const { media } = mount();
    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });
    expect(screen.getByRole("alert")).toBeTruthy();

    const guitar = screen.getByRole("button", { name: "Guitar only" });
    expect((guitar as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(guitar);

    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/guitar`);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Guitar only" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("labels its icon buttons, and seeks five seconds either way", () => {
    const { engine, at } = mount({}, { duration: 120 });
    at(10);
    fireEvent.click(button("Forward 5 seconds"));
    expect(engine.getState().time).toBe(15);
    fireEvent.click(button("Back 5 seconds"));
    expect(engine.getState().time).toBe(10);
    fireEvent.click(button("Play"));
    expect(button("Pause")).toBeTruthy();
  });

  it("shows the loop's times once set, and clears them", () => {
    const { at } = mount({}, { duration: 120 });
    at(40);
    fireEvent.click(button("Set loop start"));
    at(74);
    fireEvent.click(button("Set loop end"));
    expect(button("Set loop start (0:40)").textContent).toBe("A 0:40");
    expect(button("Set loop end (1:14)").textContent).toBe("B 1:14");

    fireEvent.click(button("Clear loop"));
    expect(button("Set loop start").textContent).toBe("A");
    expect(button("Set loop end").textContent).toBe("B");
  });

  it("shows the time with the current section, and the song's length", () => {
    const { at } = mount({ sections: SECTIONS }, { duration: 120 });
    at(67);
    expect(screen.getByText("1:07 · Verse 1")).toBeTruthy();
    expect(screen.getByText("2:00")).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Position" }).getAttribute("aria-valuetext")).toBe("1:07, Verse 1");
  });

  it("puts the audio error above the bar", () => {
    const { media } = mount();
    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });
    const alert = screen.getByRole("alert");
    const slider = screen.getByRole("slider", { name: "Position" });
    expect(alert.compareDocumentPosition(slider) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps a mouse click on any of its buttons from taking focus", () => {
    mount();
    const buttons = within(screen.getByRole("region", { name: "Transport" })).getAllByRole("button");
    expect(buttons).toHaveLength(11);
    for (const b of buttons) expect(fireEvent.mouseDown(b), b.textContent ?? "").toBe(false);
  });
});
