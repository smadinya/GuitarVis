// @vitest-environment jsdom
import { act, fireEvent, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { useTransportKeys } from "./keys";

const FIRST_SONG: TabDocument = firstSongJson;

function setup() {
  const { engine, at } = fakeEngine(buildSong(FIRST_SONG));
  renderHook(() => useTransportKeys(engine));
  return { engine, at };
}

const press = (key: string, init: KeyboardEventInit = {}, target: Element | Window = window) =>
  act(() => {
    fireEvent.keyDown(target, { key, ...init });
  });

describe("useTransportKeys", () => {
  it("sets loop A on [ and B on ], at the current time", () => {
    const { engine, at } = setup();
    at(2);
    press("[");
    at(6);
    press("]");
    expect(engine.getState().loop).toEqual({ a: 2, b: 6 });
  });

  it("leaves [ and ] typed into a text field alone", () => {
    const { engine } = setup();
    const field = document.createElement("input");
    document.body.append(field);
    press("[", {}, field);
    press("]", {}, field);
    expect(engine.getState().loop).toEqual({ a: null, b: null });
    field.remove();
  });

  it("ignores a held [ or ], so a point does not follow the playhead", () => {
    const { engine, at } = setup();
    at(2);
    press("[");
    at(6);
    press("]");
    at(8);
    press("[", { repeat: true });
    press("]", { repeat: true });
    expect(engine.getState().loop).toEqual({ a: 2, b: 6 });
    // The next press, after the key came up, sets the point again.
    press("]");
    expect(engine.getState().loop).toEqual({ a: 2, b: 8 });
  });

  it("leaves [ and ] with a modifier alone", () => {
    const { engine } = setup();
    press("[", { ctrlKey: true });
    press("]", { metaKey: true });
    press("[", { altKey: true });
    expect(engine.getState().loop).toEqual({ a: null, b: null });
  });

  describe("on a layout where [ and ] are typed with AltGr", () => {
    it("sets A and B when Windows reports AltGr as Ctrl and Alt together", () => {
      const { engine, at } = setup();
      at(2);
      press("[", { ctrlKey: true, altKey: true });
      at(6);
      press("]", { ctrlKey: true, altKey: true });
      expect(engine.getState().loop).toEqual({ a: 2, b: 6 });
    });

    it("sets A and B when the event reports the AltGraph modifier", () => {
      const { engine, at } = setup();
      at(2);
      press("[", { modifierAltGraph: true });
      at(6);
      press("]", { modifierAltGraph: true, altKey: true });
      expect(engine.getState().loop).toEqual({ a: 2, b: 6 });
    });

    it("still ignores Meta, and a held AltGr key, as it does a held [", () => {
      const { engine, at } = setup();
      at(2);
      press("[", { ctrlKey: true, altKey: true, metaKey: true });
      press("[", { ctrlKey: true, altKey: true, repeat: true });
      expect(engine.getState().loop).toEqual({ a: null, b: null });
    });

    it("gives Space and the arrows no such leave: Ctrl+Alt+Space does not toggle, Ctrl+Alt+→ does not seek", () => {
      const { engine } = setup();
      press(" ", { ctrlKey: true, altKey: true });
      press("ArrowRight", { ctrlKey: true, altKey: true });
      press("ArrowRight", { modifierAltGraph: true, altKey: true });
      expect(engine.getState().playing).toBe(false);
      expect(engine.getState().time).toBe(0);
    });
  });
});
