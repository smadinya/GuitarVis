/**
 * What the confidence thresholds do to real tab documents: the share of
 * notes they fade and hide. Recorded in
 * docs/specs/006-tab-view-sync/calibration.md as the sanity check on
 * thresholds measured on GuitarSet.
 *
 *   node scripts/confidence-report.ts <tab document JSON>...
 *
 * Node runs the TypeScript directly (type stripping, Node 22.18 and later),
 * using the same functions the views use.
 */
import { readFileSync } from "node:fs";

import { FULL, HIDE, hiddenPassages } from "../src/confidence.ts";
import type { Note } from "../src/types/tabDocument.ts";

function share(count: number, total: number): string {
  return total === 0 ? "—" : `${((100 * count) / total).toFixed(0)}%`;
}

console.log(`HIDE ${HIDE}, FULL ${FULL}`);
console.log("notes  at/below HIDE  partly faded  hidden  passages  document");
for (const path of process.argv.slice(2)) {
  const notes: Note[] = JSON.parse(readFileSync(path, "utf8")).notes ?? [];
  const weak = notes.filter((note) => note.confidence <= HIDE).length;
  const partly = notes.filter((note) => note.confidence > HIDE && note.confidence < FULL).length;
  const passages = hiddenPassages(notes);
  const hidden = notes.filter((note) => passages.some((p) => p.from <= note.t && note.t <= p.to));
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
