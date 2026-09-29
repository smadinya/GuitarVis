"""Tiny JAMS files shaped like GuitarSet's, for tests that need no dataset.

The real layout, as read from annotation.zip: six `note_midi` annotations
whose data_source is the string index, six `pitch_contour` annotations (which
the harness ignores), and two `chord` annotations — instructed (empty
data_source) then performed (non-empty data_source).
"""

import json
from collections.abc import Sequence
from pathlib import Path

PERFORMED_SOURCE = "Semi-automatic chord transcription with manual verification"


def _observations(rows: Sequence[tuple[float, float, object]]) -> list[dict]:
    return [
        {"time": t, "duration": d, "value": v, "confidence": None} for t, d, v in rows
    ]


def write_jams(
    directory: Path,
    name: str,
    *,
    notes: Sequence[tuple[float, float, float, int]] = (),
    performed: Sequence[tuple[float, float, str]] = (),
    instructed: Sequence[tuple[float, float, str]] = (),
    duration: float = 10.0,
) -> Path:
    annotations: list[dict] = []
    for string in range(6):
        annotations.append(
            {
                "namespace": "pitch_contour",
                "annotation_metadata": {"data_source": str(string)},
                "data": {"time": [], "duration": [], "value": [], "confidence": []},
            }
        )
        annotations.append(
            {
                "namespace": "note_midi",
                "annotation_metadata": {"data_source": str(string)},
                "data": _observations(
                    [(t, d, midi) for t, d, midi, s in notes if s == string]
                ),
            }
        )
    annotations.append(
        {
            "namespace": "chord",
            "annotation_metadata": {"data_source": ""},
            "data": _observations(instructed),
        }
    )
    annotations.append(
        {
            "namespace": "chord",
            "annotation_metadata": {"data_source": PERFORMED_SOURCE},
            "data": _observations(performed),
        }
    )

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jams"
    path.write_text(
        json.dumps(
            {
                "annotations": annotations,
                "file_metadata": {"title": name, "duration": duration},
                "sandbox": {},
            }
        )
    )
    return path
