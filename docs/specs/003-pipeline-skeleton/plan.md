# Pipeline Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement stages 1–3, the orchestrator, and the CLI, so that a real song produces a valid tab document with a beat grid and a chord track.

**Architecture:** Fill the typed stage stubs left by 002, in place, against the protocols already in `guitarvis_core.contracts`. The orchestrator owns the degradation ladder; stages stay ignorant of each other.

**Tech Stack:** Python 3.12, uv workspace, Demucs `htdemucs_6s`, basic-pitch via ONNX Runtime, librosa, pydantic v2.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **ADR:** [0006](../../decisions/0006-onnx-transcription-backend.md)

## Global Constraints

Repo-wide rules from `CLAUDE.md` and `docs/CONVENTIONS.md`. Every task inherits them.

- **Never commit to `main`.** All work happens on branch `003-pipeline-skeleton`. `.githooks/pre-commit` enforces it.
- **`make check` is the gate.** Run it before claiming any task is done; it runs ruff, mypy, pytest, ESLint, `tsc`, and `make schema-check`.
- **`pitch_of(string, fret, tuning) == note.midi`**, for every note, always. Use `guitarvis_core.fretboard.check_invariant`.
- **Seconds are authoritative.** Never store a note position as bar/beat.
- **`apps/api` must not import** torch, demucs, basic_pitch, librosa, or numpy. This task does not touch api, but `apps/api/tests/test_boundaries.py` enforces it.
- **Stage modules must not import** torch, demucs, basic_pitch, librosa, or **numpy** at module level — heavy imports go inside the method that uses them. `apps/worker/tests/test_stages.py` scans `tree.body` for this; numpy is in `FORBIDDEN_ROOTS`, which is easy to trip in `structure.py`.
- **`guitarvis_core` stays Pydantic and stdlib only.** No numpy, no ML.
- **After changing `tabdoc.py`, run `make schema`** and commit both generated artifacts (`schema/tab-document.schema.json`, `web/src/types/tabDocument.ts`).
- **Evaluation never gates CI.** Not touched in this phase.
- ML dependencies are opt-in: `uv sync --extra ml`.

---

### Task 1: Dependency wiring for the ONNX transcription backend

Proves [ADR 0006](../../decisions/0006-onnx-transcription-backend.md) resolves and runs before any stage code depends on it. If the override mechanism fails, this is the task that says so, and the fallback (vendoring `nmp.onnx`) is a change to this task alone.

**Files:**
- Modify: `pyproject.toml` (workspace root — `[tool.uv]` overrides)
- Modify: `apps/worker/pyproject.toml` (ml extra, and the comment that says stage 2 is undecided)
- Modify: `uv.lock` (regenerated)

**Interfaces:**
- Consumes: nothing.
- Produces: an `ml` extra that installs `basic-pitch` and `onnxruntime` with no TensorFlow in the resolved graph.

- [x] **Step 1: Add the dependency overrides to the workspace root**

uv resolves overrides only from the workspace root. Add to `pyproject.toml`, inside the existing `[tool.uv]` table:

```toml
[tool.uv]
package = false
# ADR 0006. basic-pitch pins tensorflow<2.15.1 unconditionally on Linux at
# Python >= 3.11, and no cp312 wheel of that tensorflow exists. We run its
# bundled ONNX model through onnxruntime instead, so the requirement is
# overridden away with a marker that never matches. The resampy override is a
# second, independent 3.12 break: basic-pitch pins resampy<0.4.3, and those
# versions import pkg_resources, which setuptools >= 81 no longer ships.
override-dependencies = [
    "tensorflow; sys_platform == 'never'",
    "tensorflow-macos; sys_platform == 'never'",
    "resampy>=0.4.3",
]
```

- [x] **Step 2: Add the real dependencies to the worker's ml extra**

In `apps/worker/pyproject.toml`, replace the long "basic-pitch is deliberately absent" comment with the resolved decision, and extend the extra:

```toml
# Heavy ML dependencies are opt-in so that `uv sync` and CI stay light.
# Install with `uv sync --extra ml`.
#
# basic-pitch runs through ONNX Runtime here, not TensorFlow: see ADR 0006 and
# the override-dependencies block in the workspace root pyproject.toml. Removing
# either override puts an uninstallable tensorflow back in the graph.
[project.optional-dependencies]
ml = [
    "torch>=2.4",
    "demucs>=4.0",
    "librosa>=0.10",
    "basic-pitch>=0.4.0",
    "onnxruntime>=1.17",
]
```

- [x] **Step 3: Resolve and install**

```bash
uv sync --extra ml
```

Expected: resolution succeeds and no TensorFlow appears. Verify:

```bash
uv pip list | grep -iE 'tensorflow|onnxruntime|resampy|basic'
```

Expected: `basic-pitch`, `onnxruntime`, and `resampy 0.4.3` or newer present; **no tensorflow line at all**.

If resolution fails because uv will not drop a requirement via override, stop and switch to the fallback in the spec: vendor `nmp.onnx` from the wheel into `apps/worker/src/guitarvis_worker/models/` and drop the `basic-pitch` dependency. Record the change in ADR 0006 before continuing.

- [x] **Step 4: Verify the model actually loads and transcribes**

This is the step that validates the whole approach. It reproduces the spike.

```bash
uv run --extra ml python -c "
import numpy as np, soundfile as sf, basic_pitch
from basic_pitch.inference import predict
print('model:', basic_pitch.ICASSP_2022_MODEL_PATH)
sr = 22050
t = np.linspace(0, 2.0, int(sr*2.0), endpoint=False)
sf.write('/tmp/gv_probe.wav', 0.4*np.sin(2*np.pi*440*t) + 0.4*np.sin(2*np.pi*554.37*t), sr)
_, _, events = predict('/tmp/gv_probe.wav', basic_pitch.ICASSP_2022_MODEL_PATH)
print('events:', len(events), 'pitches:', sorted({int(e[2]) for e in events}))
"
```

Expected: the model path ends in `nmp.onnx`, and the detected pitches are `[69, 73]`. Warnings about coremltools, tflite-runtime, and Tensorflow not being installed are normal and expected — that is basic-pitch reporting which backends are absent.

- [x] **Step 5: Confirm the light install still works**

The ml extra must stay optional, or CI breaks.

```bash
uv sync
make check
```

