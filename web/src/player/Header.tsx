import { useSyncExternalStore } from "react";

import { pitchNames } from "../labels";
import type { PlaybackEngine } from "../playback/engine";
import { STANDARD_TUNING, type Song } from "../song";
import { UploadAnother } from "../UploadAnother";
import { clock } from "./time";
import { ViewSwitch, type PageView } from "./ViewSwitch";

/** "Standard tuning", or the strings' pitches, lowest first: "D A D G B E
 * tuning". The pitches say which tuning it is without a table of names to
 * maintain. Each is named for its pitch, not as tab writes it: a half step
 * down is "Eb Ab Db Gb Bb Eb", with the same capital E at both ends. */
export function tuningName(tuning: readonly string[]): string {
  const standard =
    tuning.length === STANDARD_TUNING.length && tuning.every((name, i) => name === STANDARD_TUNING[i]);
  return standard ? "Standard tuning" : `${pitchNames(tuning).join(" ")} tuning`;
}

/** Length, tuning, and the tempo when there is one, joined by " · ". The
 * length is the one handed in, which is the transport's: the document's is a
 * guess until the media says how long it really is. The tempo is an average
 * the pipeline estimated, so it says "about" and rounds. */
export function details(song: Song, duration: number): string {
  const parts = [clock(duration), tuningName(song.tuning)];
  if (song.tempo !== null) parts.push(`about ${Math.round(song.tempo)} bpm`);
  return parts.join(" · ");
}

/** For a header with no engine yet: nothing to subscribe to, ever. */
const NEVER = () => () => {};

/** The song page's header: the way back, the title with what is known about
 * the song, and the choice of view. It owns the page's only <h1> once the
 * player is up, and the player shows it before its engine exists, so the
 * title never blinks out between the song page's own and this one.
 *
 * The length is the engine's, as the transport's is, and the header reads
 * only that of the engine's state: it renders when the length changes, which
 * is once when the media reports it, and not at the readout's four times a
 * second. Until there is an engine it is the document's. */
export function Header({
  song,
  engine,
  view,
  onView,
}: {
  song: Song;
  engine: PlaybackEngine | null;
  view: PageView;
  onView: (view: PageView) => void;
}) {
  const duration = useSyncExternalStore(
    engine?.subscribe ?? NEVER,
    () => engine?.getState().duration ?? song.duration,
    () => song.duration,
  );
  return (
    <header className="song-header">
      <UploadAnother className="back" />
      <div className="song-title">
        <h1>{song.title}</h1>
        <p className="details">{details(song, duration)}</p>
      </div>
      <ViewSwitch view={view} onChange={onView} />
    </header>
  );
}
