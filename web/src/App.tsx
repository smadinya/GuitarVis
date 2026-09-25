/**
 * The client shell.
 *
 * The three synced views arrive in later specs. When they do, each one
 * subscribes to (tabDocument, currentTime) and holds no playback state of its
 * own: a PlaybackEngine owns the audio element and is the sole source of truth
 * for current time.
 */
export function App() {
  return (
    <main>
      <h1>GuitarVis</h1>
      <p>Pipeline first. Views land in a later spec.</p>
    </main>
  );
}
