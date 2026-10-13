/**
 * The keyed updater: applies each frame's marks to an SVG layer without
 * React. A mark's key is stable across frames, so its node is created once,
 * has its attributes set while the key lasts, and is removed when the key is
 * gone. Colours, strokes and fonts come from the classes, in styles.css.
 */
import type { Mark } from "./layout";

const SVG = "http://www.w3.org/2000/svg";

type Kind = Mark["kind"];

/** Drawn in this order, so a message sits over the dots. */
const KINDS: readonly Kind[] = ["dot", "message"];

export class MarkLayer {
  private readonly groups: Record<Kind, SVGGElement>;
  private readonly nodes = new Map<string, SVGElement>();

  /** Takes `layer` over: React renders it empty and leaves it alone. */
  constructor(layer: SVGGElement) {
    const group = (kind: Kind) => {
      const g = document.createElementNS(SVG, "g");
      g.setAttribute("class", `fret-${kind}s`);
      layer.append(g);
      return g;
    };
    this.groups = { dot: group("dot"), message: group("message") };
  }

  apply(marks: readonly Mark[]): void {
    const seen = new Set<string>();
    for (const mark of marks) {
      seen.add(mark.key);
      let node = this.nodes.get(mark.key);
      if (node === undefined) {
        node = create(mark.kind);
        this.groups[mark.kind].append(node);
        this.nodes.set(mark.key, node);
      }
      update(node, mark);
    }
    for (const [key, node] of this.nodes) {
      if (seen.has(key)) continue;
      node.remove();
      this.nodes.delete(key);
    }
  }

  /** Remove every mark, and the groups that held them. */
  dispose(): void {
    for (const kind of KINDS) this.groups[kind].remove();
    this.nodes.clear();
  }
}

function create(kind: Kind): SVGElement {
  switch (kind) {
    case "dot": {
      const dot = element("g", "fret-dot");
      dot.append(element("circle"), element("text"));
      return dot;
    }
    case "message":
      return element("text", "fret-message");
  }
}

function update(node: SVGElement, mark: Mark): void {
  set(node, "opacity", mark.opacity);
  switch (mark.kind) {
    case "dot": {
      set(node, "transform", `translate(${mark.x} ${mark.y})`);
      const [circle, text] = node.children;
      set(circle, "r", mark.r);
      if (text.textContent !== mark.name) text.textContent = mark.name;
      break;
    }
    case "message":
      set(node, "class", mark.chord ? "fret-message fret-chord" : "fret-message");
      set(node, "x", mark.x);
      set(node, "y", mark.y);
      if (node.textContent !== mark.text) node.textContent = mark.text;
      break;
  }
}

function element(name: string, className?: string): SVGElement {
  const node = document.createElementNS(SVG, name);
  if (className !== undefined) node.setAttribute("class", className);
  return node;
}

/** Only writes what changed: most marks hold still for most frames. */
function set(node: Element, name: string, value: string | number): void {
  const text = String(value);
  if (node.getAttribute(name) !== text) node.setAttribute(name, text);
}