Expected: `make check` passes with no ML dependencies installed.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml apps/worker/pyproject.toml uv.lock
git commit -m "build: install basic-pitch via ONNX Runtime, overriding tensorflow out"
```

---

### Task 2: Core contract additions

Three additions the rest of the phase needs, landed together because they share one `make schema` regeneration. Nothing here imports ML.

**Files:**
- Modify: `packages/core/src/guitarvis_core/contracts.py`
- Modify: `packages/core/src/guitarvis_core/tabdoc.py`
- Modify: `packages/core/tests/test_contracts.py`
- Modify: `packages/core/tests/test_tabdoc.py`
- Modify: `apps/worker/src/guitarvis_worker/stages/separation.py` (signature only)
- Modify: `apps/worker/tests/test_stages.py` (signature only)
- Regenerate: `schema/tab-document.schema.json`, `web/src/types/tabDocument.ts`

**Interfaces:**
- Consumes: existing `guitarvis_core.contracts` and `tabdoc` models.
- Produces: `IngestedAudio(path: Path, title: str, duration_sec: float)`; `AudioSource` protocol with `fetch() -> IngestedAudio`; `SeparationResult(stem_path: Path, warnings: list[str])`; `Separator.isolate(audio_path: Path) -> SeparationResult`; `TabDocument.warnings: list[str]`.

- [x] **Step 1: Write the failing tests**

Append to `packages/core/tests/test_contracts.py`:

```python
def test_ingested_audio_is_frozen() -> None:
    audio = IngestedAudio(path=Path("song.wav"), title="song", duration_sec=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        audio.title = "other"  # type: ignore[misc]


def test_upload_shaped_object_satisfies_audio_source() -> None:
    class Stub:
        def fetch(self) -> IngestedAudio:
            return IngestedAudio(path=Path("a.wav"), title="a", duration_sec=1.0)

    assert isinstance(Stub(), AudioSource)


def test_separation_result_defaults_to_no_warnings() -> None:
    result = SeparationResult(stem_path=Path("guitar.wav"))
    assert result.warnings == []


def test_separator_protocol_returns_separation_result() -> None:
    class Stub:
        def isolate(self, audio_path: Path) -> SeparationResult:
            return SeparationResult(stem_path=audio_path)

    assert isinstance(Stub(), Separator)
```

Add the imports that file needs: `dataclasses`, `pytest`, `Path`, and `AudioSource`, `IngestedAudio`, `SeparationResult`, `Separator` from `guitarvis_core.contracts`.

Append to `packages/core/tests/test_tabdoc.py`, adding whatever of `TabDocument`, `Source`, `Instrument`, and `Timing` it does not already import:

```python
def test_document_defaults_to_no_warnings() -> None:
    doc = TabDocument(
        source=Source(title="t", duration_sec=1.0, audio_url="file:///t.wav"),
        instrument=Instrument(),
        timing=Timing(),
    )
    assert doc.warnings == []


def test_warnings_round_trip() -> None:
    doc = TabDocument(
        source=Source(title="t", duration_sec=1.0, audio_url="file:///t.wav"),
        instrument=Instrument(),
        timing=Timing(),
        warnings=["used the 4-stem fallback"],
    )
    assert TabDocument.model_validate_json(doc.model_dump_json()).warnings == [
        "used the 4-stem fallback"
    ]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/core -q`
Expected: FAIL — `ImportError: cannot import name 'IngestedAudio'`.

- [x] **Step 3: Add the ingestion and separation contracts**

In `packages/core/src/guitarvis_core/contracts.py`, add above the stage protocols:

```python
@dataclass(frozen=True)
class IngestedAudio:
    """What every way of getting audio into the system produces.

    URL fetching is another implementation of AudioSource and changes nothing
    downstream — the isolation the design spec asks for, expressed as a type.
    """

    path: Path
    title: str
    duration_sec: float


@dataclass(frozen=True)
class SeparationResult:
    """Stage 1 output. `warnings` carries degradation the client must show.

    A bare Path cannot say "this came from the 4-stem fallback and may contain
    other instruments", and putting that on the separator instance would make a
    stateless stage stateful.
    """

    stem_path: Path
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class AudioSource(Protocol):
    """Ingestion: produce a local audio file and its metadata."""

    def fetch(self) -> IngestedAudio: ...
```

Import `field` from `dataclasses`. Then change the `Separator` protocol:

```python
@runtime_checkable
class Separator(Protocol):
    """Stage 1: isolate the guitar from a mix."""

    def isolate(self, audio_path: Path) -> SeparationResult: ...
```

- [x] **Step 4: Add the document's warnings field**

In `packages/core/src/guitarvis_core/tabdoc.py`, add to `TabDocument` after `sections`:

```python
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Quality degradation the client must surface. A tab the user cannot "
            "tell is degraded is worse than one labelled as such."
        ),
    )
```

- [x] **Step 5: Update the separation stub's signature**

In `apps/worker/src/guitarvis_worker/stages/separation.py`, change the return type to `SeparationResult`, importing it from `guitarvis_core.contracts`. The body still raises `NotImplementedError` — Task 4 fills it. Update the matching assertion in `apps/worker/tests/test_stages.py` if it names the return type.

- [x] **Step 6: Regenerate the schema and web types**

```bash
make schema
git diff --stat schema/ web/src/types/
```

Expected: both files change, adding only the `warnings` property.

- [x] **Step 7: Run the full gate**

Run: `make check`
Expected: all pass, including `make schema-check`.

- [x] **Step 8: Commit**

```bash
git add packages/core apps/worker schema web/src/types
git commit -m "feat(core): add ingestion contracts, SeparationResult, and document warnings"
```

---

### Task 3: File ingestion

The front door: validate and probe before any expensive work starts. Uses `ffprobe` rather than a Python audio library because it decodes every container a user might supply and fails fast on files that are not audio.

**Files:**
- Create: `apps/worker/src/guitarvis_worker/ingest.py`
- Create: `apps/worker/tests/test_ingest.py`

**Interfaces:**
- Consumes: `IngestedAudio`, `AudioSource`, `FailureReason`, `PipelineError`.
- Produces: `MAX_DURATION_SEC = 600.0`; `probe_duration(path: Path) -> float`; `UploadSource(path, *, max_duration_sec=MAX_DURATION_SEC)` implementing `AudioSource`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_ingest.py`:

```python
"""Ingestion guards. Cheap checks before the expensive stages run."""

import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import AudioSource, FailureReason, PipelineError
from guitarvis_worker.ingest import UploadSource, probe_duration


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A silent wav, written with the stdlib so tests need no ml extra."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def test_upload_source_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(UploadSource(write_wav(tmp_path / "a.wav")), AudioSource)


def test_probe_duration_reads_length(tmp_path: Path) -> None:
    assert probe_duration(write_wav(tmp_path / "a.wav", seconds=2.0)) == pytest.approx(
        2.0, abs=0.05
    )


def test_fetch_returns_path_title_and_duration(tmp_path: Path) -> None:
    ingested = UploadSource(write_wav(tmp_path / "my song.wav", seconds=1.5)).fetch()
    assert ingested.title == "my song"
    assert ingested.duration_sec == pytest.approx(1.5, abs=0.05)


def test_missing_file_is_unsupported_format(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(tmp_path / "nope.wav").fetch()
    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


def test_undecodable_file_is_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.wav"
    path.write_bytes(b"this is not audio")
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(path).fetch()
    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


def test_overlong_input_is_too_long(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(
            write_wav(tmp_path / "a.wav", seconds=2.0), max_duration_sec=1.0
        ).fetch()
    assert excinfo.value.reason is FailureReason.TOO_LONG


def test_too_long_message_tells_the_user_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="single song"):
        UploadSource(
            write_wav(tmp_path / "a.wav", seconds=2.0), max_duration_sec=1.0
        ).fetch()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_worker.ingest'`

- [x] **Step 3: Write the implementation**

`apps/worker/src/guitarvis_worker/ingest.py`:

