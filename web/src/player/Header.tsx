import { pitchNames } from "../labels";
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
 * tempo is an average the pipeline estimated, so it says "about" and rounds. */
export function details(song: Song): string {
  const parts = [clock(song.duration), tuningName(song.tuning)];
  if (song.tempo !== null) parts.push(`about ${Math.round(song.tempo)} bpm`);
  return parts.join(" · ");
}

/** The song page's header: the way back, the title with what is known about
 * the song, and the choice of view. It owns the page's only <h1> once the
 * player is up. */
export function Header({ song, view, onView }: { song: Song; view: PageView; onView: (view: PageView) => void }) {
  return (
    <header className="song-header">
      <UploadAnother className="back" />
      <div className="song-title">
        <h1>{song.title}</h1>
        <p className="details">{details(song)}</p>
      </div>
      <ViewSwitch view={view} onChange={onView} />
    </header>
  );
}
