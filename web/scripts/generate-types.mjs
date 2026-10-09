/**
 * Generate the web types from the committed JSON Schemas.
 *
 * Each schema and its generated file are both committed, so a contract change
 * shows up as a diff in review. Run via `make schema`, never by hand.
 */
import { mkdirSync, writeFileSync } from "node:fs";

import { compileFromFile } from "json-schema-to-typescript";

const CONTRACTS = [
  {
    schema: "../schema/tab-document.schema.json",
    from: "packages/core tabdoc.py",
    output: "src/types/tabDocument.ts",
  },
  {
    schema: "../schema/api.schema.json",
    from: "apps/api schemas.py",
    output: "src/types/api.ts",
  },
];

mkdirSync("src/types", { recursive: true });

for (const { schema, from, output } of CONTRACTS) {
  const ts = await compileFromFile(schema, {
    bannerComment:
      "/* GENERATED FILE — do not edit.\n" +
      ` * Source: ${schema.replace("../", "")} (from ${from}).\n` +
      " * Regenerate with `make schema`.\n" +
      " */",
    additionalProperties: false,
    style: { singleQuote: false },
  });
  writeFileSync(output, ts);
  console.log(`wrote ${output}`);
}
