// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("shows the upload page at the root", () => {
    render(<App />);

    expect(screen.getByLabelText(/choose one/i)).toBeTruthy();
  });

  it("says when there is no page, and links back without a page load", () => {
    window.history.replaceState(null, "", "/nowhere");
    render(<App />);
    expect(document.body.textContent).toContain("There is no page here.");

    fireEvent.click(screen.getByRole("link", { name: "Upload a song" }));

    expect(window.location.pathname).toBe("/");
    expect(screen.getByLabelText(/choose one/i)).toBeTruthy();
  });
});
