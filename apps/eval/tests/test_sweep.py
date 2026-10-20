"""The sweep: a dev-only tuning tool. Argument parsing, the transcription cache,
and the table it prints."""

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from guitarset_fixture import write_jams
from guitarvis_core.contracts import NoteEvent
from guitarvis_eval import results
from guitarvis_eval.sweep import (
    CachedTranscriptions,
    SweepError,
    build,
    combinations,
    main,
    parse_grid,
    settings_key,
)
from guitarvis_worker.stages.fretboard import MapperCosts
from guitarvis_worker.stages.transcription import TranscriptionSettings
from test_full import EchoTranscriber

NOTES = [(0.0, 0.5, 40.0, 0), (1.0, 0.5, 45.0, 1)]
HEARD = [NoteEvent(0.0, 0.5, 40, 0.9), NoteEvent(1.0, 0.5, 45, 0.8)]
OVERLAP_HEADER = "overrides\toracle_comp\toracle_solo\toracle_ovl"
FULL_HEADER = (
    f"{OVERLAP_HEADER}\tfull_comp\tfull_solo\tf1_comp\tf1_solo"
    "\tprec_comp\tprec_solo\tfull_ovl\tobj4\tobj2"
)


def _dev_set(root: Path) -> None:
    """Two dev excerpts and one test-split one, with audio files to match."""
    for name in ("00_a_comp", "01_b_solo", "05_c_comp"):
        write_jams(root / "annotation", name, notes=NOTES, duration=2.0)
        (root / "audio_mono-mic").mkdir(exist_ok=True)
        (root / "audio_mono-mic" / f"{name}_mic.wav").write_bytes(b"")


def _rows(capsys: pytest.CaptureFixture[str]) -> list[list[str]]:
    return [line.split("\t") for line in capsys.readouterr().out.splitlines()]


def test_parse_grid_splits_names_and_values() -> None:
    assert parse_grid(["gap_weight=0,0.3,0.6", "hand_window=5"]) == {
        "gap_weight": ["0", "0.3", "0.6"],
        "hand_window": ["5"],
    }
    assert parse_grid([]) == {}


@pytest.mark.parametrize("spec", ["gap_weight", "=1,2", "gap_weight="])
def test_parse_grid_refuses_a_spec_that_is_not_name_equals_values(spec: str) -> None:
    with pytest.raises(SweepError, match="NAME=V1,V2"):
        parse_grid([spec])


def test_parse_grid_refuses_a_name_given_twice() -> None:
    with pytest.raises(SweepError, match="gap_weight"):
        parse_grid(["gap_weight=0", "gap_weight=1"])


def test_combinations_are_the_product_in_order() -> None:
    grid = {"a": ["1", "2"], "b": ["x"]}
    assert combinations(grid) == [{"a": "1", "b": "x"}, {"a": "2", "b": "x"}]
    assert combinations({"a": ["1", "2"], "b": ["x", "y"]}) == [
        {"a": "1", "b": "x"},
        {"a": "1", "b": "y"},
        {"a": "2", "b": "x"},
        {"a": "2", "b": "y"},
    ]
    assert combinations({}) == [{}]


def test_build_coerces_by_field_type() -> None:
    costs = build(MapperCosts, {"hand_window": "5", "ring_weight": "0.5"})
    assert costs == MapperCosts(hand_window=5, ring_weight=0.5)
    assert isinstance(costs.hand_window, int)
    assert isinstance(costs.ring_weight, float)

    settings = build(TranscriptionSettings, {"melodia_trick": "false"})
    assert settings == TranscriptionSettings(melodia_trick=False)

    assert build(MapperCosts, {}) == MapperCosts()


@dataclass(frozen=True)
class _Probe:
    ratio: float | None = None
    flag: bool = False


def test_build_reads_none_for_an_optional_float() -> None:
    assert build(_Probe, {"ratio": "none"}) == _Probe(ratio=None)
    assert build(_Probe, {"ratio": "0.5"}) == _Probe(ratio=0.5)
    assert build(_Probe, {"flag": "true"}) == _Probe(flag=True)


@pytest.mark.parametrize(
    ("overrides", "complaint"),
    [
        ({"hand_window": "wide"}, "hand_window"),
        ({"hand_window": "4.5"}, "hand_window"),
        ({"ring_weight": "heavy"}, "ring_weight"),
        ({"hand_window": "none"}, "hand_window"),  # none is only for float | None
        ({"hand_window": "0"}, "hand_window must be at least 1"),  # __post_init__
    ],
)
def test_build_refuses_a_value_that_does_not_fit(
    overrides: dict[str, str], complaint: str
) -> None:
    with pytest.raises(SweepError, match=complaint):
        build(MapperCosts, overrides)


