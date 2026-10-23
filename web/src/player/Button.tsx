import type { MouseEvent, ReactNode } from "react";

/** A clicked button does not keep focus, so Space stays play/pause rather
 * than clicking the last button again. Keyboard focus still works. */
export function keepFocus(event: MouseEvent) {
  event.preventDefault();
}

export interface ButtonProps {
  onClick: () => void;
  /** aria-pressed: a toggle that is on or off. */
  pressed?: boolean;
  /** aria-expanded: a button that shows or hides something. */
  expanded?: boolean;
  /** aria-current="true" while true, and no attribute otherwise: the sidebar's
   * row for the section or chord that is playing. */
  current?: boolean;
  /** aria-label, for a button that shows only an icon. */
  label?: string;
  className?: string;
  children: ReactNode;
}

/** The player's one button. It never takes focus from a mouse click, so the
 * page's Space key keeps meaning play/pause wherever the pointer has been. */
export function Button({
  onClick,
  pressed,
  expanded,
  current,
  label,
  className,
  children,
}: ButtonProps) {
  return (
    <button
      type="button"
      onMouseDown={keepFocus}
      onClick={onClick}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-current={current ? "true" : undefined}
      aria-label={label}
      className={className}
    >
      {children}
    </button>
  );
}
