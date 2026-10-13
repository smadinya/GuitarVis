/**
 * The client: an upload page, and a song page whose views all subscribe to
 * one PlaybackEngine and hold no playback state of their own.
 */
import { UploadAnother } from "./pages/Failure";
import { SongPage } from "./pages/SongPage";
import { UploadPage } from "./pages/UploadPage";
import { followLink, useRoute } from "./routing";

export function App() {
  const route = useRoute();
  return (
    <>
      <header className="masthead">
        <a href="/" onClick={followLink}>
          GuitarVis
        </a>
      </header>
      {route.page === "upload" && <UploadPage />}
      {route.page === "song" && <SongPage key={route.jobId} jobId={route.jobId} />}
      {route.page === "missing" && (
        <main>
          <p>There is no page here.</p>
          <UploadAnother label="Upload a song" />
        </main>
      )}
    </>
  );
}
