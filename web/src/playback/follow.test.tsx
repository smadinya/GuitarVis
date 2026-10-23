// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { useFollowed } from "./follow";

const FIRST_SONG: TabDocument = firstSongJson;

const whole = (t: number) => Math.floor(t);

/** The hook over a fresh engine, counting the renders it causes. */
function setup<V>(follow: (t: number) => V, same?: (a: V, b: V) => boolean) {
  const fake = fakeEngine(buildSong(FIRST_SONG));
  let renders = 0;
  const view = renderHook(
    (props: { follow: (t: number) => V }) => {
      renders++;
      return useFollowed(fake.engine, props.follow, same);
    },
    { initialProps: { follow } },
  );
  return { ...fake, view, renders: () => renders };
}

describe("useFollowed", () => {
  it("is right on its first render, from where the playhead stands, before any frame", () => {
    const fake = fakeEngine(buildSong(FIRST_SONG));
    fake.at(5.5);
    let renders = 0;

    const view = renderHook(() => {
      renders++;
      return useFollowed(fake.engine, whole);
    });

    expect(view.result.current).toBe(5);
    expect(renders).toBe(1); // reading the playhead again did not render again
  });

  it("follows the frames, and renders only when the value changes", () => {
    const { at, view, renders } = setup(whole);
    at(1.2);
    expect(view.result.current).toBe(1);
    const before = renders();

    at(1.5);
    at(1.99);
    expect(renders()).toBe(before);

    at(2.01);
    expect(view.result.current).toBe(2);
    expect(renders()).toBe(before + 1);
  });

  it("follows a jump back as it follows a jump forward", () => {
    const { at, view } = setup(whole);
    at(9.5);
    expect(view.result.current).toBe(9);
    at(2.5);
    expect(view.result.current).toBe(2);
  });

  it("takes values that `same` calls equal for unchanged, though each is a new object", () => {
    const { at, view, renders } = setup(
      (t) => ({ second: Math.floor(t) }),
      (a, b) => a.second === b.second,
    );
    at(3.1);
    const before = renders();

    at(3.5);
    at(3.9);
    expect(renders()).toBe(before);

    at(4.1);
    expect(view.result.current).toEqual({ second: 4 });
    expect(renders()).toBe(before + 1);
  });

  it("derives again, from the same playhead, when it is given another function", () => {
    const { at, view } = setup(whole);
    at(3.5);
    expect(view.result.current).toBe(3);

    view.rerender({ follow: (t) => Math.floor(t) * 10 });

    expect(view.result.current).toBe(30);
  });

  it("holds one frame subscription, and releases it on unmount", () => {
    const fake = fakeEngine(buildSong(FIRST_SONG));
    const stopped = vi.fn();
    const onFrame = fake.engine.onFrame.bind(fake.engine);
    const subscribe = vi.spyOn(fake.engine, "onFrame").mockImplementation((listener) => {
      const stop = onFrame(listener);
      return () => {
        stopped();
        stop();
      };
    });

    const view = renderHook(() => useFollowed(fake.engine, whole));
    act(() => fake.frames.flush());
    expect(subscribe).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(stopped).toHaveBeenCalledTimes(1);
  });
});
