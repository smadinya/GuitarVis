import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";

import { ApiError, createJob, createJobFromUrl, getFeatures } from "../api/client";
import type { Reason } from "../api/messages";
import { LinkIcon } from "../icons";
import { navigate, songPath } from "../routing";
import type { Features } from "../types/api";
import { Failure } from "./Failure";
import { linkHint } from "./link";

type Upload =
  | { kind: "idle" }
  | { kind: "sending"; name: string; fraction: number }
  | { kind: "checking" }
  | { kind: "refused"; reason: Reason; detail?: string };

export interface UploadPageProps {
  upload?: typeof createJob;
  sendLink?: typeof createJobFromUrl;
  features?: () => Promise<Features>;
}

/** Drop or pick a song, or paste a link; POST it; go to its page. A repeat
 * lands on the existing song, which may already be playable. */
export function UploadPage({
  upload = createJob,
  sendLink = createJobFromUrl,
  features = getFeatures,
}: UploadPageProps) {
  const [state, setState] = useState<Upload>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const linksOn = useLinksOn(features);
  const [linksRefused, setLinksRefused] = useState(false);
  const sending = state.kind === "sending" || state.kind === "checking";
  const inFlight = useRef<AbortController | null>(null);

  // A user who leaves mid-request has gone somewhere else: stop it, and
  // never pull them back to the song when it would have finished.
  useEffect(() => () => inFlight.current?.abort(), []);

  const start = () => {
    const controller = new AbortController();
    inFlight.current = controller;
    return () => !controller.signal.aborted;
  };

  const send = (file: File) => {
    if (sending) return;
    const live = start();
    setState({ kind: "sending", name: file.name, fraction: 0 });
    const onProgress = (fraction: number) => {
      if (live()) setState({ kind: "sending", name: file.name, fraction });
    };
    upload(file, onProgress, inFlight.current?.signal)
      .then(({ job }) => {
        if (live()) navigate(songPath(job.id));
      })
      .catch((error: unknown) => {
        if (!live()) return;
        setState({
          kind: "refused",
          reason: error instanceof ApiError ? error.reason : "unreachable",
        });
      });
  };

  const sendUrl = (url: string) => {
    if (sending) return;
    const live = start();
    setState({ kind: "checking" });
    sendLink(url, inFlight.current?.signal)
      .then(({ job }) => {
        if (live()) navigate(songPath(job.id));
      })
      .catch((error: unknown) => {
        if (!live()) return;
        if (!(error instanceof ApiError)) {
          setState({ kind: "refused", reason: "unreachable" });
          return;
        }
        // Turned off since the page asked: the field goes, the reason stays.
        if (error.reason === "links_disabled") setLinksRefused(true);
        setState({
          kind: "refused",
          reason: error.reason,
          detail: error.status === null ? undefined : error.message,
        });
      });
  };

  // A hint is about this attempt: an earlier attempt's failure goes. A
  // request in flight stays, though no hint can be shown while one is.
  const clearFailure = () =>
    setState((current) => (current.kind === "refused" ? { kind: "idle" } : current));

  // A file dropped just outside the drop zone would otherwise be opened by the
  // browser, and the app lost. Only the drop zone takes a drop.
  useEffect(() => {
    const refuse = (event: Event) => event.preventDefault();
    window.addEventListener("dragover", refuse);
    window.addEventListener("drop", refuse);
    return () => {
      window.removeEventListener("dragover", refuse);
      window.removeEventListener("drop", refuse);
    };
  }, []);

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file !== undefined) send(file);
  };

  return (
    <main className="upload-page">
      <h1>Turn a song into guitar tab</h1>
      <p>Upload a recording. We isolate the guitar, transcribe it, and play it back with the tab.</p>
      <label
        className={dragging ? "drop-zone dragging" : "drop-zone"}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span>Drop an audio file here, or choose one</span>
        <input
          type="file"
          accept="audio/*"
          disabled={sending}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file !== undefined) send(file);
          }}
        />
      </label>
      {linksOn && !linksRefused && (
        <LinkForm disabled={sending} onSend={sendUrl} onHint={clearFailure} />
      )}
      {state.kind === "sending" && (
        <p role="status">
          {state.fraction < 1 ? (
            <>
              Uploading {state.name} <progress value={state.fraction} max={1} />{" "}
              {Math.round(state.fraction * 100)}%
            </>
          ) : (
            // Every byte is sent; the api hashes, probes and stores the file
            // before it answers, which takes seconds for a large one.
            "Checking the file…"
          )}
        </p>
      )}
      {state.kind === "checking" && <p role="status">Checking the link…</p>}
      {state.kind === "refused" && <Failure reason={state.reason} detail={state.detail} />}
    </main>
  );
}

/** Whether to offer links: only once the api says they are on. No answer,
 * or any other answer, leaves the field hidden. */
function useLinksOn(features: () => Promise<Features>): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let live = true;
    features().then(
      (answer) => {
        if (live && answer.url_ingestion) setOn(true);
      },
      () => {},
    );
    return () => {
      live = false;
    };
  }, [features]);
  return on;
}

/** The link field, under the drop zone (the WebHome mockup). A hint shows
 * under the field, and nothing is sent, until the text looks like a link. The
 * hint is announced, as a server's refusal is, and `onHint` hears of it. */
function LinkForm({
  disabled,
  onSend,
  onHint,
}: {
  disabled: boolean;
  onSend: (url: string) => void;
  onHint: () => void;
}) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const hintId = useId();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const problem = linkHint(text);
    setHint(problem);
    if (problem === null) onSend(text.trim());
    else onHint();
  };

  return (
    <form className="link-form" onSubmit={submit} noValidate>
      <p className="divider">or paste a link</p>
      <div className="link-row">
        <label className="link-field">
          <LinkIcon />
          <input
            type="url"
            inputMode="url"
            placeholder="https://…"
            aria-label="Link to a YouTube video"
            value={text}
            disabled={disabled}
            aria-invalid={hint !== null}
            aria-describedby={hint !== null ? hintId : undefined}
            onChange={(event) => {
              setText(event.target.value);
              setHint(null);
            }}
          />
        </label>
        <button type="submit" disabled={disabled}>
          Get tab
        </button>
      </div>
      {hint !== null && (
        <p id={hintId} className="link-hint" role="alert">
          {hint}
        </p>
      )}
    </form>
  );
}
