import { useEffect } from "react";

import { SEEK_STEP_SEC, type PlaybackEngine } from "../playback/engine";

/**
 * Space plays and pauses; ← and → seek five seconds. The handler sits on the
 * window. It leaves keys aimed at text fields alone, and leaves Space to a
 * focused button or link, which Space activates.
 */
export function useTransportKeys(engine: PlaybackEngine | null): void {
  useEffect(() => {
    if (engine === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (takesText(event.target)) return;
      if (event.key === " ") {
        if (activates(event.target)) return;
        event.preventDefault(); // and do not scroll the page
        if (!event.repeat) engine.toggle();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        engine.seekBy(-SEEK_STEP_SEC);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        engine.seekBy(SEEK_STEP_SEC);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [engine]);
}

const NOT_TEXT = new Set(["button", "checkbox", "radio", "range", "submit", "reset", "file"]);

function takesText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  return target instanceof HTMLInputElement && !NOT_TEXT.has(target.type);
}

function activates(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLButtonElement ||
    target instanceof HTMLAnchorElement ||
    target instanceof HTMLInputElement
  );
}
