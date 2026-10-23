// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Warnings } from "./Warnings";

const region = () => screen.getByRole("complementary", { name: "Warnings" });

describe("Warnings", () => {
  it("shows nothing for a clean document", () => {
    const { container } = render(<Warnings warnings={[]} />);
    expect(container.childElementCount).toBe(0);
  });

  it("shows a single warning's text, with no button", () => {
    render(<Warnings warnings={["Chord detection failed, so this tab has no chords."]} />);
    expect(region().textContent).toContain("Chord detection failed");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("collapses several warnings to a count, and expands them on demand", () => {
    render(<Warnings warnings={["one", "two", "three"]} />);
    expect(region().textContent).toContain("3 things to know about this tab");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["one", "two", "three"]);
    expect(screen.getByRole("button", { name: "Hide" }).getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Show" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps a mouse click on Show from taking focus", () => {
    render(<Warnings warnings={["one", "two"]} />);
    expect(fireEvent.mouseDown(screen.getByRole("button", { name: "Show" }))).toBe(false);
  });
});
