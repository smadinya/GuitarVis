import { useState } from "react";

import { AlertIcon } from "../icons";
import { Button } from "./Button";

/** The document's warnings. A tab the user cannot tell is degraded is worse
 * than one labelled as such. One warning shows its text. Several collapse to
 * a count with a Show button, so they do not push the player down the page;
 * the choice is not remembered, as the warnings are a note about this load. */
export function Warnings({ warnings }: { warnings: readonly string[] }) {
  const [open, setOpen] = useState(false);
  if (warnings.length === 0) return null;

  const several = warnings.length > 1;
  return (
    <aside className="warnings" aria-label="Warnings">
      <AlertIcon />
      <p>{several ? `${warnings.length} things to know about this tab` : warnings[0]}</p>
      {several && (
        <Button expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show"}
        </Button>
      )}
      {several && open && (
        <ul>
          {warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
    </aside>
  );
}
