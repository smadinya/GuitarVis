// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { details, Header } from "./Header";

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

describe("Header", () => {
  it("titles the page, links back to the upload page, and offers the views", () => {
    render(<Header song={song()} view="3d" onView={() => {}} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Test");
    expect(screen.getByRole("link", { name: "Upload another song" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
  });
});
