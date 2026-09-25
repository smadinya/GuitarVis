"""Emit the tab document JSON Schema.

The committed schema is what a future iOS or desktop client reads. Generating
it from the Pydantic models rather than maintaining it by hand is what makes
"one contract, many clients" structural instead of aspirational.

Run via `make schema`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from guitarvis_core.tabdoc import TabDocument

DEFAULT_OUTPUT = Path("schema/tab-document.schema.json")


def _strip_property_titles(node: Any) -> None:
    """Remove Pydantic's auto-generated per-field titles, in place.

    Pydantic titles every *field* (Note.string -> "String", Note.t -> "T"),
    and json-schema-to-typescript hoists a standalone named export for every
    schema node that carries a title — including leaf scalars. Left alone,
    that produces `export type String = number` (shadowing the JS global) and
    a pile of numbered duplicates (T1, T2, Dur1, Confidence1, ...) with no
    documentation value: a client reads the TabDocument/Note/Chord/... field
    names directly, never these synthetic aliases.

    This walks every "properties" mapping in the schema (the top-level
    TabDocument properties and every $defs object's properties) and deletes
    the "title" key each property carries directly, however that property is
    shaped — plain scalar, `anyOf` (optional/nullable fields), or array
    `items`. It never touches a dict's own "title" — only titles attached to
    entries *inside* a "properties" mapping — so the model names in $defs
    (Note, Chord, Section, ...) and the explicit root title survive, and
    those are what become the named TypeScript interfaces.
    """
    if not isinstance(node, dict):
        return

    properties = node.get("properties")
    if isinstance(properties, dict):
        for prop_schema in properties.values():
            if isinstance(prop_schema, dict):
                prop_schema.pop("title", None)

    for value in node.values():
        if isinstance(value, dict):
            _strip_property_titles(value)
        elif isinstance(value, list):
            for item in value:
                _strip_property_titles(item)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output = Path(args[0]) if args else DEFAULT_OUTPUT

    schema = TabDocument.model_json_schema()
    _strip_property_titles(schema)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "TabDocument"

    output.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys makes regeneration byte-stable, so a diff means a real change.
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
