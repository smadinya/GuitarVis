// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Upload } from "../api/client";
import { MESSAGES } from "../api/messages";
import { JOB_ID, jobView } from "../test/jobs";
import { UploadPage } from "./UploadPage";

const song = () => new File([new Uint8Array([1])], "song.mp3", { type: "audio/mpeg" });

function choose(file: File) {
  fireEvent.change(screen.getByLabelText(/choose one/i), { target: { files: [file] } });
}

describe("UploadPage", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("goes to the song's page once the upload is accepted", async () => {
    const upload = vi.fn(async (): Promise<Upload> => ({ job: jobView(), created: true }));
    render(<UploadPage upload={upload} />);

    choose(song());
    await act(async () => {});

    expect(upload).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
  });

  it("takes a dropped file too", async () => {
    const upload = vi.fn(async (): Promise<Upload> => ({ job: jobView(), created: false }));
    render(<UploadPage upload={upload} />);

    fireEvent.drop(screen.getByText(/drop an audio file/i), {
      dataTransfer: { files: [song()] },
    });
    await act(async () => {});

    expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
  });

  it("shows upload progress", () => {
    render(
      <UploadPage
        upload={(_file, onProgress) => {
          onProgress?.(0.5);
          return new Promise(() => {});
        }}
      />,
    );

    choose(song());

    expect(screen.getByRole("status").textContent).toContain("50%");
  });

  it("says it is checking the file once every byte is sent, until the api answers", async () => {
    let answer: (upload: Upload) => void = () => {};
    render(
      <UploadPage
        upload={(_file, onProgress) => {
          onProgress?.(0.5);
          onProgress?.(1);
          return new Promise<Upload>((resolve) => (answer = resolve));
        }}
      />,
    );

    choose(song());

    const status = screen.getByRole("status").textContent;
    expect(status).toContain("Checking the file");
    expect(status).not.toContain("100%");
    await act(async () => answer({ job: jobView(), created: true }));
    expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
  });

  it("shows the mapped text when the api refuses", async () => {
    render(
      <UploadPage
        upload={async () => {
          throw new ApiError(429, "too_many_jobs", "You already have 2 songs processing.");
        }}
      />,
    );

    choose(song());
    await act(async () => {});

    expect(screen.getByText(MESSAGES.too_many_jobs.headline)).toBeTruthy();
    expect(screen.getByText(MESSAGES.too_many_jobs.action)).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });

  it("calls anything else unreachable", async () => {
    render(
      <UploadPage
        upload={async () => {
          throw new TypeError("boom");
        }}
      />,
    );

    choose(song());
    await act(async () => {});

    expect(screen.getByText(MESSAGES.unreachable.headline)).toBeTruthy();
  });

  it("stays wherever the user went if they leave before the upload finishes", async () => {
    let answer: (upload: Upload) => void = () => {};
    let signal: AbortSignal | undefined;
    const { unmount } = render(
      <UploadPage
        upload={(_file, _onProgress, given) => {
          signal = given;
          return new Promise<Upload>((resolve) => (answer = resolve));
        }}
      />,
    );
    choose(song());

    unmount();
    window.history.pushState(null, "", "/songs/the-one-they-were-playing");
    await act(async () => answer({ job: jobView(), created: true }));

    expect(window.location.pathname).toBe("/songs/the-one-they-were-playing");
    expect(signal?.aborted).toBe(true);
  });

  it("keeps a file dropped just outside the drop zone from opening in the browser", () => {
    const { unmount } = render(<UploadPage upload={() => new Promise(() => {})} />);

    const near = new Event("drop", { cancelable: true });
    const over = new Event("dragover", { cancelable: true });
    window.dispatchEvent(near);
    window.dispatchEvent(over);

    expect(near.defaultPrevented).toBe(true);
    expect(over.defaultPrevented).toBe(true);

    unmount();
    const later = new Event("drop", { cancelable: true });
    const laterOver = new Event("dragover", { cancelable: true });
    window.dispatchEvent(later);
    window.dispatchEvent(laterOver);

    expect(later.defaultPrevented).toBe(false);
    expect(laterOver.defaultPrevented).toBe(false);
  });
});
