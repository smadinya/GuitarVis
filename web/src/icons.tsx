import type { ReactNode } from "react";

/** One icon's frame. The glyph takes its colour from the button's text, and
 * is hidden from assistive tech: a button that shows only an icon carries an
 * `aria-label`. */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** The seconds a skip button moves by, drawn in the arrow's middle. */
function Five() {
  return (
    <text x="12" y="15.5" fontSize="6.5" fontWeight="700" textAnchor="middle">
      5
    </text>
  );
}

/** Play: the transport's main button while the song is paused. */
export function PlayIcon() {
  return (
    <Icon>
      <path d="M8 5v14l11-7z" />
    </Icon>
  );
}

/** Pause: the transport's main button while the song plays. */
export function PauseIcon() {
  return (
    <Icon>
      <path d="M7 5h4v14H7zM13 5h4v14h-4z" />
    </Icon>
  );
}

/** Back 5 seconds. */
export function BackIcon() {
  return (
    <Icon>
      <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z" />
      <Five />
    </Icon>
  );
}

/** Forward 5 seconds. */
export function ForwardIcon() {
  return (
    <Icon>
      <path d="M4 13c0 4.4 3.6 8 8 8s8-3.6 8-8h-2c0 3.3-2.7 6-6 6s-6-2.7-6-6 2.7-6 6-6v4l5-5-5-5v4c-4.4 0-8 3.6-8 8z" />
      <Five />
    </Icon>
  );
}

/** The link field's marker: two chain links. */
export function LinkIcon() {
  return (
    <Icon>
      <path d="M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8v2zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z" />
    </Icon>
  );
}

/** The warnings line's marker. */
export function AlertIcon() {
  return (
    <Icon>
      <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" />
    </Icon>
  );
}
