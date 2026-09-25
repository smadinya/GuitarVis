"""Emit the tab document JSON Schema.

The committed schema is what a future iOS or desktop client reads. Generating
it from the Pydantic models rather than maintaining it by hand is what makes
"one contract, many clients" structural instead of aspirational.

Run via `make schema`.
"""

import json
import sys
from pathlib import Path

from guitarvis_core.tabdoc import TabDocument

DEFAULT_OUTPUT = Path("schema/tab-document.schema.json")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output = Path(args[0]) if args else DEFAULT_OUTPUT

    schema = TabDocument.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "TabDocument"

    output.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys makes regeneration byte-stable, so a diff means a real change.
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
