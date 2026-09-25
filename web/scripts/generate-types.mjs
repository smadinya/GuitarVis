/**
 * Generate web/src/types/tabDocument.ts from the committed JSON Schema.
 *
 * Both artifacts are committed so a contract change shows up as a diff in
 * review. Run via `make schema`, never by hand.
 */
import { mkdirSync, writeFileSync } from "node:fs";

import { compileFromFile } from "json-schema-to-typescript";

const SCHEMA = "../schema/tab-document.schema.json";
const OUTPUT = "src/types/tabDocument.ts";

const ts = await compileFromFile(SCHEMA, {
  bannerComment:
    "/* GENERATED FILE — do not edit.\n" +
    " * Source: schema/tab-document.schema.json (from packages/core tabdoc.py).\n" +
    " * Regenerate with `make schema`.\n" +
    " */",
  additionalProperties: false,
  style: { singleQuote: false },
});

mkdirSync("src/types", { recursive: true });
writeFileSync(OUTPUT, ts);

console.log(`wrote ${OUTPUT}`);
