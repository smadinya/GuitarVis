/**
 * The text the views share. A view takes its labels from here, never from
 * another view's layout: views do not talk to each other, and two copies of
 * one rule would drift.
 */

export const EMPTY_MESSAGE = "No notes to show";
export const UNCLEAR_LABEL = "unclear passage";
/** In the guitar's place when its code could not be fetched. A reload is the
 * only retry: the failed fetch is remembered until the page is. */
export const GUITAR_LOAD_FAILED = "The guitar could not load. Reload the page to try again.";
/** In the guitar's place when it threw. A reload would only repeat the bug,
 * so this one does not offer it. */
export const GUITAR_FAILED = "The guitar hit an error and stopped. The tab and the audio carry on.";

/** Pitch classes from C, spelled with sharps as the chord symbols are. */
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/**
 * Letter names by string, lowest first. The top string is lowercased when it
 * shares a letter with the bottom one: e … E in standard tuning, while drop D
 * keeps its capital E.
 */
export function stringLabels(tuning: readonly string[]): string[] {
  const labels = tuning.map((name) => /^[A-Ga-g][#b]?/.exec(name)?.[0] ?? name);
  const top = labels.length - 1;
  if (top > 0 && labels[top].toLowerCase() === labels[0].toLowerCase()) {
    labels[top] = labels[top].toLowerCase();
  }
  return labels;
}

/** A pitch's name without its octave: MIDI 40 and 64 are both "E". The
 * document has no key, so there is no right choice between a sharp and a
 * flat; sharps match the chord symbols. */
export function noteName(midi: number): string {
  return NOTE_NAMES[((midi % 12) + 12) % 12];
}