def test_build_refuses_anything_but_true_or_false_for_a_flag() -> None:
    with pytest.raises(SweepError, match=r"melodia_trick.*true or false"):
        build(TranscriptionSettings, {"melodia_trick": "yes"})


def test_a_misspelled_field_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dev_set(tmp_path)

    code = main(
        [
            "--cost",
            "hand_widow=4",
            "--data-dir",
            str(tmp_path),
            "--cache",
            str(tmp_path / "cache"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "hand_widow" in captured.err
    assert "hand_window" in captured.err  # the valid names are listed
    assert "Traceback" not in captured.err
    assert captured.out == ""  # nothing scored before the typo was found


def test_a_value_the_dataclass_refuses_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dev_set(tmp_path)

    code = main(["--cost", "hand_window=0", "--data-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.count("\n") == 1  # one line
    assert "hand_window must be at least 1" in captured.err
    assert "Traceback" not in captured.err


def test_transcription_without_full_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dev_set(tmp_path)

    code = main(["--transcription", "onset_threshold=0.4", "--data-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.count("\n") == 1
    assert "--transcription needs --full" in captured.err


def test_missing_annotations_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-dir", str(tmp_path)]) == 1
    assert "make eval-data" in capsys.readouterr().err


class _CountingTranscriber:
    def __init__(self, events: list[NoteEvent]) -> None:
        self.events = events
        self.calls = 0

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        self.calls += 1
        return list(self.events)


def test_the_cache_transcribes_each_file_once(tmp_path: Path) -> None:
    inner = _CountingTranscriber([NoteEvent(0.1, 0.25, 40, 0.75)])
    cached = CachedTranscriptions(inner, tmp_path / "cache")
    audio = tmp_path / "somewhere" / "00_a_comp_mic.wav"

    first = cached.transcribe(audio)
    second = cached.transcribe(audio)

    assert inner.calls == 1
    assert first == second == [NoteEvent(0.1, 0.25, 40, 0.75)]
    assert isinstance(second[0].midi, int)

    # The entry is on disk, keyed by the audio's stem, so a new run reuses it.
    [entry] = (tmp_path / "cache").iterdir()
    assert entry.name == "00_a_comp_mic.json"
    again = CachedTranscriptions(inner, tmp_path / "cache")
    assert again.transcribe(audio) == first
    assert inner.calls == 1

    cached.transcribe(tmp_path / "01_b_solo_mic.wav")
    assert inner.calls == 2


def test_the_cache_keeps_an_empty_transcription(tmp_path: Path) -> None:
    inner = _CountingTranscriber([])
    cached = CachedTranscriptions(inner, tmp_path / "cache")
    cached.transcribe(tmp_path / "x_mic.wav")
    assert cached.transcribe(tmp_path / "x_mic.wav") == []
    assert inner.calls == 1


def test_settings_key_is_stable_and_distinguishes() -> None:
    key = settings_key(TranscriptionSettings())
    assert key == settings_key(TranscriptionSettings())
    assert len(key) == 12
    assert int(key, 16) >= 0
    assert key != settings_key(TranscriptionSettings(onset_threshold=0.4))
    assert key != settings_key(TranscriptionSettings(melodia_trick=False))


def test_settings_key_covers_every_field() -> None:
    base = TranscriptionSettings()
    key = settings_key(base)
    for field in dataclasses.fields(base):
        value = getattr(base, field.name)
        changed: Any
        if isinstance(value, bool):
            changed = not value
        elif value is None:
            changed = 0.5
        else:
            changed = value / 2
        variant = dataclasses.replace(base, **{field.name: changed})
        assert settings_key(variant) != key, field.name


def test_main_prints_defaults_first_then_each_combination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dev_set(tmp_path)

    code = main(
        [
            "--cost",
            "gap_weight=0,0.6",
            "--data-dir",
            str(tmp_path),
            "--cache",
            str(tmp_path / "cache"),
        ]
    )

    assert code == 0
    header, defaults, zero, sixth = _rows(capsys)
    assert "\t".join(header) == OVERLAP_HEADER
    assert defaults[0] == "defaults"
    assert zero[0] == "gap_weight=0"
    assert sixth[0] == "gap_weight=0.6"
    # E2 open and A2 open are each right: one decimal, a percentage, no sign.
    assert defaults[1:] == ["100.0", "100.0", "0.0"]
    assert all(len(row) == 4 for row in (defaults, zero, sixth))


def test_oracle_mode_scores_the_dev_split_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A player-05 excerpt the mapper gets wrong would drag the rate if it
    # were counted. The sweep tunes on dev and never looks at test.
    _dev_set(tmp_path)
    write_jams(
        tmp_path / "annotation",
        "05_d_comp",
        notes=[(0.0, 0.5, 45.0, 0)],  # A2 on the low string: the mapper opts for open
    )

    assert main(["--data-dir", str(tmp_path), "--cache", str(tmp_path / "c")]) == 0

    [_, defaults] = _rows(capsys)
    assert defaults[1:3] == ["100.0", "100.0"]


def test_main_full_adds_the_transcription_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("mir_eval")
    import guitarvis_worker.stages.transcription as transcription

    _dev_set(tmp_path)
    echo = EchoTranscriber(HEARD)
    built: list[TranscriptionSettings] = []

    def transcriber(settings: TranscriptionSettings) -> EchoTranscriber:
        built.append(settings)
        return echo

    monkeypatch.setattr(transcription, "BasicPitchTranscriber", transcriber)
    cache = tmp_path / "cache"

    code = main(
        [
            "--full",
            "--cost",
            "gap_weight=0,0.6",
            "--transcription",
            "onset_threshold=0.4",
            "--data-dir",
            str(tmp_path),
            "--cache",
            str(cache),
        ]
    )

    assert code == 0
    header, defaults, zero, sixth = _rows(capsys)
    assert "\t".join(header) == FULL_HEADER
    assert defaults[0] == "defaults"
    assert zero[0] == "gap_weight=0,onset_threshold=0.4"
    assert sixth[0] == "gap_weight=0.6,onset_threshold=0.4"
    # Perfect transcription of the same two notes in both styles. Percentages
    # have one decimal; F1, precision and the mean of the two have three.
    assert defaults[1:] == [
        "100.0",
        "100.0",
        "0.0",  # oracle
        "100.0",
        "100.0",  # full string accuracy
        "1.000",
        "1.000",  # f1
        "1.000",
        "1.000",  # precision
        "0.0",  # full overlaps
        "100.0",  # obj4
        "1.000",  # obj2
    ]
    # Two settings were built and each file was transcribed once under each,
    # however many cost combinations scored it. Test-split audio is not touched.
    assert built == [
        TranscriptionSettings(),
        TranscriptionSettings(onset_threshold=0.4),
    ]
    assert len(echo.seen) == 4
    assert {path.stem for path in echo.seen} == {"00_a_comp_mic", "01_b_solo_mic"}
    assert sorted(path.name for path in cache.iterdir()) == sorted(
        [
            settings_key(TranscriptionSettings()),
            settings_key(TranscriptionSettings(onset_threshold=0.4)),
        ]
    )


def test_main_full_reports_missing_audio_before_transcribing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("mir_eval")
    import guitarvis_worker.stages.transcription as transcription

    echo = EchoTranscriber(HEARD)
    monkeypatch.setattr(transcription, "BasicPitchTranscriber", lambda settings: echo)
    write_jams(tmp_path / "annotation", "00_a_comp", notes=NOTES)

    assert main(["--full", "--data-dir", str(tmp_path)]) == 1
    assert "00_a_comp_mic.wav" in capsys.readouterr().err
    assert echo.seen == []


def test_main_full_without_the_ml_stack_says_what_to_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("mir_eval")
    import guitarvis_worker.stages.transcription as transcription

    class NoBasicPitch:
        def transcribe(self, stem_path: Path) -> list[NoteEvent]:
            raise ImportError("No module named 'basic_pitch'")

    monkeypatch.setattr(
        transcription, "BasicPitchTranscriber", lambda settings: NoBasicPitch()
    )
    _dev_set(tmp_path)

    code = main(["--full", "--data-dir", str(tmp_path), "--cache", str(tmp_path / "c")])

    captured = capsys.readouterr()
    assert code == 1
    assert "uv sync --extra eval-full" in captured.err
    assert "Traceback" not in captured.err


def test_main_never_writes_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("mir_eval")
    import guitarvis_worker.stages.transcription as transcription

    def refuse(**_: object) -> Path:
        raise AssertionError("the sweep wrote a results file")

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(results, "RESULTS_DIR", out)
    monkeypatch.setattr(results, "write_results", refuse)
    monkeypatch.setattr(
        transcription,
        "BasicPitchTranscriber",
        lambda settings: EchoTranscriber(HEARD),
    )
    _dev_set(tmp_path / "data")
    cache = tmp_path / "cache"
    before = set(tmp_path.rglob("*"))

    assert main(["--data-dir", str(tmp_path / "data"), "--cache", str(cache)]) == 0
    assert (
        main(["--full", "--data-dir", str(tmp_path / "data"), "--cache", str(cache)])
        == 0
    )

    assert list(out.iterdir()) == []
    created = set(tmp_path.rglob("*")) - before
    assert created, "the full run should have cached its transcriptions"
    assert all(cache == path or cache in path.parents for path in created)
