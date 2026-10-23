// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UploadAnother } from "./UploadAnother";

describe("UploadAnother", () => {
  afterEach(() => {
    window.history.pushState(null, "", "/");
  });

  it("links to the upload page, and says so", () => {
    render(<UploadAnother />);
    const link = screen.getByRole("link", { name: "Upload another song" });
    expect(link.getAttribute("href")).toBe("/");
  });

  it("takes the words the page needs, and a class to be styled by", () => {
    render(<UploadAnother label="Upload a song" className="back" />);
    const link = screen.getByRole("link", { name: "Upload a song" });
    expect(link.className).toBe("back");
  });

  it("has no class unless it is given one", () => {
    render(<UploadAnother />);
    expect(screen.getByRole("link").hasAttribute("class")).toBe(false);
  });

  it("goes to the upload page in place, and leaves a click that asks for a new tab to the browser", () => {
    window.history.pushState(null, "", "/songs/abc");
    render(<UploadAnother />);
    const link = screen.getByRole("link");

    expect(fireEvent.click(link, { button: 0, ctrlKey: true })).toBe(true);
    expect(window.location.pathname).toBe("/songs/abc");

    expect(fireEvent.click(link, { button: 0 })).toBe(false); // preventDefault: followed in place
    expect(window.location.pathname).toBe("/");
  });
});