```python
"""Getting audio into the pipeline.

UploadSource is one implementation of AudioSource; URL fetching will be
another, and nothing downstream will change when it lands. Guards run here, at
the front door, because rejecting a three-hour DJ set after separation has
already run is the expensive way to find out.
"""

import json
import subprocess
from pathlib import Path

from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    PipelineError,
)

MAX_DURATION_SEC = 600.0  # ten minutes


def probe_duration(path: Path) -> float:
    """Read a file's duration with ffprobe.

    ffprobe rather than a Python audio library: it decodes every container a
    user might supply, and it is the same check for "is this audio at all".
    """
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            FailureReason.INTERNAL,
            "ffprobe is not installed. Install ffmpeg to process audio.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT,
            "That file could not be read as audio. Try an mp3, wav, or m4a file.",
        ) from exc

    try:
        return float(json.loads(completed.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT,
            "That file could not be read as audio. Try an mp3, wav, or m4a file.",
        ) from exc


class UploadSource:
    """Implements guitarvis_core.contracts.AudioSource for a local file."""

    def __init__(
        self, path: Path | str, *, max_duration_sec: float = MAX_DURATION_SEC
    ) -> None:
        self.path = Path(path)
        self.max_duration_sec = max_duration_sec

    def fetch(self) -> IngestedAudio:
        if not self.path.is_file():
            raise PipelineError(
                FailureReason.UNSUPPORTED_FORMAT, f"No such audio file: {self.path}"
            )

        duration = probe_duration(self.path)
        if duration > self.max_duration_sec:
            raise PipelineError(
                FailureReason.TOO_LONG,
                f"That recording is longer than {self.max_duration_sec / 60:.0f} "
                "minutes. Try a single song rather than a full set.",
            )

        return IngestedAudio(
            path=self.path, title=self.path.stem, duration_sec=duration
        )
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest apps/worker/tests/test_ingest.py -q`
Expected: all pass. These need ffmpeg but no ML extra.

- [x] **Step 5: Run the full gate**

Run: `make check`
Expected: pass.

- [x] **Step 6: Commit**

```bash
git add apps/worker/src/guitarvis_worker/ingest.py apps/worker/tests/test_ingest.py
git commit -m "feat(worker): add file ingestion with duration and format guards"
```

---

### Task 4: Stage 1 — separation

Implements the first rung of the degradation ladder: a silent guitar stem falls back to the 4-stem `other` track, and only two silent stems fail the job. The Demucs subprocess call is isolated in one overridable method so the ladder is testable in CI without the ml extra.

`measure_rms` deliberately uses the stdlib `wave` module rather than numpy: numpy is in `FORBIDDEN_ROOTS` for stage modules, and keeping this function dependency-free is what lets the fallback tests run in CI.

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/separation.py`
- Create: `apps/worker/tests/test_separation.py`
- Modify: `apps/worker/tests/test_stages.py` (drop the stage-1 NotImplementedError assertion)

**Interfaces:**
- Consumes: `SeparationResult`, `PipelineError`, `FailureReason`.
- Produces: `SILENCE_RMS = 1e-3`; `measure_rms(path: Path) -> float`; `DemucsSeparator(model="htdemucs_6s", fallback_model="htdemucs", device=None)` implementing `Separator`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_separation.py`:

```python
"""Stage 1 and the first rung of the degradation ladder.

The Demucs call is stubbed out: what is under test is the fallback decision,
which must hold whether or not the ml extra is installed.
"""

import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_worker.stages.separation import (
    SILENCE_RMS,
    DemucsSeparator,
    measure_rms,
)


def write_wav(path: Path, amplitude: int = 8000, rate: int = 8000) -> Path:
    """One second of a square-ish tone at the given amplitude, or silence at 0."""
    frames = bytearray()
    for index in range(rate):
        value = amplitude if (index // 20) % 2 == 0 else -amplitude
        frames += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


class FakeSeparator(DemucsSeparator):
    """Replaces the Demucs subprocess with prepared files."""

    def __init__(self, stems: dict[str, Path]) -> None:
        super().__init__()
        self.stems = stems
        self.calls: list[tuple[str, str]] = []

    def _demucs(self, model: str, audio_path: Path, stem_name: str) -> Path:
        self.calls.append((model, stem_name))
        return self.stems[model]


def test_measure_rms_separates_signal_from_silence(tmp_path: Path) -> None:
    assert measure_rms(write_wav(tmp_path / "loud.wav", amplitude=8000)) > SILENCE_RMS
    assert measure_rms(write_wav(tmp_path / "quiet.wav", amplitude=0)) < SILENCE_RMS


def test_audible_guitar_stem_is_used_directly(tmp_path: Path) -> None:
    guitar = write_wav(tmp_path / "guitar.wav", amplitude=8000)
    separator = FakeSeparator({"htdemucs_6s": guitar})

    result = separator.isolate(tmp_path / "song.wav")

    assert result.stem_path == guitar
    assert result.warnings == []
    assert separator.calls == [("htdemucs_6s", "guitar")]


def test_silent_guitar_stem_falls_back_to_the_other_track(tmp_path: Path) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "guitar.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "other.wav", amplitude=8000),
        }
    )

    result = separator.isolate(tmp_path / "song.wav")

    assert result.stem_path.name == "other.wav"
    assert result.warnings and "other" in result.warnings[0]
    assert separator.calls == [("htdemucs_6s", "guitar"), ("htdemucs", "other")]


def test_two_silent_stems_fail_honestly(tmp_path: Path) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "a.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "b.wav", amplitude=0),
        }
    )

    with pytest.raises(PipelineError) as excinfo:
        separator.isolate(tmp_path / "song.wav")

    assert excinfo.value.reason is FailureReason.NO_GUITAR_DETECTED
    assert "guitar" in str(excinfo.value).lower()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_separation.py -q`
Expected: FAIL — `ImportError: cannot import name 'measure_rms'`

- [x] **Step 3: Write the implementation**

Replace the body of `apps/worker/src/guitarvis_worker/stages/separation.py`, keeping its existing module docstring and adding to it:

