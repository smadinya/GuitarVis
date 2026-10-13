// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import type { Mark } from "./layout";
import { MarkLayer } from "./marks";

const SVG = "http://www.w3.org/2000/svg";

function dot(key: string, fields: Partial<Extract<Mark, { kind: "dot" }>> = {}): Mark {
  return { kind: "dot", key, x: 10, y: 20, r: 11, name: "E", opacity: 1, ...fields };
}

const CHORD: Mark = { kind: "message", key: "message", x: 0, y: 0, text: "Am", chord: true, opacity: 1 };

describe("MarkLayer", () => {
  let layer: SVGGElement;
  let marks: MarkLayer;

  beforeEach(() => {
    const svg = document.createElementNS(SVG, "svg");
    layer = document.createElementNS(SVG, "g");
    svg.append(layer);
    document.body.replaceChildren(svg);
    marks = new MarkLayer(layer);
  });

  const nodes = (selector: string) => [...layer.querySelectorAll(selector)];

  it("creates a node for a new key", () => {
    marks.apply([dot("dot:n1", { name: "C#", opacity: 0.35 })]);

    const [node] = nodes(".fret-dot");
    expect(node.getAttribute("transform")).toBe("translate(10 20)");
    expect(node.getAttribute("opacity")).toBe("0.35");
    expect(node.querySelector("circle")?.getAttribute("r")).toBe("11");
    expect(node.querySelector("text")?.textContent).toBe("C#");
  });

  it("reuses the node for the same key, and updates its attributes", () => {
    marks.apply([dot("dot:n1")]);
    const [before] = nodes(".fret-dot");

    marks.apply([dot("dot:n1", { x: 40, opacity: 0.5 })]);

    const [after] = nodes(".fret-dot");
    expect(after).toBe(before);
    expect(after.getAttribute("transform")).toBe("translate(40 20)");
    expect(after.getAttribute("opacity")).toBe("0.5");
    expect(nodes(".fret-dot")).toHaveLength(1);
  });

  it("removes the node of a key that is gone", () => {
    marks.apply([dot("dot:n1"), dot("dot:n2", { y: 50 })]);

    marks.apply([dot("dot:n2", { y: 50 })]);

    expect(nodes(".fret-dot").map((n) => n.getAttribute("transform"))).toEqual(["translate(10 50)"]);
  });

  it("draws in two groups, the dots and then the message", () => {
    expect([...layer.children].map((g) => g.getAttribute("class"))).toEqual(["fret-dots", "fret-messages"]);
  });

  it("draws a message over the dots, whatever order they arrive in", () => {
    marks.apply([CHORD, dot("dot:n1")]);

    const order = nodes(".fret-dot, .fret-message").map((n) => n.getAttribute("class"));
    expect(order).toEqual(["fret-dot", "fret-message fret-chord"]);
  });

  it("restyles the message when it changes from a chord to the unclear label", () => {
    marks.apply([CHORD]);
    const [before] = nodes(".fret-message");

    marks.apply([{ ...CHORD, text: "unclear passage", chord: false }]);

    expect(nodes(".fret-message")).toEqual([before]);
    expect(before.getAttribute("class")).toBe("fret-message");
    expect(before.textContent).toBe("unclear passage");
  });

  it("removes everything it drew on dispose", () => {
    marks.apply([dot("dot:n1"), CHORD]);

    marks.dispose();

    expect(layer.childNodes).toHaveLength(0);
  });
});
