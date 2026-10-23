// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Player } from "./Player";
import { VIEW_KEY } from "./ViewSwitch";

const FIRST_SONG: TabDocument = firstSongJson;

// The factory runs when the module is first imported, which is when React.lazy
// fetches the chunk.
const loaded = vi.hoisted(() => vi.fn());
vi.mock("../guitar/Guitar", () => {
  loaded();
  return { Guitar: () => <p>guitar stand-in</p> };
});

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

it("fetches the guitar's chunk only once a guitar view is chosen", async () => {
  localStorage.setItem(VIEW_KEY, "tab");
  const media = new FakeMedia();
  render(<Player song={buildSong(FIRST_SONG)} jobId={JOB_ID} createMedia={() => media} />);
  await act(async () => {});

  expect(screen.queryByText("guitar stand-in")).toBeNull();
  expect(loaded).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "3D" }));
  expect(await screen.findByText("guitar stand-in")).toBeTruthy();
  expect(loaded).toHaveBeenCalledTimes(1);
});