```python
import array
import subprocess
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FailureReason, PipelineError, SeparationResult

SILENCE_RMS = 1e-3  # below this, a stem is empty rather than quiet

_RMS_STRIDE = 97  # sample every Nth frame; silence detection needs no more


def measure_rms(path: Path) -> float:
    """Root-mean-square amplitude of a 16-bit PCM wav, normalised to 0..1.

    Stdlib only, on purpose: numpy is forbidden at module level in stage
    modules, and keeping this free of the ml extra is what lets the fallback
    tests run in CI.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {handle.getsampwidth()} bytes")
        frames = handle.readframes(handle.getnframes())

    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        return 0.0

    sampled = samples[::_RMS_STRIDE] if len(samples) >= _RMS_STRIDE else samples
    total = sum(float(value) * float(value) for value in sampled)
    return (total / len(sampled)) ** 0.5 / 32768.0


class DemucsSeparator:
    """Implements guitarvis_core.contracts.Separator."""

    def __init__(
        self,
        model: str = "htdemucs_6s",
        fallback_model: str = "htdemucs",
        device: str | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.device = device

    def isolate(self, audio_path: Path) -> SeparationResult:
        guitar = self._demucs(self.model, audio_path, "guitar")
        if measure_rms(guitar) >= SILENCE_RMS:
            return SeparationResult(stem_path=guitar)

        # A heavily distorted guitar is often attributed elsewhere by the
        # 6-stem model. The 4-stem `other` track is the next best thing, and
        # saying so is better than returning silence.
        other = self._demucs(self.fallback_model, audio_path, "other")
        if measure_rms(other) < SILENCE_RMS:
            raise PipelineError(
                FailureReason.NO_GUITAR_DETECTED,
                "No clear guitar part was found in this recording.",
            )

        return SeparationResult(
            stem_path=other,
            warnings=[
                "The 6-stem model found no guitar, so this tab comes from the "
                "4-stem 'other' track and may include other instruments."
            ],
        )

    def _demucs(self, model: str, audio_path: Path, stem_name: str) -> Path:
        """Run Demucs as a subprocess and return the requested stem.

        A subprocess rather than the Python API: the CLI is stable across
        releases, and a model that dies cannot take the worker down with it.
        """
        out_dir = audio_path.parent / "stems"
        command = [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            model,
            "-o",
            str(out_dir),
            str(audio_path),
        ]
        if self.device:
            command += ["-d", self.device]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise PipelineError(
                FailureReason.INTERNAL,
                "demucs is not installed. Run `uv sync --extra ml`.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation failed: {exc.stderr[-500:]}"
            ) from exc

        stem = out_dir / model / audio_path.stem / f"{stem_name}.wav"
        if not stem.exists():
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation produced no stem at {stem}"
            )
        return stem


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Separator  # only, so this

    _conforms: Separator = DemucsSeparator()  # assignment is what
    # actually checks the signature.
```

- [x] **Step 4: Update the stub test**

In `apps/worker/tests/test_stages.py`, remove the assertion that `DemucsSeparator().isolate(...)` raises `NotImplementedError`. Leave the module-level import scan and the other three stages alone.

- [x] **Step 5: Run the tests**

Run: `uv run pytest apps/worker -q`
Expected: pass.

- [x] **Step 6: Verify against the real model once**

The first run downloads roughly 300MB of weights and is slow on CPU.

```bash
uv run --extra ml python -c "
from pathlib import Path
from guitarvis_worker.stages.separation import DemucsSeparator
result = DemucsSeparator(device='cuda').isolate(Path('/path/to/song.mp3'))
print(result.stem_path, result.warnings)
"
```

Expected: a path to `guitar.wav` that exists. If the directory layout differs, correct the path built in `_demucs`. On the 6GB GTX 1660 Ti, add `--segment 7` to the command if CUDA runs out of memory on a full song.

- [x] **Step 7: Run the full gate and commit**

```bash
make check
git add apps/worker
git commit -m "feat(worker): implement stage 1 separation with silent-stem fallback"
```

---

### Task 5: Stage 2 — transcription

Implements the protocol's single upgrade point. The class keeps its name; only its docstring changes, because [ADR 0006](../../decisions/0006-onnx-transcription-backend.md) confirms basic-pitch as the backend and removes the "provisional" caveat 002 left.

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/transcription.py`
- Create: `apps/worker/tests/test_transcription.py`
- Modify: `apps/worker/tests/test_stages.py` (drop the stage-2 assertion)

**Interfaces:**
- Consumes: `NoteEvent`.
- Produces: `MIN_CONFIDENCE = 0.1`; `BasicPitchTranscriber(min_confidence=MIN_CONFIDENCE)` implementing `Transcriber`, with an overridable `_predict(stem_path) -> Sequence[tuple]`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_transcription.py`:

```python
"""Stage 2's conversion from raw model output to NoteEvent.

_predict is stubbed: what is under test is the clamping, filtering, and
ordering, none of which should require the ml extra to verify.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_worker.stages.transcription import (
    MIN_CONFIDENCE,
    BasicPitchTranscriber,
)


class StubTranscriber(BasicPitchTranscriber):
    def __init__(self, raw: Sequence[tuple], **kwargs: float) -> None:
        super().__init__(**kwargs)
        self.raw = raw

    def _predict(self, stem_path: Path) -> Sequence[tuple]:
        return self.raw


def test_builds_note_events_from_model_tuples() -> None:
    # (start, end, midi, amplitude, pitch_bends) — basic-pitch's shape
    events = StubTranscriber([(1.0, 1.5, 52, 0.8, None)]).transcribe(Path("x.wav"))

    assert len(events) == 1
    assert events[0].onset == 1.0
    assert events[0].duration == pytest.approx(0.5)
    assert events[0].midi == 52
    assert events[0].confidence == pytest.approx(0.8)


def test_confidence_is_clamped_into_range() -> None:
    # Note.confidence is bounded 0..1 by the schema; amplitude is not
    events = StubTranscriber([(1.0, 1.5, 52, 1.4, None)]).transcribe(Path("x.wav"))
    assert events[0].confidence == 1.0


def test_near_noise_is_dropped() -> None:
    events = StubTranscriber([(1.0, 1.5, 52, 0.01, None)]).transcribe(Path("x.wav"))
    assert events == []


def test_pitches_outside_midi_range_are_dropped() -> None:
    events = StubTranscriber([(1.0, 1.5, 200, 0.9, None)]).transcribe(Path("x.wav"))
    assert events == []


def test_events_are_sorted_by_onset() -> None:
    raw = [(2.0, 2.5, 52, 0.8, None), (1.0, 1.5, 55, 0.8, None)]
    events = StubTranscriber(raw).transcribe(Path("x.wav"))
    assert [event.onset for event in events] == [1.0, 2.0]


def test_empty_prediction_is_not_an_error() -> None:
    assert StubTranscriber([]).transcribe(Path("x.wav")) == []


def test_midi_is_a_plain_int() -> None:
    # basic-pitch returns numpy integers; they must not reach the document,
    # where they would serialise as something a strict client may reject.
    events = StubTranscriber([(1.0, 1.5, 52, 0.8, None)]).transcribe(Path("x.wav"))
    assert type(events[0].midi) is int


def test_min_confidence_stays_conservative() -> None:
    # The degradation ladder needs faint notes to survive and render faintly;
    # this floor removes near-noise only.
    assert MIN_CONFIDENCE <= 0.2
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_transcription.py -q`
Expected: FAIL — `ImportError: cannot import name 'MIN_CONFIDENCE'`

- [x] **Step 3: Write the implementation**

Replace the module docstring of `apps/worker/src/guitarvis_worker/stages/transcription.py` — the "provisional name" caveat is now resolved:

