// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { details, Header, tuningName } from "./Header";

const FIRST_SONG: TabDocument = firstSongJson;

const song = (fields: Partial<TabDocument> = {}) => buildSong({ ...FIRST_SONG, ...fields });

describe("details", () => {
  it("gives the length, the tuning and the tempo", () => {
    expect(details(song())).toBe("0:13 · Standard tuning · about 117 bpm");
  });

  it("leaves out a tempo the document lacks", () => {
    expect(details(song({ timing: {} }))).toBe("0:13 · Standard tuning");
  });

  it("names a tuning that is not standard by its strings", () => {
    expect(details(song({ instrument: { tuning: ["D2", "A2", "D3", "G3", "B3", "E4"] } }))).toBe(
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
    render(<Header song={song()} view="3d" onView={() => {}} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Test");
    expect(screen.getByRole("link", { name: "Upload another song" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
  });
});
