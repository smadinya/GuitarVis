// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Upload } from "../api/client";
import { MESSAGES, type Reason } from "../api/messages";
import type { Features } from "../types/api";
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

  describe("the link field", () => {
    const LINK = "https://youtu.be/kPdv44HtEoA";
    const on = async (): Promise<Features> => ({ url_ingestion: true });
    const never = () => new Promise<Upload>(() => {});

    async function showLinks(sendLink: (url: string, signal?: AbortSignal) => Promise<Upload>) {
      render(<UploadPage upload={never} sendLink={sendLink} features={on} />);
      await act(async () => {});
    }

    function field() {
      return screen.getByRole("textbox", { name: "Link to a YouTube video" }) as HTMLInputElement;
    }

    function paste(text: string) {
      fireEvent.change(field(), { target: { value: text } });
      fireEvent.click(screen.getByRole("button", { name: "Get tab" }));
    }

    it.each<[string, () => Promise<Features>]>([
      ["says links are off", async () => ({ url_ingestion: false })],
      [
        "cannot be reached",
        async () => {
          throw new ApiError(null, "unreachable", "No answer from the server.");
        },
      ],
    ])("is hidden when the api %s", async (_case, features) => {
      render(<UploadPage upload={never} sendLink={never} features={features} />);
      await act(async () => {});

      expect(screen.queryByRole("textbox", { name: "Link to a YouTube video" })).toBeNull();
      expect(screen.queryByText("or paste a link")).toBeNull();
    });

    it("shows under the drop zone when the api says links are on", async () => {
      await showLinks(never);

      expect(field().placeholder).toBe("https://…");
      expect(screen.getByText("or paste a link")).toBeTruthy();
    });

    it.each<[string, string]>([
      ["", "Paste a link first."],
      ["never gonna give you up", "That doesn't look like a link."],
      ["javascript:alert(1)", "That doesn't look like a link."],
    ])("hints and sends nothing for %j", async (text, hint) => {
      const sendLink = vi.fn(never);
      await showLinks(sendLink);

      paste(text);

      expect(sendLink).not.toHaveBeenCalled();
      const shown = screen.getByText(hint);
      expect(field().getAttribute("aria-invalid")).toBe("true");
      expect(field().getAttribute("aria-describedby")).toBe(shown.id);
    });

    it("announces the hint, in place of an earlier attempt's failure", async () => {
      await showLinks(async () => {
        throw new ApiError(503, "fetch_failed", "Words from the server.");
      });
      paste(LINK);
      await act(async () => {});
      expect(screen.getByText(MESSAGES.fetch_failed.headline)).toBeTruthy();

      paste("");

      const alerts = screen.getAllByRole("alert");
      expect(alerts).toHaveLength(1);
      expect(alerts[0].textContent).toBe("Paste a link first.");
      expect(screen.queryByText(MESSAGES.fetch_failed.headline)).toBeNull();
    });

    it("clears the hint once the text changes", async () => {
      await showLinks(never);
      paste("");

      fireEvent.change(field(), { target: { value: "y" } });

      expect(screen.queryByText("Paste a link first.")).toBeNull();
      expect(field().getAttribute("aria-invalid")).toBe("false");
    });

    it("sends the link, says it is checking, and goes to the song", async () => {
      let answer: (upload: Upload) => void = () => {};
      const sendLink = vi.fn<(url: string, signal?: AbortSignal) => Promise<Upload>>(
        () => new Promise((resolve) => (answer = resolve)),
      );
      await showLinks(sendLink);

      paste(`  ${LINK}  `);

      expect(sendLink).toHaveBeenCalledOnce();
      expect(sendLink.mock.calls[0][0]).toBe(LINK);
      expect(screen.getByRole("status").textContent).toBe("Checking the link…");
      expect(field().disabled).toBe(true);
      expect((screen.getByLabelText(/choose one/i) as HTMLInputElement).disabled).toBe(true);
      await act(async () => answer({ job: jobView(), created: true }));
      expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
    });

    it.each<[Reason, number]>([
      ["unsupported_link", 422],
      ["link_unusable", 422],
      ["too_long", 422],
      ["too_many_jobs", 429],
      ["fetch_failed", 503],
      ["internal", 500],
    ])("shows %s's text with the server's words as detail", async (reason, status) => {
      await showLinks(async () => {
        throw new ApiError(status, reason, "Words from the server.");
      });

      paste(LINK);
      await act(async () => {});

      expect(screen.getByText(MESSAGES[reason].headline)).toBeTruthy();
      expect(screen.getByText(MESSAGES[reason].action)).toBeTruthy();
      expect(screen.getByText("Words from the server.")).toBeTruthy();
      expect(field()).toBeTruthy(); // still there to try another link
      expect(window.location.pathname).toBe("/");
    });

    it("removes itself when the api says links were turned off", async () => {
      await showLinks(async () => {
        throw new ApiError(403, "links_disabled", "Links are turned off on this server.");
      });

      paste(LINK);
      await act(async () => {});

      expect(screen.getByText(MESSAGES.links_disabled.headline)).toBeTruthy();
      expect(screen.getByText("Links are turned off on this server.")).toBeTruthy();
      expect(screen.queryByRole("textbox", { name: "Link to a YouTube video" })).toBeNull();
    });

    it("calls no answer unreachable, without a detail of its own", async () => {
      await showLinks(async () => {
        throw new ApiError(null, "unreachable", "No answer from the server.");
      });

      paste(LINK);
      await act(async () => {});

      expect(screen.getByText(MESSAGES.unreachable.headline)).toBeTruthy();
      expect(screen.queryByText("No answer from the server.")).toBeNull();
    });

    it("stops the request and stays put if the user leaves first", async () => {
      let answer: (upload: Upload) => void = () => {};
      let signal: AbortSignal | undefined;
      const { unmount } = render(
        <UploadPage
          upload={never}
          features={on}
          sendLink={(_url, given) => {
            signal = given;
            return new Promise<Upload>((resolve) => (answer = resolve));
          }}
        />,
      );
      await act(async () => {});
      paste(LINK);

      unmount();
      window.history.pushState(null, "", "/songs/somewhere-else");
      await act(async () => answer({ job: jobView(), created: true }));

      expect(signal?.aborted).toBe(true);
      expect(window.location.pathname).toBe("/songs/somewhere-else");
    });
  });
});
