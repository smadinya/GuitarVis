// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { Profiler } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { details, Header, tuningName } from "./Header";

const FIRST_SONG: TabDocument = firstSongJson;

const song = (fields: Partial<TabDocument> = {}) => buildSong({ ...FIRST_SONG, ...fields });

describe("details", () => {
  it("gives the length, the tuning and the tempo", () => {
    expect(details(song(), 13.871)).toBe("0:13 · Standard tuning · about 117 bpm");
  });

  it("gives the length it is handed", () => {
    expect(details(song(), 203)).toBe("3:23 · Standard tuning · about 117 bpm");
  });

  it("leaves out a tempo the document lacks", () => {
    expect(details(song({ timing: {} }), 13.871)).toBe("0:13 · Standard tuning");
  });

  it("names a tuning that is not standard by its strings", () => {
    expect(details(song({ instrument: { tuning: ["D2", "A2", "D3", "G3", "B3", "E4"] } }), 13.871)).toBe(
      "0:13 · D A D G B E tuning · about 117 bpm",
    );
  });
});

describe("tuningName", () => {
  it("calls the standard tuning standard", () => {
    expect(tuningName(["E2", "A2", "D3", "G3", "B3", "E4"])).toBe("Standard tuning");
  });

  it("names a tuning by the pitch of each string, with its accidental", () => {
    expect(tuningName(["Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"])).toBe("Eb Ab Db Gb Bb Eb tuning");
  });

  it("keeps the top string's capital where it shares a letter with the bottom one", () => {
    expect(tuningName(["D2", "A2", "D3", "G3", "A3", "D4"])).toBe("D A D G A D tuning");
    expect(tuningName(["D2", "A2", "D3", "G3", "B3", "E4"])).toBe("D A D G B E tuning");
  });
});

describe("Header", () => {
  it("titles the page, links back to the upload page, and offers the views", () => {
    render(<Header song={song()} engine={null} view="3d" onView={() => {}} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Test");
    expect(screen.getByRole("link", { name: "Upload another song" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
  });

  it("gives the document's length while there is no engine", () => {
    render(<Header song={song()} engine={null} view="3d" onView={() => {}} />);

    expect(screen.getByText(/^0:13 · /)).toBeTruthy();
  });

  it("gives the length the transport shows: the media's own, once it reports one", () => {
    const doc = song();
    const { engine, media } = fakeEngine(doc);
    render(<Header song={doc} engine={engine} view="3d" onView={() => {}} />);
    expect(screen.getByText(/^0:13 · /)).toBeTruthy();

    act(() => media.loadMetadata(203)); // the file is longer than the document says

    expect(engine.getState().duration).toBe(203);
    expect(screen.getByText(/^3:23 · /)).toBeTruthy();
  });

  it("renders again when the length changes, not at the readout's rate", () => {
    const doc = song();
    const { engine, media, at } = fakeEngine(doc);
    const onRender = vi.fn();
    render(
      <Profiler id="header" onRender={onRender}>
        <Header song={doc} engine={engine} view="3d" onView={() => {}} />
      </Profiler>,
    );
    const renders = onRender.mock.calls.length;

    at(1);
    at(2.5);
    act(() => void engine.setRate(0.5));
    expect(engine.getState().time).toBe(2.5);
    expect(onRender).toHaveBeenCalledTimes(renders);

    act(() => media.loadMetadata(203));
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
  });
});
