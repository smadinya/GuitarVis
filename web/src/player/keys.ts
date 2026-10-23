import { useEffect } from "react";

import { SEEK_STEP_SEC, type PlaybackEngine } from "../playback/engine";

/**
 * Space plays and pauses; ← and → seek five seconds; [ and ] set the loop's A
 * and B at the current time. The handler sits on the window. It leaves keys
 * aimed at text fields alone, and leaves Space to a focused button or link,
 * which Space activates. A held Space, [ or ] acts once: auto-repeat would
 * otherwise flip the audio on and off, or drag a loop point along with the
 * playhead. (← and → repeat on purpose, to scrub.)
 *
 * The shortcuts that the browser or the system own (Ctrl, Alt, Meta) are left
 * alone, with one exception: [ and ] are typed with AltGr on many layouts
 * (German, French, Swiss, Nordic), and Windows reports AltGr as Ctrl and Alt
 * together. A bracket typed that way is a bracket, and Ctrl+Alt+[ is no
 * shortcut anyone relies on. Space and the arrows keep the full guard.
 */
export function useTransportKeys(engine: PlaybackEngine | null): void {
  useEffect(() => {
    if (engine === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey) return;
      const bracket = event.key === "[" || event.key === "]";
      if ((event.altKey || event.ctrlKey) && !(bracket && typedWithAltGr(event))) return;
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
      } else if (event.key === "[") {
        event.preventDefault();
        if (!event.repeat) engine.setLoopPoint("a");
      } else if (event.key === "]") {
        event.preventDefault();
        if (!event.repeat) engine.setLoopPoint("b");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [engine]);
}

/** Whether the key was typed with AltGr: the browser says so, or (Windows)
 * reports Ctrl and Alt together. */
function typedWithAltGr(event: KeyboardEvent): boolean {
  return event.getModifierState("AltGraph") || (event.ctrlKey && event.altKey);
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
