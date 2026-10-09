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
});