```python
"""Stage 2 — transcription. basic-pitch, run through ONNX Runtime.

Polyphonic, CPU-runnable, and it emits per-note activation strength that maps
to the confidence field the degradation ladder depends on. It runs through
onnxruntime rather than TensorFlow, which cannot install on Python 3.12: see
ADR 0006 and the override-dependencies block in the root pyproject.toml.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import NoteEvent

MIN_CONFIDENCE = 0.1  # near-noise only; faint notes must survive to render faintly

_MIDI_MIN = 0
_MIDI_MAX = 127


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber."""

    def __init__(self, min_confidence: float = MIN_CONFIDENCE) -> None:
        self.min_confidence = min_confidence

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        events = []
        for start, end, midi, amplitude, *_ in self._predict(stem_path):
            confidence = min(1.0, max(0.0, float(amplitude)))
            pitch = int(midi)
            if confidence < self.min_confidence:
                continue
            if not _MIDI_MIN <= pitch <= _MIDI_MAX:
                continue
            events.append(
                NoteEvent(
                    onset=float(start),
                    duration=float(end) - float(start),
                    midi=pitch,
                    confidence=confidence,
                )
            )

        events.sort(key=lambda event: (event.onset, event.midi))
        return events

    def _predict(self, stem_path: Path) -> Sequence[tuple]:
        """Raw model output. Imported lazily so the module needs no ml extra.

        ICASSP_2022_MODEL_PATH resolves to the bundled nmp.onnx when
        onnxruntime is the only installed backend, which is how this repo
        installs it.
        """
        import basic_pitch
        from basic_pitch.inference import predict

        _, _, note_events = predict(str(stem_path), basic_pitch.ICASSP_2022_MODEL_PATH)
        return note_events


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Transcriber  # only, so this

    _conforms: Transcriber = BasicPitchTranscriber()  # assignment is what
    # actually checks the signature.
```

- [x] **Step 4: Update the stub test**

Remove the stage-2 `NotImplementedError` assertion from `apps/worker/tests/test_stages.py`.

- [x] **Step 5: Run the tests**

Run: `uv run pytest apps/worker -q`
Expected: pass.

- [x] **Step 6: Verify against the real model**

```bash
uv run --extra ml python -c "
import wave, math
from pathlib import Path
from guitarvis_worker.stages.transcription import BasicPitchTranscriber
rate = 22050
with wave.open('/tmp/gv_a440.wav', 'wb') as h:
    h.setnchannels(1); h.setsampwidth(2); h.setframerate(rate)
    h.writeframes(b''.join(
        int(12000 * math.sin(2*math.pi*440*i/rate)).to_bytes(2, 'little', signed=True)
        for i in range(rate * 2)))
events = BasicPitchTranscriber().transcribe(Path('/tmp/gv_a440.wav'))
print(len(events), 'events; pitches:', sorted({e.midi for e in events}))
"
```

Expected: at least one event, including MIDI 69 (A4).

- [x] **Step 7: Run the full gate and commit**

```bash
make check
git add apps/worker
git commit -m "feat(worker): implement stage 2 transcription via basic-pitch ONNX"
```

---

### Task 6: Stage 3 — musical structure

Beats and chords. The numbering, template, and merging logic are pure Python — no numpy — so the parts most likely to be wrong are the parts CI can check. Only the chroma extraction needs librosa.

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/structure.py`
- Create: `apps/worker/tests/test_structure.py`
- Modify: `apps/worker/tests/test_stages.py` (drop the stage-3 assertion)

**Interfaces:**
- Consumes: `StructureResult`, and `Beat`, `Chord`, `Timing` from `guitarvis_core.tabdoc`.
- Produces: `MIN_CHORD_CONFIDENCE = 0.5`; `chord_templates() -> list[tuple[str, tuple[float, ...]]]`; `beats_to_events(beat_times, beats_per_bar=4) -> list[Beat]`; `merge_chords(symbols, times, confidences, end_time) -> list[Chord]`; `LibrosaStructureAnalyzer(beats_per_bar=4, min_chord_confidence=MIN_CHORD_CONFIDENCE)` implementing `StructureAnalyzer`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_structure.py`:

```python
"""Stage 3's pure logic: bar numbering, chord templates, and run merging."""

import math

from guitarvis_worker.stages.structure import (
    MIN_CHORD_CONFIDENCE,
    beats_to_events,
    chord_templates,
    merge_chords,
)


def test_beats_are_numbered_into_bars() -> None:
    beats = beats_to_events([0.0, 0.5, 1.0, 1.5, 2.0], beats_per_bar=4)
    assert [(b.bar, b.beat) for b in beats] == [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1)]
    assert beats[0].t == 0.0


def test_no_beats_yields_no_events() -> None:
    assert beats_to_events([]) == []


def test_templates_cover_every_major_and_minor_triad() -> None:
    names = [name for name, _ in chord_templates()]
    assert len(names) == 24
    assert "C" in names and "Am" in names and "F#m" in names


def test_templates_are_unit_vectors() -> None:
    for _, vector in chord_templates():
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, abs_tol=1e-9)


def test_c_major_template_is_c_e_g() -> None:
    template = dict(chord_templates())["C"]
    assert {i for i, v in enumerate(template) if v > 0} == {0, 4, 7}


def test_a_minor_template_is_a_c_e() -> None:
    template = dict(chord_templates())["Am"]
    assert {i for i, v in enumerate(template) if v > 0} == {9, 0, 4}


def test_repeated_labels_collapse_into_one_chord() -> None:
    chords = merge_chords(
        symbols=["Am", "Am", "G", "G", "G"],
        times=[0.0, 1.0, 2.0, 3.0, 4.0],
        confidences=[0.9, 0.8, 0.7, 0.9, 0.8],
        end_time=5.0,
    )
    assert [(c.symbol, c.t, c.dur) for c in chords] == [
        ("Am", 0.0, 2.0),
        ("G", 2.0, 3.0),
    ]


def test_merged_confidence_is_the_mean() -> None:
    chords = merge_chords(["Am", "Am"], [0.0, 1.0], [0.6, 0.8], end_time=2.0)
    assert math.isclose(chords[0].confidence, 0.7, abs_tol=1e-9)


def test_unlabelled_segments_are_skipped() -> None:
    chords = merge_chords(["Am", None, "G"], [0.0, 1.0, 2.0], [0.9, 0.0, 0.8], 3.0)
    assert [c.symbol for c in chords] == ["Am", "G"]


def test_confidence_threshold_is_a_real_threshold() -> None:
    assert 0.0 < MIN_CHORD_CONFIDENCE < 1.0
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_structure.py -q`
Expected: FAIL — `ImportError: cannot import name 'chord_templates'`

- [x] **Step 3: Write the implementation**

Keep the existing module docstring in `apps/worker/src/guitarvis_worker/stages/structure.py` and write:

