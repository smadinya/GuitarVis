import { useEffect, useState, type DragEvent } from "react";

import { ApiError, createJob } from "../api/client";
import type { Reason } from "../api/messages";
import { navigate, songPath } from "../routing";
import { Failure } from "./Failure";

type Upload =
  | { kind: "idle" }
  | { kind: "sending"; name: string; fraction: number }
  | { kind: "refused"; reason: Reason };

export interface UploadPageProps {
  upload?: typeof createJob;
}

/** Drop or pick a song; POST /jobs; go to its page. A re-upload lands on the
 * existing song, which may already be playable. */
export function UploadPage({ upload = createJob }: UploadPageProps) {
  const [state, setState] = useState<Upload>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const sending = state.kind === "sending";

  const send = (file: File) => {
    if (sending) return;
    setState({ kind: "sending", name: file.name, fraction: 0 });
    upload(file, (fraction) => setState({ kind: "sending", name: file.name, fraction }))
      .then(({ job }) => navigate(songPath(job.id)))
      .catch((error: unknown) =>
        setState({
          kind: "refused",
          reason: error instanceof ApiError ? error.reason : "unreachable",
        }),
      );
  };

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
      {state.kind === "refused" && <Failure reason={state.reason} />}
    </main>
  );
}
