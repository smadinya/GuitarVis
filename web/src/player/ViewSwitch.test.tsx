// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStoredView, ViewSwitch, VIEW_KEY } from "./ViewSwitch";

function Harness() {
  const [view, setView] = useStoredView();
  return <ViewSwitch view={view} onChange={setView} />;
}

const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

describe("ViewSwitch", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("opens in 3D on a first visit", () => {
    render(<Harness />);
    expect(["3D", "Fretboard", "Tab only"].map(pressed)).toEqual(["true", "false", "false"]);
  });

  it("switches views, and remembers the choice", () => {
    const first = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Fretboard" }));
    expect(localStorage.getItem(VIEW_KEY)).toBe("2d");
    first.unmount();

    const second = render(<Harness />);
    expect(pressed("Fretboard")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Tab only" }));
    expect(localStorage.getItem(VIEW_KEY)).toBe("tab");
    second.unmount();

    render(<Harness />);
    expect(pressed("Tab only")).toBe("true");
  });

  it("opens in 3D when the browser's storage throws, and still switches", () => {
    const denied = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(denied);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(denied);

    render(<Harness />);
    expect(pressed("3D")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Fretboard" }));
    expect(pressed("Fretboard")).toBe("true");
  });

  it("ignores a stored view it does not know", () => {
    localStorage.setItem(VIEW_KEY, "4d");

    render(<Harness />);

    expect(pressed("3D")).toBe("true");
  });

  it("names its group View", () => {
    render(<Harness />);

    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
  });

  it("keeps a mouse click from taking focus", () => {
    render(<Harness />);
    for (const name of ["3D", "Fretboard", "Tab only"]) {
      expect(fireEvent.mouseDown(screen.getByRole("button", { name }))).toBe(false);
    }
  });
});