```python
import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import StructureResult
from guitarvis_core.tabdoc import Beat, Chord, Timing

MIN_CHORD_CONFIDENCE = 0.5

_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_TRIADS = (("", (0, 4, 7)), ("m", (0, 3, 7)))


def chord_templates() -> list[tuple[str, tuple[float, ...]]]:
    """Unit-normalised chroma templates for all 24 major and minor triads.

    Plain tuples rather than numpy arrays: numpy must not be imported at module
    level in a stage, and keeping this pure means CI can test it.
    """
    magnitude = 1.0 / math.sqrt(3.0)
    templates = []
    for root, root_name in enumerate(_PITCH_NAMES):
        for suffix, intervals in _TRIADS:
            vector = [0.0] * 12
            for interval in intervals:
                vector[(root + interval) % 12] = magnitude
            templates.append((f"{root_name}{suffix}", tuple(vector)))
    return templates


def beats_to_events(beat_times: Sequence[float], beats_per_bar: int = 4) -> list[Beat]:
    """Number a flat list of beat times into bars and beats.

    Bar 1 starts at the first detected beat; downbeat detection is not
    attempted. A wrong phase shifts bar lines and never affects note sync,
    because notes carry their own wall-clock onsets.
    """
    return [
        Beat(t=float(t), bar=index // beats_per_bar + 1, beat=index % beats_per_bar + 1)
        for index, t in enumerate(beat_times)
    ]


def merge_chords(
    symbols: Sequence[str | None],
    times: Sequence[float],
    confidences: Sequence[float],
    end_time: float,
) -> list[Chord]:
    """Collapse per-segment labels into held chords, dropping unlabelled runs."""
    chords: list[Chord] = []
    index = 0
    while index < len(symbols):
        symbol = symbols[index]
        run_end = index + 1
        while run_end < len(symbols) and symbols[run_end] == symbol:
            run_end += 1

        if symbol is not None:
            stop = times[run_end] if run_end < len(times) else end_time
            span = confidences[index:run_end]
            chords.append(
                Chord(
                    t=float(times[index]),
                    dur=float(stop - times[index]),
                    symbol=symbol,
                    confidence=sum(span) / len(span),
                )
            )
        index = run_end
    return chords


class LibrosaStructureAnalyzer:
    """Implements guitarvis_core.contracts.StructureAnalyzer."""

    def __init__(
        self,
        beats_per_bar: int = 4,
        min_chord_confidence: float = MIN_CHORD_CONFIDENCE,
    ) -> None:
        self.beats_per_bar = beats_per_bar
        self.min_chord_confidence = min_chord_confidence

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        import librosa
        import numpy as np

        mix, mix_rate = librosa.load(str(mix_path), mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=mix, sr=mix_rate)
        beat_times = [
            float(t) for t in librosa.frames_to_time(beat_frames, sr=mix_rate)
        ]
        tempo_value = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else None

        timing = Timing(
            beats=beats_to_events(beat_times, self.beats_per_bar),
            tempo_bpm_avg=tempo_value if tempo_value and tempo_value > 0 else None,
            time_signature=f"{self.beats_per_bar}/4",
        )

        stem, stem_rate = librosa.load(str(stem_path), mono=True)
        chroma = librosa.feature.chroma_cqt(y=stem, sr=stem_rate)
        duration = float(librosa.get_duration(y=stem, sr=stem_rate))
        frame_times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=stem_rate)

        # Without a beat grid, fall back to fixed one-second segments: the
        # chord track should survive beat tracking failing.
        segments = (
            beat_times
            if len(beat_times) >= 2
            else [float(t) for t in np.arange(0.0, duration, 1.0)]
        )

        templates = [(name, np.array(vector)) for name, vector in chord_templates()]
        symbols: list[str | None] = []
        confidences: list[float] = []

        for index, start in enumerate(segments):
            stop = segments[index + 1] if index + 1 < len(segments) else duration
            mask = (frame_times >= start) & (frame_times < stop)
            profile = chroma[:, mask].mean(axis=1) if mask.any() else None
            norm = float(np.linalg.norm(profile)) if profile is not None else 0.0

            if profile is None or norm == 0.0:
                symbols.append(None)
                confidences.append(0.0)
                continue

            unit = profile / norm
            score, name = max(
                (float(unit @ vector), name) for name, vector in templates
            )
            if score < self.min_chord_confidence:
                symbols.append(None)
                confidences.append(0.0)
            else:
                symbols.append(name)
                confidences.append(min(1.0, score))

        return StructureResult(
            timing=timing,
            chords=merge_chords(symbols, segments, confidences, duration),
            sections=[],  # Section labelling is optional and not attempted in v1.
        )


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import StructureAnalyzer  # only, so this

    _conforms: StructureAnalyzer = LibrosaStructureAnalyzer()  # assignment is
    # what actually checks the signature.
```

- [x] **Step 4: Update the stub test**

Remove the stage-3 `NotImplementedError` assertion from `apps/worker/tests/test_stages.py`.

- [x] **Step 5: Run the tests**

Run: `uv run pytest apps/worker -q`
Expected: pass. Confirm the import scan still passes — `numpy` and `librosa` are imported inside `analyze`, never at module level.

- [x] **Step 6: Run the full gate and commit**

```bash
make check
git add apps/worker
git commit -m "feat(worker): implement stage 3 beat tracking and chord detection"
```

---

### Task 7: The orchestrator

Runs the stages in order, reports progress, and owns the degradation ladder. Stages arrive by injection, so the entire ladder is testable with stubs and no ML.

This is where the phase's known gap is handled: stage 4 still raises `NotImplementedError`, and the orchestrator treats that as a degraded track rather than a crash, exactly as it treats a failed structure analysis.

**Files:**
- Create: `apps/worker/src/guitarvis_worker/pipeline.py`
- Create: `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `IngestedAudio`, `SeparationResult`, `StructureResult`, `NoteEvent`, `TabNote`, `PipelineError`, the four stage protocols, `check_invariant`, and the tabdoc models.
- Produces: `StageProgress(stage: str, percent: int)`; `ProgressCallback`; `STAGE_PERCENT`; `run_pipeline(audio, *, separator, transcriber, analyzer, mapper, tuning=STANDARD_TUNING, progress=None) -> TabDocument`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_pipeline.py`:

