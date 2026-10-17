/**
 * The guitar's painted textures: the dots and rings that name the sounding
 * notes, and the text the model hangs on the headstock and under the neck.
 * Each is drawn on a 2D canvas and handed to three.js.
 *
 * Browser-only. With no 2D context (jsdom, or a browser without canvas) a
 * painter returns a blank texture, and never throws: the guitar then draws
 * without names.
 */
import { CanvasTexture, SRGBColorSpace, Texture } from "three";

import type { TextPainter } from "./model";
import type { DotPainter } from "./notes";

/** The colours that follow the page's colour scheme. The guitar keeps its own. */
export interface Palette {
  background: string;
  dot: string;
  dotText: string;
}

/** An open string's name. Its ring lies over the headstock, which is dark in
 * both themes, so the name is always light. */
export const RING_TEXT = "#f4efe2";
/** A dot's edge, which keeps it apart from the rosewood. */
const DOT_EDGE = "rgba(255,255,255,0.92)";
/** A dot's canvas is this many pixels square. */
const DOT_PX = 128;
/** A line of text's canvas is this many pixels tall, and as wide as the text. */
const TEXT_PX = 64;
const TEXT_FONT = "600 48px system-ui, sans-serif";

/** Colours come from the --guitar-* custom properties in styles.css, as the
 * tab strip's come from its --tab-* ones. */
export function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const read = (name: string) => style.getPropertyValue(`--guitar-${name}`).trim() || "#888";
  return { background: read("background"), dot: read("dot"), dotText: read("dot-text") };
}

function canvasTexture(canvas: HTMLCanvasElement): Texture {
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}

/**
 * A fretted note is a filled dot and an open string a ring, each with the
 * note's name. `palette` is read at each paint, so a texture painted after a
 * colour-scheme change takes the new colours.
 */
export function dotPainter(palette: () => Palette): DotPainter {
  return (name, open) => {
    const canvas = document.createElement("canvas");
    canvas.width = DOT_PX;
    canvas.height = DOT_PX;
    const context = canvas.getContext("2d");
    if (context === null) return new Texture();

    const { dot, dotText } = palette();
    const middle = DOT_PX / 2;
    context.beginPath();
    if (open) {
      context.arc(middle, middle, 55, 0, Math.PI * 2);
      context.lineWidth = 13;
      context.strokeStyle = dot;
      context.stroke();
    } else {
      context.arc(middle, middle, 59, 0, Math.PI * 2);
      context.fillStyle = dot;
      context.fill();
      context.lineWidth = 5;
      context.strokeStyle = DOT_EDGE;
      context.stroke();
    }
    context.fillStyle = open ? RING_TEXT : dotText;
    context.font = `600 ${name.length > 1 ? 50 : 62}px system-ui, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    // A little below the middle: the glyphs' visual centre sits under their box's.
    context.fillText(name, middle, middle + 4);

    const texture = canvasTexture(canvas);
    texture.anisotropy = 4;
    return texture;
  };
}

/** One line of text, on a canvas as wide as the text. */
export const paintText: TextPainter = (text, colour) => {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (context === null) return { texture: new Texture(), aspect: 1 };

  context.font = TEXT_FONT;
  const width = Math.max(1, Math.ceil(context.measureText(text).width));
  canvas.width = width;
  canvas.height = TEXT_PX;
  // Sizing a canvas resets its context, font and all.
  context.font = TEXT_FONT;
  context.fillStyle = colour;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, width / 2, TEXT_PX / 2);
  return { texture: canvasTexture(canvas), aspect: width / TEXT_PX };
};
