/**
 * What the confidence thresholds do to real tab documents: the share of
 * notes they fade and hide, and of chords they fade. Recorded in
 * docs/specs/006-tab-view-sync/calibration.md as the sanity check on
 * thresholds measured on GuitarSet.
 *
 *   node scripts/confidence-report.ts <tab document JSON>...
 *
 * Node runs the TypeScript directly (type stripping, Node 22.18 and later),
 * using the same functions the views use, and tsc checks it with the rest of
 * the client.
 */
import { readFileSync } from "node:fs";

import {
  CHORD_FULL,
  CHORD_HIDE,
  FULL,
  HIDE,
  hiddenPassages,
  isHidden,
} from "../src/confidence.ts";
import type { TabDocument } from "../src/types/tabDocument.ts";

function share(count: number, total: number): string {
  return total === 0 ? "—" : `${((100 * count) / total).toFixed(0)}%`;
}

const paths = process.argv.slice(2);
const docs = paths.map((path): [string, Partial<TabDocument>] => [
  path,
  JSON.parse(readFileSync(path, "utf8")),
]);

console.log(`HIDE ${HIDE}, FULL ${FULL}`);
console.log("notes  at/below HIDE  partly faded  hidden  passages  document");
for (const [path, doc] of docs) {
  const notes = doc.notes ?? [];
  const weak = notes.filter((note) => note.confidence <= HIDE).length;
  const partly = notes.filter((note) => note.confidence > HIDE && note.confidence < FULL).length;
  const passages = hiddenPassages(notes);
  const hidden = notes.filter((note) => isHidden(passages, note.t));
  console.log(
    [
      String(notes.length).padStart(5),
      share(weak, notes.length).padStart(14),
      share(partly, notes.length).padStart(13),
      share(hidden.length, notes.length).padStart(7),
      String(passages.length).padStart(9),
      ` ${path}`,
    ].join(" "),
  );
}

console.log(`\nCHORD_HIDE ${CHORD_HIDE}, CHORD_FULL ${CHORD_FULL}`);
console.log("chords  at/below CHORD_HIDE  partly faded  document");
for (const [path, doc] of docs) {
  const chords = doc.chords ?? [];
  const weak = chords.filter((chord) => chord.confidence <= CHORD_HIDE).length;
  const partly = chords.filter(
    (chord) => chord.confidence > CHORD_HIDE && chord.confidence < CHORD_FULL,
  ).length;
  console.log(
    [
      String(chords.length).padStart(6),
      share(weak, chords.length).padStart(20),
      share(partly, chords.length).padStart(13),
      ` ${path}`,
    ].join(" "),
  );
}
