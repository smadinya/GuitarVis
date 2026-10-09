"""Scores one excerpt at a time and adds the scores up.

Stages arrive by injection, as they do in the worker's pipeline, so every
path through here is testable with stubs and no audio.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from guitarvis_core.contracts import (
    FretboardMapper,
    NoteEvent,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_core.tabdoc import STANDARD_TUNING

from guitarvis_eval.calibration import BANDS, ConfidenceBands, confidence_bands
from guitarvis_eval.dataset import Excerpt
from guitarvis_eval.metrics import (
    NoteCounts,
    Tally,
    chord_tally,
    match_notes,
    oracle_string_tally,
)


@dataclass(frozen=True)
class ExcerptScore:
    name: str
    style: str
    strings: Tally  # the mapper's string accuracy
    baseline_strings: Tally | None = None  # oracle mode only
    notes: NoteCounts | None = None  # full mode only
    chords: Tally | None = None  # full mode only
    confidence: ConfidenceBands | None = None  # full mode only


def score_oracle(
    excerpt: Excerpt, mapper: FretboardMapper, baseline: FretboardMapper
) -> ExcerptScore:
    """Ground-truth pitches in, so string accuracy measures stage 4 alone."""
    events = [
        NoteEvent(onset=n.onset, duration=n.duration, midi=n.midi, confidence=1.0)
        for n in excerpt.notes
    ]
    return ExcerptScore(
        name=excerpt.name,
        style=excerpt.style,
        strings=oracle_string_tally(
            excerpt.notes, mapper.assign(events, STANDARD_TUNING).notes
        ),
        baseline_strings=oracle_string_tally(
            excerpt.notes, baseline.assign(events, STANDARD_TUNING).notes
        ),
    )


def score_full(
    excerpt: Excerpt,
    audio: Path,
    *,
    transcriber: Transcriber,
    analyzer: StructureAnalyzer,
    mapper: FretboardMapper,
) -> ExcerptScore:
    """Audio in. Separation is skipped — GuitarSet is already solo guitar —
    so the recording is passed as both stem and mix.

    Note F1 scores the transcriber's own output, before the mapper drops
    anything, so it moves only when transcription does. String accuracy
    scores the notes the mapper placed, over those matching the truth.
    The confidence bands tally the transcriber's notes too, for the same
    reason: they calibrate what the transcriber's confidence means.
    """
    events = transcriber.transcribe(audio)
    heard = match_notes(excerpt.notes, events)
    placed = mapper.assign(events, STANDARD_TUNING).notes
    pairs = match_notes(excerpt.notes, placed)
    structure = analyzer.analyze(audio, audio)
    return ExcerptScore(
        name=excerpt.name,
        style=excerpt.style,
        strings=Tally(
            correct=sum(excerpt.notes[t].string == placed[e].string for t, e in pairs),
            total=len(pairs),
        ),
        notes=NoteCounts(
            matched=len(heard), truth=len(excerpt.notes), estimated=len(events)
        ),
        chords=chord_tally(excerpt.chords, structure.chords, excerpt.duration),
        confidence=confidence_bands(events, {e for _, e in heard}),
    )


def summarize(scores: Sequence[ExcerptScore]) -> dict[str, object]:
    """Totals overall ("all") and per style ("comp", "solo"). Counts are
    summed before dividing, so long excerpts weigh more than short ones.
    Confidence bands appear here only: per excerpt, they are mostly empty."""
    groups: dict[str, list[ExcerptScore]] = {"all": list(scores)}
    for score in scores:
        groups.setdefault(score.style, []).append(score)
    return {
        group: _total(members, with_bands=True)
        for group, members in sorted(groups.items())
    }


def score_to_dict(score: ExcerptScore) -> dict[str, object]:
    return {"name": score.name, "style": score.style, **_total([score])}


def _total(
    scores: Sequence[ExcerptScore], *, with_bands: bool = False
) -> dict[str, object]:
    out: dict[str, object] = {
        "excerpts": len(scores),
        "string": _tally(sum((s.strings for s in scores), Tally())),
    }
    baselines = [s.baseline_strings for s in scores if s.baseline_strings is not None]
    if baselines:
        out["baseline_string"] = _tally(sum(baselines, Tally()))
    counts = [s.notes for s in scores if s.notes is not None]
    if counts:
        notes = sum(counts, NoteCounts())
        out["note"] = {
            "matched": notes.matched,
            "truth": notes.truth,
            "estimated": notes.estimated,
            "precision": notes.precision,
            "recall": notes.recall,
            "f1": notes.f1,
        }
    chords = [s.chords for s in scores if s.chords is not None]
    if chords:
        out["chord"] = _tally(sum(chords, Tally()))
    bands = [s.confidence for s in scores if s.confidence is not None]
    if with_bands and bands:
        out["precision_by_confidence"] = _bands(sum(bands, ConfidenceBands()))
    return out


def _bands(bands: ConfidenceBands) -> dict[str, object]:
    """Keyed by each band's lower edge: "0.3" holds [0.3, 0.4)."""
    return {
        f"{band / BANDS:.1f}": {
            "estimated": bands.estimated[band],
            "matched": bands.matched[band],
            "precision": bands.precision(band),
        }
        for band in range(BANDS)
    }


def _tally(tally: Tally) -> dict[str, object]:
    return {"correct": tally.correct, "total": tally.total, "rate": tally.rate}
