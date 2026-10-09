"""Emit the JSON Schema of the api's response bodies.

`make schema` writes schema/api.schema.json from these models and turns it
into web/src/types/api.ts, as it does for the tab document. The reason
vocabulary is the point: a reason added on the server regenerates the web
types, and the client's `Record<Reason, ...>` stops compiling until the new
reason has text.

Run via `make schema`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from guitarvis_core.schema_export import strip_property_titles
from pydantic.json_schema import models_json_schema

from guitarvis_api.errors import ErrorBody
from guitarvis_api.schemas import JobView

DEFAULT_OUTPUT = Path("schema/api.schema.json")


def api_schema() -> dict[str, Any]:
    """Every body the api answers with: a job, or an error.

    The root is the union of the two, so the generator emits a type for each
    model without needing a list of unreachable definitions.
    """
    _, definitions = models_json_schema(
        [(JobView, "serialization"), (ErrorBody, "serialization")],
        ref_template="#/$defs/{model}",
    )
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ApiResponse",
        "anyOf": [{"$ref": "#/$defs/JobView"}, {"$ref": "#/$defs/ErrorBody"}],
        **definitions,
    }
    strip_property_titles(schema)
    return schema


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output = Path(args[0]) if args else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys makes regeneration byte-stable, so a diff means a real change.
    output.write_text(json.dumps(api_schema(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
