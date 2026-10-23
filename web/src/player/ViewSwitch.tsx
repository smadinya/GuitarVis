import { useCallback, useState } from "react";

import { Button } from "./Button";

/** What the page shows: the guitar in 3D, the guitar as a flat fretboard, or
 * the tab alone. Not the guitar's own `View`: the guitar's modules are
 * reached only through `React.lazy`, so this file may not import them, and
 * `Player` narrows this to the guitar's two before it hands one over. */
export type PageView = "3d" | "2d" | "tab";

/** 008's key, kept so that a returning user keeps their view. */
export const VIEW_KEY = "guitarvis.guitar-view";

const VIEWS: Array<[PageView, string]> = [
  ["3d", "3D"],
  ["2d", "Fretboard"],
  ["tab", "Tab only"],
];

/** The remembered view; a first visit, a value that is not a view, or storage
 * that is off gets 3D. */
function readView(): PageView {
  try {
    const stored = localStorage.getItem(VIEW_KEY);
    return stored === "2d" || stored === "3d" || stored === "tab" ? stored : "3d";
  } catch {
    return "3d";
  }
}

function writeView(view: PageView): void {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // Storage is off: the choice lasts until the page closes.
  }
}

/** The remembered view, and a setter that remembers it. Read once, when the
 * page mounts, so a switch costs one write and no read. */
export function useStoredView(): [PageView, (view: PageView) => void] {
  const [view, setView] = useState(readView);
  const choose = useCallback((next: PageView) => {
    setView(next);
    writeView(next);
  }, []);
  return [view, choose];
}

/** The page's choice of view, one segmented group. It is the page's, not the
 * guitar's, because "Tab only" takes the guitar away. */
export function ViewSwitch({ view, onChange }: { view: PageView; onChange: (view: PageView) => void }) {
  return (
    <div className="segmented" role="group" aria-label="View">
      {VIEWS.map(([value, label]) => (
        <Button key={value} pressed={view === value} onClick={() => onChange(value)}>
          {label}
        </Button>
      ))}
    </div>
  );
}