```python
"""The orchestrator and the degradation ladder.

Every stage is stubbed. What is under test is what happens when one of them
fails: the design's promise is that only "no usable guitar audio" fails a job.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationResult,
    StructureResult,
    TabNote,
)
from guitarvis_core.tabdoc import Beat, Chord, Timing
from guitarvis_worker.pipeline import StageProgress, run_pipeline


class StubSeparator:
    def __init__(self, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []

    def isolate(self, audio_path: Path) -> SeparationResult:
        return SeparationResult(stem_path=audio_path, warnings=list(self.warnings))


class FailingSeparator:
    def isolate(self, audio_path: Path) -> SeparationResult:
        raise PipelineError(FailureReason.NO_GUITAR_DETECTED, "No clear guitar part")


class StubTranscriber:
    def __init__(self, events: Sequence[NoteEvent] = ()) -> None:
        self.events = list(events)

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return list(self.events)


class StubAnalyzer:
    def __init__(self, result: StructureResult | None = None) -> None:
        self.result = result or StructureResult(timing=Timing(), chords=[], sections=[])

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return self.result


class FailingAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        raise RuntimeError("beat tracker exploded")


class StubMapper:
    def __init__(self, notes: Sequence[TabNote] = ()) -> None:
        self.notes = list(notes)

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        return list(self.notes)


class UnimplementedMapper:
    """Stage 4 as it stands until 004-fretboard-mapper lands."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        raise NotImplementedError("Stage 4 lands in 004-fretboard-mapper")


def audio(tmp_path: Path) -> IngestedAudio:
    path = tmp_path / "song.wav"
    path.write_bytes(b"")
    return IngestedAudio(path=path, title="song", duration_sec=10.0)


def run(tmp_path: Path, **overrides):
    kwargs = {
        "separator": StubSeparator(),
        "transcriber": StubTranscriber(),
        "analyzer": StubAnalyzer(),
        "mapper": StubMapper(),
    }
    kwargs.update(overrides)
    return run_pipeline(audio(tmp_path), **kwargs)


def test_produces_a_valid_document(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        # D3 open is 50, so fret 2 is 52 — the invariant holds
        mapper=StubMapper([TabNote(1.0, 0.5, 52, 2, 2, 0.8)]),
        analyzer=StubAnalyzer(
            StructureResult(
                timing=Timing(beats=[Beat(t=0.0, bar=1, beat=1)], tempo_bpm_avg=120.0),
                chords=[Chord(t=0.0, dur=2.0, symbol="Am", confidence=0.9)],
                sections=[],
            )
        ),
    )

    assert doc.source.title == "song"
    assert doc.source.audio_url.startswith("file://")
    assert [(n.string, n.fret) for n in doc.notes] == [(2, 2)]
    assert doc.notes[0].id == "n_0000"
    assert doc.chords[0].symbol == "Am"
    assert doc.timing.tempo_bpm_avg == 120.0


def test_reports_progress_for_every_stage(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, progress=seen.append)

    assert [p.stage for p in seen] == [
        "separation",
        "transcription",
        "structure",
        "fretboard",
    ]
    assert [p.percent for p in seen] == [40, 65, 80, 100]


def test_no_guitar_is_the_only_hard_failure(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        run(tmp_path, separator=FailingSeparator())
    assert excinfo.value.reason is FailureReason.NO_GUITAR_DETECTED


def test_structure_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=StubMapper([TabNote(1.0, 0.5, 52, 2, 2, 0.8)]),
        analyzer=FailingAnalyzer(),
    )

    assert len(doc.notes) == 1  # notes keep their own onsets and survive
    assert doc.timing.beats == []
    assert doc.chords == []
    assert any("bar lines" in w for w in doc.warnings)


def test_unimplemented_fretboard_stage_degrades(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=UnimplementedMapper(),
    )

    assert doc.notes == []
    assert any("fretboard" in w.lower() for w in doc.warnings)


def test_separation_warnings_reach_the_document(tmp_path: Path) -> None:
    doc = run(tmp_path, separator=StubSeparator(["used the 4-stem track"]))
    assert "used the 4-stem track" in doc.warnings


def test_empty_transcription_warns_but_still_returns_a_document(tmp_path: Path) -> None:
    doc = run(tmp_path, transcriber=StubTranscriber([]))
    assert doc.notes == []
    assert any("no notes" in w.lower() for w in doc.warnings)


def test_a_note_violating_the_invariant_is_rejected(tmp_path: Path) -> None:
    # String 2 (D3=50) fret 2 sounds 52, so a mapper claiming 53 is broken
    with pytest.raises(PipelineError) as excinfo:
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 53, 0.8)]),
            mapper=StubMapper([TabNote(1.0, 0.5, 53, 2, 2, 0.8)]),
        )
    assert excinfo.value.reason is FailureReason.INTERNAL
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_pipeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_worker.pipeline'`

- [x] **Step 3: Write the implementation**

`apps/worker/src/guitarvis_worker/pipeline.py`:

```python
"""Runs the stages in order and assembles a tab document.

The degradation ladder lives here. Every stage after separation is optional to
the core promise, so a failure downstream costs the user a feature rather than
the whole job. Only "no usable guitar audio" fails outright.

Stages arrive by injection: the worker decides what to run, and the stages stay
ignorant of each other.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    IngestedAudio,
    PipelineError,
    Separator,
    StructureAnalyzer,
    StructureResult,
    Transcriber,
)
from guitarvis_core.fretboard import InvariantViolation, check_invariant
from guitarvis_core.tabdoc import (
    STANDARD_TUNING,
    Instrument,
    Note,
    Source,
    TabDocument,
    Timing,
)

STAGE_PERCENT = {
    "separation": 40,
    "transcription": 65,
    "structure": 80,
    "fretboard": 100,
}


@dataclass(frozen=True)
class StageProgress:
    stage: str
    percent: int


ProgressCallback = Callable[[StageProgress], None]


def _report(progress: ProgressCallback | None, stage: str) -> None:
    if progress is not None:
        progress(StageProgress(stage=stage, percent=STAGE_PERCENT[stage]))


def run_pipeline(
    audio: IngestedAudio,
    *,
    separator: Separator,
    transcriber: Transcriber,
    analyzer: StructureAnalyzer,
    mapper: FretboardMapper,
    tuning: Sequence[str] = STANDARD_TUNING,
    progress: ProgressCallback | None = None,
) -> TabDocument:
    """Turn ingested audio into a tab document."""
    warnings: list[str] = []

    # Stage 1. The only stage whose failure is fatal: with no guitar audio
    # there is nothing to transcribe and nothing honest to show.
    separation = separator.isolate(audio.path)
    warnings.extend(separation.warnings)
    _report(progress, "separation")

    # Stage 2.
    events = transcriber.transcribe(separation.stem_path)
    if not events:
        warnings.append("No notes were detected in the isolated guitar part.")
    _report(progress, "transcription")

    # Stage 3. Optional: notes carry their own onsets, so losing the beat grid
    # costs bar lines and chord symbols, never synchronisation.
    structure = StructureResult(timing=Timing(), chords=[], sections=[])
    try:
        structure = analyzer.analyze(separation.stem_path, audio.path)
    except Exception as exc:  # noqa: BLE001 - every analyzer failure degrades alike
        warnings.append(
            f"Beat and chord detection failed ({exc.__class__.__name__}), so "
            "bar lines and chord symbols are unavailable."
        )
    _report(progress, "structure")

    # Stage 4. Not implemented until 004-fretboard-mapper, and treated as a
    # degraded track until then rather than a crash.
    tab_notes = []
    try:
        tab_notes = mapper.assign(events, tuning)
    except NotImplementedError:
        warnings.append(
            "Fretboard assignment is not implemented yet, so this document "
            "carries no notes. Timing and chords are unaffected."
        )
    _report(progress, "fretboard")

    notes = [
        Note(
            id=f"n_{index:04d}",
            t=tab.onset,
            dur=tab.duration,
            midi=tab.midi,
            string=tab.string,
            fret=tab.fret,
            confidence=tab.confidence,
        )
        for index, tab in enumerate(tab_notes)
    ]

    # A tab that renders the wrong fret is worse than no tab: a beginner cannot
    # tell it from a hard passage. Refuse to emit one.
    for note in notes:
        try:
            check_invariant(note, tuning)
        except InvariantViolation as exc:
            raise PipelineError(
                FailureReason.INTERNAL, f"Fretboard assignment is inconsistent: {exc}"
            ) from exc

    return TabDocument(
        source=Source(
            title=audio.title,
            duration_sec=audio.duration_sec,
            audio_url=audio.path.resolve().as_uri(),
        ),
        instrument=Instrument(tuning=list(tuning), string_count=len(tuning)),
        timing=structure.timing,
        notes=notes,
        chords=structure.chords,
        sections=structure.sections,
        warnings=warnings,
    )
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest apps/worker/tests/test_pipeline.py -q`
Expected: pass. No ML library is imported during this run, which is the point of injecting the stages.

- [x] **Step 5: Run the full gate and commit**

```bash
make check
git add apps/worker
git commit -m "feat(worker): add the orchestrator and its degradation ladder"
```

---

### Task 8: The CLI and the end-to-end run

The phase deliverable. Wires ingestion to the orchestrator, prints stage progress, and maps typed failures to actionable messages and exit codes.

