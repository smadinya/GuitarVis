"""GuitarSet on disk: where it lives, how its JAMS files read, how it splits.

A standard-library reader rather than `jams` or `mirdata`: an excerpt is six
note arrays and a chord array in one JSON file, and that is all the harness
needs from it.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Split = Literal["test", "dev"]

TEST_PLAYERS = frozenset({"05"})
DEFAULT_DATA_DIR = Path.home() / ".cache" / "guitarvis" / "guitarset"
ANNOTATION_DIR = "annotation"
MIC_AUDIO_DIR = "audio_mono-mic"


class DatasetMissing(Exception):
    """GuitarSet is not where the harness looked for it."""


@dataclass(frozen=True)
class TruthNote:
    onset: float
    duration: float
    midi: int
    string: int  # 0 is the lowest string, as in tabdoc.Note


@dataclass(frozen=True)
class TruthChord:
    start: float
    end: float
    label: str  # as annotated, e.g. "D#:sus2(7)/1"


@dataclass(frozen=True)
class Excerpt:
    name: str  # e.g. "05_BN1-129-Eb_comp"
    player: str  # "00".."05"
    style: str  # "comp" or "solo"
    duration: float
    notes: list[TruthNote]
    chords: list[TruthChord]


def data_dir() -> Path:
    """GUITARSET_DIR if set, else the cache `make eval-data` fills."""
    configured = os.environ.get("GUITARSET_DIR")
    return Path(configured) if configured else DEFAULT_DATA_DIR


def excerpt_paths(root: Path, split: Split) -> list[Path]:
    """The split's JAMS files, sorted. Split by player so one player's habits
    cannot leak between tuning and measurement."""
    annotations = root / ANNOTATION_DIR
    paths = sorted(annotations.glob("*.jams"))
    if not paths:
        raise DatasetMissing(
            f"no GuitarSet annotations under {annotations}. Run `make eval-data`, "
            "or point GUITARSET_DIR at an existing copy."
        )
    in_test = split == "test"
    return [p for p in paths if (p.name[:2] in TEST_PLAYERS) == in_test]


def mic_audio_path(root: Path, excerpt: Excerpt) -> Path:
    return root / MIC_AUDIO_DIR / f"{excerpt.name}_mic.wav"


def read_jams(path: Path) -> Excerpt:
    """One GuitarSet excerpt.

    Each of the six `note_midi` annotations is one string; its
    `annotation_metadata.data_source` is the string index with 0 as low E —
    the same convention as tabdoc.Note.string. Pitches are annotated as
    floats and rounded to the nearest MIDI number.

    There are two `chord` annotations: the instructed chords from the lead
    sheet (empty data_source) and the performed chords transcribed from what
    was actually played (non-empty data_source). The harness scores against
    what was played.
    """
    document = json.loads(path.read_text())
    name = document["file_metadata"]["title"]
    notes: list[TruthNote] = []
    chord_annotations = []

    for annotation in document["annotations"]:
        namespace = annotation["namespace"]
        if namespace == "note_midi":
            string = int(annotation["annotation_metadata"]["data_source"])
            notes.extend(
                TruthNote(
                    onset=float(obs["time"]),
                    duration=float(obs["duration"]),
                    midi=round(obs["value"]),
                    string=string,
                )
                for obs in annotation["data"]
            )
        elif namespace == "chord":
            chord_annotations.append(annotation)

    performed = [
        a for a in chord_annotations if a["annotation_metadata"].get("data_source")
    ]
    chords = [
        TruthChord(
            start=float(obs["time"]),
            end=float(obs["time"]) + float(obs["duration"]),
            label=str(obs["value"]),
        )
        for obs in (performed[0]["data"] if performed else [])
    ]

    notes.sort(key=lambda n: (n.onset, n.string))
    return Excerpt(
        name=name,
        player=name[:2],
        style=name.rsplit("_", 1)[-1],
        duration=float(document["file_metadata"]["duration"]),
        notes=notes,
        chords=chords,
    )
