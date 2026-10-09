import { describe, expect, it } from "vitest";

import { FakeMedia } from "../test/fakeMedia";
import { MediaClock } from "./clock";

function setup() {
  const media = new FakeMedia();
  let ms = 0;
  const clock = new MediaClock(media, () => ms);
  const wait = (milliseconds: number) => {
    ms += milliseconds;
  };
  return { media, clock, wait };
}

describe("MediaClock", () => {
  it("returns media time exactly while paused", () => {
    const { media, clock, wait } = setup();
    media.currentTime = 12.5;

    wait(500);

    expect(clock.now()).toBe(12.5);
  });

  it("extrapolates between coarse media updates", () => {
    const { media, clock, wait } = setup();
    void media.play();

    wait(16);
    expect(clock.now()).toBeCloseTo(0.016);
    wait(16);
    expect(clock.now()).toBeCloseTo(0.032); // media time has not moved yet
    media.currentTime = 0.03; // it catches up, within the drift allowance
    wait(16);
    expect(clock.now()).toBeCloseTo(0.048);
  });

  it("snaps to media time when extrapolation drifts more than 50 ms", () => {
    const { media, clock, wait } = setup();
    void media.play();
    media.currentTime = 1;
    media.emit("timeupdate");

    wait(200); // the element stalled without saying so
    media.currentTime = 1.1;

    expect(clock.now()).toBeCloseTo(1.1);
  });

  it("freezes while the element is waiting for data", () => {
    const { media, clock, wait } = setup();
    void media.play();
    media.currentTime = 3;
    media.emit("waiting");

    wait(30); // inside the drift allowance, so only the freeze can hold it at 3

    expect(clock.now()).toBe(3);
    media.emit("playing");
    wait(100);
    media.currentTime = 3.09;
    expect(clock.now()).toBeCloseTo(3.1);
  });

  it("never goes backwards on a correction", () => {
    const { media, clock, wait } = setup();
    void media.play();
    wait(40);
    const ahead = clock.now();
    media.currentTime = 0.01; // a late, low reading
    media.emit("timeupdate");

    expect(clock.now()).toBe(ahead);
  });

  it("goes backwards after a seek", () => {
    const { media, clock, wait } = setup();
    media.currentTime = 30;
    clock.now();

    media.currentTime = 10;
    media.emit("seeked");
    wait(16);

    expect(clock.now()).toBe(10);
  });

  it("goes backwards after a jump the engine announces", () => {
    const { media, clock } = setup();
    media.currentTime = 30;
    clock.now();

    media.currentTime = 10;
    clock.jump();

    expect(clock.now()).toBe(10);
  });

  it("follows a rate change mid-play", () => {
    const { media, clock, wait } = setup();
    void media.play();
    wait(1000);
    media.currentTime = 1;
    expect(clock.now()).toBeCloseTo(1);

    media.playbackRate = 0.5;
    media.emit("ratechange");
    wait(1000);
    media.currentTime = 1.5;

    expect(clock.now()).toBeCloseTo(1.5);
    wait(40);
    expect(clock.now()).toBeCloseTo(1.52);
  });

  it("stops listening when disposed", () => {
    const { media, clock } = setup();

    clock.dispose();

    expect(media.listenerCount()).toBe(0);
  });
});
