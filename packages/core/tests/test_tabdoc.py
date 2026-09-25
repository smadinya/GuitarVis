"""The tab document is the contract between the pipeline and every client.

These tests pin the parts a client would break on: the version, the field
names, and the refusal to silently accept anything unexpected.
"""

import json
from pathlib import Path

import pytest
from guitarvis_core.tabdoc import SCHEMA_VERSION, TabDocument
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures" / "minimal.tabdoc.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_schema_version_is_one() -> None:
    assert SCHEMA_VERSION == 1


def test_fixture_validates() -> None:
    doc = TabDocument.model_validate(load_fixture())

    assert doc.schema_version == 1
    assert doc.source.title == "Fixture Song"
    assert len(doc.notes) == 2
    assert doc.notes[1].midi == 52
    assert doc.notes[1].string == 2
    assert doc.notes[1].fret == 2


def test_round_trip_is_lossless() -> None:
    raw = load_fixture()

    doc = TabDocument.model_validate(raw)
    again = json.loads(doc.model_dump_json())

    assert again == raw


def test_unknown_fields_are_rejected() -> None:
    raw = load_fixture()
    raw["notes"][0]["vibrato"] = True

    with pytest.raises(ValidationError):
        TabDocument.model_validate(raw)


def test_confidence_outside_zero_to_one_is_rejected() -> None:
    raw = load_fixture()
    raw["notes"][0]["confidence"] = 1.4

    with pytest.raises(ValidationError):
        TabDocument.model_validate(raw)


def test_optional_tracks_default_to_empty() -> None:
    """A degraded job omits tracks; it must not have to send empty scaffolding."""
    raw = load_fixture()
    del raw["chords"]
    del raw["sections"]

    doc = TabDocument.model_validate(raw)

    assert doc.chords == []
    assert doc.sections == []
