import { Component, type ErrorInfo, type ReactNode } from "react";

import { GUITAR_FAILED, GUITAR_LOAD_FAILED } from "../labels";
import { logError } from "../log";

/** The guitar's chunk could not be fetched. Player's lazy import throws it in
 * place of the browser's own error, whose wording differs between browsers,
 * and keeps that error as `cause`. */
export class GuitarChunkError extends Error {
  constructor(cause: unknown) {
    super("The guitar's code could not load.", { cause });
    this.name = "GuitarChunkError";
  }
}

interface State {
  /** What the panel says in the guitar's place, or null while it works. */
  message: string | null;
}

/**
 * Keeps a guitar that fails from taking the player with it. React unmounts
 * the whole tree on an error no boundary catches, and the tab strip, the
 * controls and the audio would go with the 3D panel. The fallback is the
 * panel's own box, so the page keeps its height.
 *
 * Two failures reach it. A chunk that could not be fetched comes as a
 * GuitarChunkError, and a reload may fix it. Anything else is a bug in the
 * guitar, which a reload would only repeat.
 *
 * It holds no retry: React.lazy remembers a rejection, so only a reload
 * fetches the chunk again.
 */
export class GuitarBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { message: null };

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof GuitarChunkError ? GUITAR_LOAD_FAILED : GUITAR_FAILED };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    if (error instanceof GuitarChunkError) logError("the guitar's code could not load", error);
    else logError(`the guitar failed${info.componentStack ?? ""}`, error);
  }

  render() {
    if (this.state.message === null) return this.props.children;
    return (
      <div className="guitar">
        <p className="guitar-unavailable">{this.state.message}</p>
      </div>
    );
  }
}
