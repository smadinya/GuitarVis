// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import type { Mark } from "./layout";
import { MarkLayer } from "./marks";

const SVG = "http://www.w3.org/2000/svg";

function dot(key: string, fields: Partial<Extract<Mark, { kind: "dot" }>> = {}): Mark {
  return { kind: "dot", key, x: 10, y: 20, r: 11, name: "E", opacity: 1, ...fields };
}

function ring(key: string, r: number): Mark {
  return { kind: "ring", key, x: 30, y: 40, r, opacity: 0.5 };
}

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
    marks.apply([ring("ring:0:3", 22)]);
    const [before] = nodes(".fret-ring");

    marks.apply([ring("ring:0:3", 16.5)]);

    const [after] = nodes(".fret-ring");
    expect(after).toBe(before);
    expect(after.getAttribute("r")).toBe("16.5");
    expect(nodes(".fret-ring")).toHaveLength(1);
  });

  it("removes the node of a key that is gone", () => {
    marks.apply([dot("dot:n1"), dot("dot:n2", { y: 50 })]);

    marks.apply([dot("dot:n2", { y: 50 })]);

    expect(nodes(".fret-dot").map((n) => n.getAttribute("transform"))).toEqual(["translate(10 50)"]);
  });

  it("draws rings under dots, and a message over both, whatever order they arrive in", () => {
    const message: Mark = { kind: "message", key: "message", x: 0, y: 0, text: "Am", chord: true, opacity: 1 };

    marks.apply([message, dot("dot:n1"), ring("ring:0:3", 20)]);

    const order = nodes(".fret-ring, .fret-dot, .fret-message").map((n) => n.getAttribute("class"));
    expect(order).toEqual(["fret-ring", "fret-dot", "fret-message fret-chord"]);
  });

  it("restyles the message when it changes from a chord to the unclear label", () => {
    const chord: Mark = { kind: "message", key: "message", x: 0, y: 0, text: "Am", chord: true, opacity: 1 };
    marks.apply([chord]);
    const [before] = nodes(".fret-message");

    marks.apply([{ ...chord, text: "unclear passage", chord: false }]);

    expect(nodes(".fret-message")).toEqual([before]);
    expect(before.getAttribute("class")).toBe("fret-message");
    expect(before.textContent).toBe("unclear passage");
  });

  it("removes everything it drew on dispose", () => {
    marks.apply([dot("dot:n1"), ring("ring:0:3", 20)]);

    marks.dispose();

    expect(layer.childNodes).toHaveLength(0);
  });
});