**Files:**
- Create: `apps/worker/src/guitarvis_worker/cli.py`
- Create: `apps/worker/tests/test_cli.py`
- Modify: `apps/worker/pyproject.toml` (console script)
- Modify: `README.md`, `CLAUDE.md` (phase 1 is done; phase 2 is next)

**Interfaces:**
- Consumes: `UploadSource`, `run_pipeline`, the four stage classes, `PipelineError`.
- Produces: `main(argv: list[str] | None = None) -> int`; console script `guitarvis-worker`.

- [x] **Step 1: Write the failing test**

`apps/worker/tests/test_cli.py`:

```python
"""The CLI's contract: a written document, honest errors, useful exit codes."""

import json
import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import SeparationResult, StructureResult
from guitarvis_core.tabdoc import Timing
from guitarvis_worker import cli


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


class StubSeparator:
    def isolate(self, audio_path: Path) -> SeparationResult:
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list:
        return []


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


@pytest.fixture
def stub_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "DemucsSeparator", lambda **kwargs: StubSeparator())
    monkeypatch.setattr(
        cli, "BasicPitchTranscriber", lambda **kwargs: StubTranscriber()
    )
    monkeypatch.setattr(
        cli, "LibrosaStructureAnalyzer", lambda **kwargs: StubAnalyzer()
    )


def test_writes_a_valid_document_and_exits_zero(
    tmp_path: Path, stub_stages: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "song.json"
    code = cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])

    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["notes"] == []
    assert "100%" in capsys.readouterr().err


def test_reports_the_pending_fretboard_stage(
    tmp_path: Path, stub_stages: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "song.json"
    cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])
    assert "004" in capsys.readouterr().err


def test_missing_file_reports_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["process", str(tmp_path / "nope.wav"), "-o", str(tmp_path / "o.json")]
    )
    assert code == 2
    assert "unsupported_format" in capsys.readouterr().err


def test_too_long_reports_its_own_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "process",
            str(write_wav(tmp_path / "song.wav", seconds=2.0)),
            "-o",
            str(tmp_path / "o.json"),
            "--max-duration",
            "1",
        ]
    )
    assert code == 2
    assert "too_long" in capsys.readouterr().err
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'cli'`

- [x] **Step 3: Write the implementation**

`apps/worker/src/guitarvis_worker/cli.py`:

```python
"""Command line entry point for the pipeline.

Stage construction happens here, not inside run_pipeline, so the CLI can be
tested end to end without loading a model: the names below are what tests
patch. It is also the seam the future job worker replaces.
"""

import argparse
import sys
from pathlib import Path

from guitarvis_core.contracts import PipelineError
from guitarvis_core.tabdoc import STANDARD_TUNING
from guitarvis_worker.ingest import MAX_DURATION_SEC, UploadSource
from guitarvis_worker.pipeline import StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber


def _print_progress(update: StageProgress) -> None:
    print(f"  {update.stage:<14} {update.percent:>3}%", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guitarvis-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("process", help="turn an audio file into tablature")
    run.add_argument("audio", help="path to an audio file")
    run.add_argument(
        "-o", "--output", required=True, help="where to write the document"
    )
    run.add_argument(
        "--tuning",
        default=",".join(STANDARD_TUNING),
        help="comma-separated open strings, lowest first",
    )
    run.add_argument(
        "--max-duration",
        type=float,
        default=MAX_DURATION_SEC,
        help="reject inputs longer than this many seconds",
    )
    run.add_argument("--device", default=None, help="torch device, e.g. cuda")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        audio = UploadSource(args.audio, max_duration_sec=args.max_duration).fetch()
        document = run_pipeline(
            audio,
            separator=DemucsSeparator(device=args.device),
            transcriber=BasicPitchTranscriber(),
            analyzer=LibrosaStructureAnalyzer(),
            mapper=ViterbiFretboardMapper(),
            tuning=args.tuning.split(","),
            progress=_print_progress,
        )
    except PipelineError as error:
        print(f"error [{error.reason.value}]: {error}", file=sys.stderr)
        return 2

    Path(args.output).write_text(document.model_dump_json(indent=2))

    print(
        f"wrote {args.output}: {len(document.notes)} notes, "
        f"{len(document.chords)} chords, {len(document.timing.beats)} beats",
        file=sys.stderr,
    )
    for warning in document.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add the console script to `apps/worker/pyproject.toml`:

```toml
[project.scripts]
guitarvis-worker = "guitarvis_worker.cli:main"
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest apps/worker/tests/test_cli.py -q`
Expected: pass.

- [ ] **Step 5: Process a real song end to end**

The phase milestone. Use any song you own.

```bash
uv sync --extra ml
uv run guitarvis-worker process ~/Music/some-song.mp3 -o /tmp/some-song.json --device cuda
python -c "
import json; d = json.load(open('/tmp/some-song.json'))
print('beats:', len(d['timing']['beats']), 'tempo:', d['timing']['tempo_bpm_avg'])
print('chords:', [c['symbol'] for c in d['chords'][:12]])
print('warnings:', d['warnings'])
"
```

Expected: stage progress on stderr; a document with a populated beat grid and chord track, an empty `notes` array, and the warning naming 004. Sanity-check the chords against the song — if they are nonsense, that is a finding for the spec's open decision on chord source, not a blocker for this phase.

- [x] **Step 6: Validate the output against the committed schema**

```bash
uv run python -c "
import json
from guitarvis_core.tabdoc import TabDocument
TabDocument.model_validate(json.load(open('/tmp/some-song.json')))
print('document validates')
"
```

Expected: `document validates`.

- [x] **Step 7: Update the docs**

In `CLAUDE.md`, move the `← next` marker from phase 1 to phase 2. In `README.md`, document the CLI:

```markdown
    uv sync --extra ml
    uv run guitarvis-worker process song.mp3 -o song.json
```

Note that `notes` stays empty until 004-fretboard-mapper lands.

- [x] **Step 8: Run the full gate and commit**

```bash
make check
git add apps/worker README.md CLAUDE.md
git commit -m "feat(worker): add the process CLI and complete the pipeline skeleton"
```

---

## Completion checklist

> **Two boxes stay unticked deliberately.** No real song has been processed end
> to end: `ffprobe` is absent on the development machine and installing ffmpeg
> needs sudo. A substitute verification ran the real pipeline (Demucs,
> basic-pitch, librosa) against synthetic audio below the ingestion layer and
> produced a schema-valid document; see
> [review-notes.md](review-notes.md). Everything else was performed as written,
> except Task 8 step 6, which validated that substitute document rather than a
> real song's.


- [x] `make check` passes with no ML dependencies installed.
- [x] `uv sync --extra ml` resolves with no TensorFlow in the tree.
- [ ] A real song processes end to end and the output validates against the committed schema.
- [x] The document carries a beat grid, a chord track, and the warning naming 004.
- [x] `CLAUDE.md`'s phase marker points at phase 2.

## Opening the PR

Use `.github/pull_request_template.md`. The **Spec:** line is `docs/specs/003-pipeline-skeleton/spec.md`.

Worth calling out for the reviewer: the two dependency overrides ([ADR 0006](../../decisions/0006-onnx-transcription-backend.md)), the three core contract additions in Task 2, and the empty `notes` array, which is the deliberate consequence of splitting stage 4 into 004.
