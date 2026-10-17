import { Component, type ReactNode } from "react";

import { GUITAR_LOAD_FAILED } from "../labels";

interface State {
  failed: boolean;
}

/**
 * Keeps a guitar that cannot load from taking the player with it. React
 * unmounts the whole tree when a lazy import rejects, and the tab strip, the
 * controls and the audio would go with the 3D panel. The fallback is the
 * panel's own box, so the page keeps its height.
 *
 * It holds no retry: React.lazy remembers a rejection, so only a reload
 * fetches the chunk again.
 */
export class GuitarBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="guitar">
        <p className="guitar-unavailable">{GUITAR_LOAD_FAILED}</p>
      </div>
    );
  }
}
