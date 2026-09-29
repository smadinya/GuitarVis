"""Reading GuitarSet: strings, rounding, which chords count, and the split."""

from pathlib import Path

import pytest
from guitarset_fixture import write_jams
from guitarvis_eval.dataset import (
    DEFAULT_DATA_DIR,
    DatasetMissing,
    TruthChord,
    TruthNote,
    data_dir,
    excerpt_paths,
    mic_audio_path,
    read_jams,
)


def test_notes_take_their_string_from_the_annotation(tmp_path: Path) -> None:
    path = write_jams(
        tmp_path,
        "00_BN1-129-Eb_comp",
        notes=[(0.5, 0.4, 51.04, 1), (0.1, 0.3, 44.02, 0)],
    )
    excerpt = read_jams(path)

    # Rounded to MIDI, sorted by onset, string straight from data_source.
    assert excerpt.notes == [
        TruthNote(onset=0.1, duration=0.3, midi=44, string=0),
        TruthNote(onset=0.5, duration=0.4, midi=51, string=1),
    ]


def test_pitches_round_to_the_nearest_semitone(tmp_path: Path) -> None:
    path = write_jams(tmp_path, "00_x_solo", notes=[(0.0, 0.1, 58.51, 2)])
    assert read_jams(path).notes[0].midi == 59


def test_performed_chords_are_used_not_instructed(tmp_path: Path) -> None:
    path = write_jams(
        tmp_path,
        "00_x_comp",
        instructed=[(0.0, 4.0, "D#:maj")],
        performed=[(0.0, 4.0, "D#:sus2(7)/1"), (4.0, 2.0, "G#:maj6(*5)/1")],
    )
    assert read_jams(path).chords == [
        TruthChord(start=0.0, end=4.0, label="D#:sus2(7)/1"),
        TruthChord(start=4.0, end=6.0, label="G#:maj6(*5)/1"),
    ]


def test_excerpt_metadata_comes_from_the_name(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "05_Rock2-85-F_solo", duration=21.5))

    assert excerpt.name == "05_Rock2-85-F_solo"
    assert excerpt.player == "05"
    assert excerpt.style == "solo"
    assert excerpt.duration == 21.5


def test_split_is_by_player(tmp_path: Path) -> None:
    annotations = tmp_path / "annotation"
    for name in ("05_b_solo", "00_a_comp", "05_a_comp", "04_a_solo"):
        write_jams(annotations, name)

    assert [p.stem for p in excerpt_paths(tmp_path, "test")] == [
        "05_a_comp",
        "05_b_solo",
    ]
    assert [p.stem for p in excerpt_paths(tmp_path, "dev")] == [
        "00_a_comp",
        "04_a_solo",
    ]


def test_missing_dataset_says_how_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(DatasetMissing, match="make eval-data"):
        excerpt_paths(tmp_path, "test")


def test_data_dir_honours_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GUITARSET_DIR", str(tmp_path))
    assert data_dir() == tmp_path

    monkeypatch.delenv("GUITARSET_DIR")
    assert data_dir() == DEFAULT_DATA_DIR


def test_mic_audio_path_follows_the_archive_naming(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "00_BN1-129-Eb_comp"))
    assert mic_audio_path(Path("/data"), excerpt) == Path(
        "/data/audio_mono-mic/00_BN1-129-Eb_comp_mic.wav"
    )
