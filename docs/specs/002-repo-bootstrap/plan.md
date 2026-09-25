# Repository Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a repository holding one design document into a uv workspace monorepo with a drift-checked tab document contract, enforced conventions, and a green `make check` on an essentially empty tree.

**Architecture:** Four uv workspace members (`packages/core`, `apps/api`, `apps/worker`, `apps/eval`) plus a `web/` npm workspace. `core` owns the tab document as Pydantic models — the single source of truth — from which a JSON Schema and TypeScript types are generated, committed, and diff-checked in CI. Rules that matter are mechanisms, not notes: a static import scan keeps ML out of `api`, a pre-commit hook keeps commits off `main`, and `make eval` sits outside `make check`.

**Tech Stack:** Python 3.12, uv, Pydantic v2, pytest, mypy, ruff · Node 22, Vite, React, TypeScript, vitest, ESLint, json-schema-to-typescript · GNU make, GitHub Actions

**Spec:** [`docs/specs/002-repo-bootstrap/spec.md`](./spec.md) · Parent: [`docs/specs/001-guitarvis-design/spec.md`](../001-guitarvis-design/spec.md)

## Global Constraints

Every task's requirements implicitly include this section.

- **Python `>=3.12`**; the development machine has 3.12.3. Node `22`; npm `10.9.3`.
- **Branch:** all work happens on `002-repo-bootstrap`. Never commit to `main`.
- **Python distribution names** are `guitarvis-core`, `guitarvis-api`, `guitarvis-worker`, `guitarvis-eval`; **import names** are the same with underscores.
- **Workspace members:** `packages/core`, `apps/api`, `apps/worker`, `apps/eval`. `core` depends only on Pydantic. `api` and `worker` depend on `core`. Only `worker` and `eval` may declare torch/demucs/basic-pitch.
- **Heavy ML dependencies are an optional extra**, never default. `uv sync` must stay light and CI must download no model weights. Phase 1 installs them with `uv sync --extra ml`. *(This refines the parent spec, which names the dependencies but not their install-time grouping.)*
- **`SCHEMA_VERSION = 1`.** Tab document field names are exactly those fixed in the parent spec: `schema_version`, `source`, `instrument`, `timing`, `notes`, `chords`, `sections`.
- **Failure reasons** are exactly: `unsupported_format`, `no_guitar_detected`, `too_long`, `fetch_failed`, `internal`.
- **Hard invariant:** `pitch_of(string, fret, tuning) == note.midi`, for every note, always.
- **Seconds are authoritative.** Never store a note position as bar/beat.
- **Generated artifacts are committed:** `schema/tab-document.schema.json` and `web/src/types/tabDocument.ts`. CI fails if regenerating them produces a diff.
- **`eval/results/` and `schema/` are tracked on purpose** — never add them to `.gitignore`.
- **Evaluation is measured, never gated.** `make eval` must not be reachable from `make check`.
- **Commits** follow Conventional Commits and end with the line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| Path | Responsibility |
|---|---|
| `.gitignore` | What never enters git; carries the do-not-ignore note for `schema/` and `eval/results/` |
| `LICENSE` | MIT |
| `.githooks/pre-commit` | Refuses commits on `main` |
| `.github/pull_request_template.md` | Forces a **Spec:** link on every PR |
| `.github/workflows/ci.yml` | Runs `make check` on push and PR |
| `Makefile` | The command surface; the only place task names are defined |
| `pyproject.toml` | uv workspace root, dev dependency group, pytest config |
| `ruff.toml` / `mypy.ini` | Lint/format rules; strict typing scoped to the contract modules |
| `packages/core/src/guitarvis_core/tabdoc.py` | The tab document — single source of truth |
| `packages/core/src/guitarvis_core/fretboard.py` | Pitch arithmetic and the hard invariant |
| `packages/core/src/guitarvis_core/contracts.py` | Stage Protocols, plain data types, failure taxonomy |
| `packages/core/src/guitarvis_core/schema_export.py` | Emits the JSON Schema deterministically |
| `packages/core/tests/fixtures/minimal.tabdoc.json` | The cross-language fixture, read by pytest *and* vitest |
| `apps/api/src/guitarvis_api/app.py` | FastAPI shell, no routes yet |
| `apps/api/tests/test_boundaries.py` | Static + runtime proof that `api` carries no ML |
| `apps/worker/src/guitarvis_worker/stages/*.py` | One stub per pipeline stage, typed against the Protocols |
| `apps/eval/src/guitarvis_eval/__main__.py` | Harness entry point; phase 2 fills it |
| `eval/results/` | Tracked metric history |
| `web/scripts/generate-types.mjs` | JSON Schema → TypeScript |
| `web/src/types/tabDocument.ts` | Generated; never hand-edited |
| `web/src/types/tabDocument.test.ts` | Proves the shared fixture matches the generated type |
| `README.md` `CONTRIBUTING.md` `CLAUDE.md` `docs/CONVENTIONS.md` | The four audiences: stranger, operator, agent, code author |
| `docs/decisions/` | ADRs, template, and the open-decision backlog |
| `.claude/skills/` | `tab-document`, `pipeline-stage`, `eval-harness`, `spec-workflow` |

---

### Task 1: Repo hygiene and the spec workflow

**Files:**
- Create: `.gitignore`, `LICENSE`, `.githooks/pre-commit`, `.github/pull_request_template.md`
- Move: `docs/superpowers/specs/2026-09-24-guitarvis-design.md` → `docs/specs/001-guitarvis-design/spec.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the branch discipline every later task commits under; `git config core.hooksPath .githooks`, which Task 11 folds into `make install`.

- [x] **Step 1: Migrate the parent spec to the repo convention**

```bash
mkdir -p docs/specs/001-guitarvis-design
git mv docs/superpowers/specs/2026-09-24-guitarvis-design.md \
       docs/specs/001-guitarvis-design/spec.md
rmdir docs/superpowers/specs docs/superpowers
```

- [x] **Step 2: Verify the move left nothing behind**

Run: `ls docs && ls docs/specs/001-guitarvis-design && test ! -d docs/superpowers && echo OK`
Expected: `CONVENTIONS.md` is absent (not yet written), `specs` present, `spec.md` listed, `OK` printed.

- [x] **Step 3: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
build/
dist/

# Node
node_modules/
web/dist/
.vite/

# Environment
.env
.env.*
!.env.example

# OS
.DS_Store
Thumbs.db

# Model weights — the worker downloads these on first run, they never enter git
models/
*.pt
*.pth
*.onnx
*.ckpt

# Audio — uploads, stems, and intermediates. Test fixtures are re-included below.
*.wav
*.mp3
*.flac
*.m4a
*.ogg
!**/tests/fixtures/**

# Local object storage
.minio/
storage/

# ──────────────────────────────────────────────────────────────────────
# Tracked on purpose. Do NOT add these, however generated they look:
#   schema/          generated from tabdoc.py, committed, diff-checked in CI
#   web/src/types/   likewise
#   eval/results/    tracked metric history; the point is comparing runs
# ──────────────────────────────────────────────────────────────────────
```

- [x] **Step 4: Write `LICENSE`**

```
MIT License

Copyright (c) 2026 Sam Madinya

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [x] **Step 5: Write `.githooks/pre-commit`**

```bash
#!/usr/bin/env bash
# Refuse commits on main.
#
# GuitarVis changes land through a pull request from a spec branch, and the
# branch name is its docs/specs/NNN-short-name/ folder name.
set -euo pipefail

branch="$(git rev-parse --abbrev-ref HEAD)"

if [ "$branch" = "main" ]; then
  cat >&2 <<'MSG'
✗ Commit refused: you are on main.

  Work belongs on a spec branch named after its spec folder:

      git checkout -b 003-pipeline-skeleton

  See CONTRIBUTING.md. Bypass with --no-verify only for a genuine exception.
MSG
  exit 1
fi
```

- [x] **Step 6: Make the hook executable and activate it**

```bash
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

- [x] **Step 7: Write `.github/pull_request_template.md`**

```markdown
**Spec:** docs/specs/NNN-short-name/spec.md

<!-- Every PR implements a spec. If there is no spec folder, write one first;
     see .claude/skills/spec-workflow/SKILL.md. -->

## What changed

<!-- One paragraph. What a reviewer needs before reading the diff. -->

## Verification

- [x] `make check` passes locally
- [x] Contract artifacts regenerated if `tabdoc.py` changed (`make schema`)
- [x] Plan checkboxes in `docs/specs/NNN-short-name/plan.md` updated

## Deviations from the spec

<!-- Anything implemented differently than designed, and why. "None" is a
     valid answer, and a common one. -->
```

- [x] **Step 8: Commit**

```bash
git add .gitignore LICENSE .githooks .github docs/specs/001-guitarvis-design
git commit -m "$(cat <<'EOF'
chore: add repo hygiene, MIT license, and spec workflow enforcement

Migrate the design spec to docs/specs/001-guitarvis-design/spec.md, the
convention this repo now uses. A pre-commit hook refuses commits on main
so the branch-per-spec rule is a mechanism rather than a note, and the PR
template requires a spec link.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [x] **Step 9: Prove the hook refuses a commit on `main`**

This cannot be tested in place. `core.hooksPath` points at `.githooks/`, which
does not exist in `main`'s tree until this branch merges — checking out `main`
removes the directory, and git then silently runs no hook at all. Testing in
place produces a commit that succeeds and tells you nothing.

Test it in a throwaway clone where `main` does contain the hook:

```bash
T=$(mktemp -d)
git clone -q . "$T"
cd "$T"
git branch -f main origin/002-repo-bootstrap
git checkout -q main
git config core.hooksPath .githooks
git commit --allow-empty -m "should be refused"
```
Expected: FAIL, exit code 1, with the "Commit refused: you are on main" message.

- [x] **Step 10: Prove the hook permits a commit on a spec branch**

Still in the throwaway clone:

```bash
git checkout -q -b 003-pipeline-skeleton
git commit --allow-empty -m "should be permitted"
```
Expected: PASS — the commit is created.

- [x] **Step 11: Discard the throwaway clone**

```bash
cd - && rm -rf "$T"
git status --short   # in the real repo: no changes, still on 002-repo-bootstrap
```

Nothing in the real repository was touched by the test, which is the reason to
run it in a clone rather than by committing to `main` and resetting afterwards.

---

### Task 2: uv workspace and the `core` package skeleton

**Files:**
- Create: `pyproject.toml`, `ruff.toml`, `mypy.ini`
- Create: `packages/core/pyproject.toml`, `packages/core/src/guitarvis_core/__init__.py`
- Test: `packages/core/tests/test_package.py`

**Interfaces:**
- Consumes: Task 1's branch discipline.
- Produces: `guitarvis_core.__version__: str` (`"0.1.0"`); a working `uv sync` and `uv run pytest`; the workspace every later Python task adds a member to.

- [x] **Step 1: Install uv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```
Expected: a version string. Add `$HOME/.local/bin` to your shell profile so later sessions find it.

- [x] **Step 2: Write the failing test**

Create `packages/core/tests/test_package.py`:

```python
"""The core package must import cleanly and stay free of heavy dependencies.

core is imported by api, which must never pull torch into its process. The
cheapest guard is at the bottom of the dependency graph.
"""

import sys


def test_core_exposes_a_version() -> None:
    import guitarvis_core

    assert guitarvis_core.__version__ == "0.1.0"


def test_importing_core_loads_no_ml_modules() -> None:
    import guitarvis_core  # noqa: F401

    for forbidden in ("torch", "demucs", "basic_pitch"):
        assert forbidden not in sys.modules, f"core pulled in {forbidden}"
```

- [x] **Step 3: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_package.py -v`
Expected: FAIL — uv cannot build the workspace, or `ModuleNotFoundError: No module named 'guitarvis_core'`.

- [x] **Step 4: Write the workspace root `pyproject.toml`**

```toml
[project]
name = "guitarvis"
version = "0.1.0"
description = "Audio to guitar tablature, with synced play-along views."
requires-python = ">=3.12"
dependencies = [
    "guitarvis-core",
    "guitarvis-api",
    "guitarvis-worker",
    "guitarvis-eval",
]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/core", "apps/api", "apps/worker", "apps/eval"]

[tool.uv.sources]
guitarvis-core = { workspace = true }
guitarvis-api = { workspace = true }
guitarvis-worker = { workspace = true }
guitarvis-eval = { workspace = true }

[dependency-groups]
dev = [
    "pytest>=8.3",
    "mypy>=1.13",
    "ruff>=0.8",
]

[tool.pytest.ini_options]
testpaths = ["packages", "apps"]
addopts = "-q"
```

Note: the four workspace members are all listed now, but only `core` exists yet. Tasks 6–8 create the rest; `uv sync` will fail until then unless you create the stub members in this task. To keep each task independently runnable, create the three remaining member directories with a minimal `pyproject.toml` here, and let Tasks 6–8 fill in their contents.

- [x] **Step 5: Create minimal manifests for the not-yet-built members**

```bash
mkdir -p apps/api/src/guitarvis_api apps/worker/src/guitarvis_worker apps/eval/src/guitarvis_eval
```

Write the same shape to each — `apps/api/pyproject.toml`:

```toml
[project]
name = "guitarvis-api"
version = "0.1.0"
description = "HTTP surface. No ML code, no model weights."
requires-python = ">=3.12"
dependencies = ["guitarvis-core"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_api"]
```

`apps/worker/pyproject.toml`:

```toml
[project]
name = "guitarvis-worker"
version = "0.1.0"
description = "The pipeline. The only component that needs torch or weights."
requires-python = ">=3.12"
dependencies = ["guitarvis-core"]

# Heavy ML dependencies are opt-in so that `uv sync` and CI stay light.
# Phase 1 (003-pipeline-skeleton) installs these with `uv sync --extra ml`.
#
# basic-pitch is deliberately absent — it cannot install on this project's
# Python 3.12. See the comment in apps/worker/pyproject.toml.
[project.optional-dependencies]
ml = [
    "torch>=2.4",
    "demucs>=4.0",
    "librosa>=0.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_worker"]
```

`apps/eval/pyproject.toml`:

```toml
[project]
name = "guitarvis-eval"
version = "0.1.0"
description = "GuitarSet evaluation harness. Measured, never gated."
requires-python = ">=3.12"
dependencies = ["guitarvis-core"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_eval"]
```

Then create empty package roots so the builds succeed:

```bash
touch apps/api/src/guitarvis_api/__init__.py
touch apps/worker/src/guitarvis_worker/__init__.py
touch apps/eval/src/guitarvis_eval/__init__.py
```

- [x] **Step 6: Write `packages/core/pyproject.toml`**

```toml
[project]
name = "guitarvis-core"
version = "0.1.0"
description = "Tab document contract, stage interfaces, and shared invariants."
requires-python = ">=3.12"
dependencies = ["pydantic>=2.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_core"]
```

- [x] **Step 7: Write `packages/core/src/guitarvis_core/__init__.py`**

```python
"""Shared contract between the GuitarVis pipeline and every client.

This package is deliberately light: Pydantic and the standard library only.
api imports it, and api must never load torch.
"""

__version__ = "0.1.0"
```

- [x] **Step 8: Write `ruff.toml`**

```toml
line-length = 88
target-version = "py312"

[lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[format]
quote-style = "double"
```

- [x] **Step 9: Write `mypy.ini`**

```ini
[mypy]
python_version = 3.12
warn_unused_configs = True
warn_redundant_casts = True
warn_unused_ignores = True
ignore_missing_imports = True

; Strict where the contract lives. Everything else stays lenient so that
; exploratory pipeline code is not fought with type errors during phase 1.
;
; mypy's `strict` is a command-line flag only and cannot be set per module, so
; the contract modules name the individual flags it implies.
[mypy-guitarvis_core.tabdoc]
disallow_untyped_defs = True
disallow_incomplete_defs = True
disallow_untyped_calls = True
no_implicit_optional = True
warn_return_any = True
strict_equality = True

[mypy-guitarvis_core.contracts]
disallow_untyped_defs = True
disallow_incomplete_defs = True
disallow_untyped_calls = True
no_implicit_optional = True
warn_return_any = True
strict_equality = True

[mypy-guitarvis_core.fretboard]
disallow_untyped_defs = True
disallow_incomplete_defs = True
disallow_untyped_calls = True
no_implicit_optional = True
warn_return_any = True
strict_equality = True
```

- [x] **Step 10: Sync and run the test to verify it passes**

Run: `uv sync && uv run pytest packages/core/tests/test_package.py -v`
Expected: PASS, 2 passed. `uv.lock` is created, and `uv sync` completes without downloading torch.

- [x] **Step 11: Confirm the sync stayed light**

Run: `uv run python -c "import torch" 2>&1 | tail -1`
Expected: `ModuleNotFoundError: No module named 'torch'` — the ml extra was not installed.

- [x] **Step 12: Commit**

```bash
git add pyproject.toml uv.lock ruff.toml mypy.ini packages apps
git commit -m "$(cat <<'EOF'
feat: add uv workspace with the core package

Four members: core, api, worker, eval. core depends only on Pydantic so
that api, which imports it, cannot acquire torch transitively. The
worker's ML dependencies are an opt-in extra, keeping uv sync and CI
light until phase 1 needs them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The tab document

**Files:**
- Create: `packages/core/src/guitarvis_core/tabdoc.py`
- Create: `packages/core/tests/fixtures/minimal.tabdoc.json`
- Test: `packages/core/tests/test_tabdoc.py`

**Interfaces:**
- Consumes: `guitarvis_core` package from Task 2.
- Produces: `SCHEMA_VERSION: int`; models `TabDocument`, `Source`, `Instrument`, `Beat`, `Timing`, `Note`, `Chord`, `Section`, `Technique`. Task 5 imports `Timing`, `Chord`, `Section`. Task 10 imports `TabDocument`. The fixture path `packages/core/tests/fixtures/minimal.tabdoc.json` is read by Task 10's vitest test.

- [x] **Step 1: Write the fixture**

Create `packages/core/tests/fixtures/minimal.tabdoc.json`. This file is read by
pytest *and* by vitest, so it is the one artifact both languages agree on.

```json
{
  "schema_version": 1,
  "source": {
    "title": "Fixture Song",
    "duration_sec": 12.5,
    "audio_url": "s3://guitarvis-test/fixture.wav"
  },
  "instrument": {
    "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
    "capo": 0,
    "string_count": 6
  },
  "timing": {
    "beats": [
      { "t": 0.0, "bar": 1, "beat": 1 },
      { "t": 0.5, "bar": 1, "beat": 2 }
    ],
    "tempo_bpm_avg": 120.0,
    "time_signature": "4/4"
  },
  "notes": [
    {
      "id": "n_0000",
      "t": 0.0,
      "dur": 0.5,
      "midi": 40,
      "string": 0,
      "fret": 0,
      "confidence": 0.95,
      "technique": null
    },
    {
      "id": "n_0001",
      "t": 0.5,
      "dur": 0.25,
      "midi": 52,
      "string": 2,
      "fret": 2,
      "confidence": 0.81,
      "technique": null
    }
  ],
  "chords": [
    { "t": 0.0, "dur": 2.0, "symbol": "Em", "confidence": 0.9 }
  ],
  "sections": [
    { "t": 0.0, "dur": 12.5, "label": "intro" }
  ]
}
```

- [x] **Step 2: Write the failing test**

Create `packages/core/tests/test_tabdoc.py`:

```python
"""The tab document is the contract between the pipeline and every client.

These tests pin the parts a client would break on: the version, the field
names, and the refusal to silently accept anything unexpected.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from guitarvis_core.tabdoc import SCHEMA_VERSION, TabDocument

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
```

- [x] **Step 3: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_tabdoc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_core.tabdoc'`.

- [x] **Step 4: Write the implementation**

Create `packages/core/src/guitarvis_core/tabdoc.py`:

```python
"""The tab document.

Two shape decisions carry the weight, both argued in
docs/specs/001-guitarvis-design/spec.md:

Seconds are authoritative. Every note carries a wall-clock onset; bars and
beats live in timing.beats, which maps time to musical position. Beat tracking
is the most error-prone stage, and storing note positions as bar/beat would let
a tempo error desynchronise playback from audio — the one thing a play-along
app must never do.

The note list is flat. Measures are computed from the beat grid at render time,
so correcting timing does not rewrite the notes, and the fretboard views parse
no structure they do not need.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

STANDARD_TUNING = ("E2", "A2", "D3", "G3", "B3", "E4")


class Strict(BaseModel):
    """Base for every document model.

    extra="forbid" is the point: a client that sends a field this version does
    not know about should be told, not silently ignored.
    """

    model_config = ConfigDict(extra="forbid")


class Technique(str, Enum):
    BEND = "bend"
    SLIDE = "slide"
    HAMMER = "hammer"
    PULL = "pull"
    MUTE = "mute"
    HARMONIC = "harmonic"


class Source(Strict):
    title: str
    duration_sec: float = Field(ge=0)
    audio_url: str


class Instrument(Strict):
    tuning: list[str] = Field(
        default_factory=lambda: list(STANDARD_TUNING),
        description="Scientific pitch names, low string first.",
    )
    capo: int = Field(default=0, ge=0)
    string_count: int = Field(default=6, ge=1)


class Beat(Strict):
    t: float = Field(ge=0)
    bar: int = Field(ge=1)
    beat: int = Field(ge=1)


class Timing(Strict):
    beats: list[Beat] = Field(default_factory=list)
    tempo_bpm_avg: float | None = Field(default=None, gt=0)
    time_signature: str | None = None


class Note(Strict):
    id: str
    t: float = Field(ge=0, description="Onset in seconds. Authoritative.")
    dur: float = Field(ge=0)
    midi: int = Field(ge=0, le=127)
    string: int = Field(ge=0, description="0 is the lowest string.")
    fret: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    technique: Technique | None = None


class Chord(Strict):
    t: float = Field(ge=0)
    dur: float = Field(ge=0)
    symbol: str
    confidence: float = Field(ge=0, le=1)


class Section(Strict):
    t: float = Field(ge=0)
    dur: float = Field(ge=0)
    label: str


class TabDocument(Strict):
    schema_version: int = SCHEMA_VERSION
    source: Source
    instrument: Instrument
    timing: Timing
    notes: list[Note] = Field(default_factory=list)
    chords: list[Chord] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
```

- [x] **Step 5: Run the test to verify it passes**

Run: `uv run pytest packages/core/tests/test_tabdoc.py -v`
Expected: PASS, 6 passed.

- [x] **Step 6: Commit**

```bash
git add packages/core/src/guitarvis_core/tabdoc.py packages/core/tests
git commit -m "$(cat <<'EOF'
feat(core): add the tab document as the single source of truth

Pydantic models with extra="forbid", so a client sending an unknown field
is told rather than silently ignored. Optional tracks default to empty,
which is what the degradation ladder needs: a job that loses chord
detection omits the track instead of sending scaffolding.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The fretboard invariant

**Files:**
- Create: `packages/core/src/guitarvis_core/fretboard.py`
- Test: `packages/core/tests/test_fretboard.py`

**Interfaces:**
- Consumes: `guitarvis_core.tabdoc.Note`, `STANDARD_TUNING`.
- Produces: `parse_pitch(name: str) -> int`, `pitch_of(string_index: int, fret: int, tuning: Sequence[str]) -> int`, `check_invariant(note: Note, tuning: Sequence[str]) -> None`, `InvariantViolation(Exception)`. Phase 2's `FretboardMapper` calls all of these.

- [x] **Step 1: Write the failing test**

Create `packages/core/tests/test_fretboard.py`:

```python
"""The hard invariant: pitch(string, fret, tuning) == the note's MIDI pitch.

The parent spec makes fretboard assignment deterministic precisely so that
tablature correctness does not depend on model accuracy. This is the assertion
that keeps that promise true.
"""

import pytest

from guitarvis_core.fretboard import (
    InvariantViolation,
    check_invariant,
    parse_pitch,
    pitch_of,
)
from guitarvis_core.tabdoc import STANDARD_TUNING, Note

MAX_FRET = 24


@pytest.mark.parametrize(
    ("name", "midi"),
    [
        ("C-1", 0),
        ("E2", 40),
        ("A2", 45),
        ("D3", 50),
        ("C4", 60),
        ("A4", 69),
        ("E4", 64),
        ("Eb3", 51),
        ("F#2", 42),
    ],
)
def test_parse_pitch(name: str, midi: int) -> None:
    assert parse_pitch(name) == midi


def test_parse_pitch_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        parse_pitch("H7")


def test_open_low_e_is_midi_40() -> None:
    assert pitch_of(0, 0, STANDARD_TUNING) == 40


def test_spec_example_d_string_second_fret_is_e3() -> None:
    """The worked example in the parent spec's tab document section."""
    assert pitch_of(2, 2, STANDARD_TUNING) == 52


def test_invariant_holds_across_the_whole_neck() -> None:
    """Exhaustive rather than randomised: 6 x 25 cases is cheap and total.

    Hypothesis would add a dependency to generate a strictly smaller space.
    """
    for string_index, open_name in enumerate(STANDARD_TUNING):
        open_midi = parse_pitch(open_name)
        for fret in range(MAX_FRET + 1):
            assert pitch_of(string_index, fret, STANDARD_TUNING) == open_midi + fret


def test_pitch_of_rejects_an_out_of_range_string() -> None:
    with pytest.raises(IndexError):
        pitch_of(6, 0, STANDARD_TUNING)


def test_check_invariant_accepts_a_consistent_note() -> None:
    note = Note(id="n_0", t=0.0, dur=0.5, midi=52, string=2, fret=2, confidence=1.0)

    check_invariant(note, STANDARD_TUNING)  # must not raise


def test_check_invariant_rejects_an_inconsistent_note() -> None:
    note = Note(id="n_0", t=0.0, dur=0.5, midi=53, string=2, fret=2, confidence=1.0)

    with pytest.raises(InvariantViolation) as excinfo:
        check_invariant(note, STANDARD_TUNING)

    assert "n_0" in str(excinfo.value)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_fretboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_core.fretboard'`.

- [x] **Step 3: Write the implementation**

Create `packages/core/src/guitarvis_core/fretboard.py`:

```python
"""Pitch arithmetic and the one invariant tablature correctness rests on.

This lives in core, not in the worker, because the mapper, its tests, and any
future editing feature must all ask the same question of the same code.
"""

import re
from collections.abc import Sequence

from guitarvis_core.tabdoc import Note

_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_PITCH_RE = re.compile(r"^([A-G])([#b]?)(-?\d+)$")


class InvariantViolation(Exception):
    """A note's (string, fret, tuning) does not produce its MIDI pitch."""


def parse_pitch(name: str) -> int:
    """Convert a scientific pitch name to a MIDI number. C-1 is 0, A4 is 69."""
    match = _PITCH_RE.match(name)
    if match is None:
        raise ValueError(f"not a scientific pitch name: {name!r}")

    letter, accidental, octave = match.groups()
    semitone = _SEMITONES[letter]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1

    return 12 * (int(octave) + 1) + semitone


def pitch_of(string_index: int, fret: int, tuning: Sequence[str]) -> int:
    """The MIDI pitch produced by fretting `string_index` at `fret`.

    string_index is 0 for the lowest string, matching Note.string.
    """
    if fret < 0:
        raise ValueError(f"fret must not be negative: {fret}")
    if not 0 <= string_index < len(tuning):
        raise IndexError(
            f"string {string_index} does not exist on a {len(tuning)}-string instrument"
        )

    return parse_pitch(tuning[string_index]) + fret


def check_invariant(note: Note, tuning: Sequence[str]) -> None:
    """Raise if a note's fingering does not produce its pitch.

    Call this on every note leaving stage 4. A tab that renders the wrong fret
    is worse than no tab: a beginner cannot tell it from a hard passage.
    """
    produced = pitch_of(note.string, note.fret, tuning)
    if produced != note.midi:
        raise InvariantViolation(
            f"note {note.id}: string {note.string} fret {note.fret} produces "
            f"MIDI {produced}, but the note claims MIDI {note.midi}"
        )
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/core/tests/test_fretboard.py -v`
Expected: PASS, 15 passed (9 parametrised cases plus 6 tests).

- [x] **Step 5: Commit**

```bash
git add packages/core/src/guitarvis_core/fretboard.py packages/core/tests/test_fretboard.py
git commit -m "$(cat <<'EOF'
feat(core): add pitch arithmetic and the fretboard invariant

check_invariant is the assertion that keeps the spec's promise that
tablature correctness does not depend on model accuracy. Exhaustive over
the whole neck rather than randomised: 150 cases is cheap and total, and
it avoids adding a property-testing dependency to the lightest package.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Stage contracts and the failure taxonomy

**Files:**
- Create: `packages/core/src/guitarvis_core/contracts.py`
- Test: `packages/core/tests/test_contracts.py`

**Interfaces:**
- Consumes: `guitarvis_core.tabdoc.{Timing, Chord, Section}`.
- Produces: `NoteEvent`, `TabNote`, `StructureResult` (frozen dataclasses); Protocols `Separator`, `Transcriber`, `StructureAnalyzer`, `FretboardMapper`; `FailureReason` (str Enum); `PipelineError`. Task 7's stage stubs implement the Protocols.

- [x] **Step 1: Write the failing test**

Create `packages/core/tests/test_contracts.py`:

```python
"""Stage interfaces and the failure taxonomy.

The interfaces are narrow on purpose: stage 2 returns (onset, duration, pitch,
confidence) and NOT string/fret, so a guitar-specific model can later implement
the same interface. That is the single upgrade point the staged architecture
exists to protect.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    NoteEvent,
    PipelineError,
    Separator,
    TabNote,
    Transcriber,
)


def test_failure_reasons_match_the_spec_exactly() -> None:
    """The UI maps these to actionable text; the strings are a contract."""
    assert {reason.value for reason in FailureReason} == {
        "unsupported_format",
        "no_guitar_detected",
        "too_long",
        "fetch_failed",
        "internal",
    }


def test_pipeline_error_carries_a_typed_reason() -> None:
    error = PipelineError(FailureReason.NO_GUITAR_DETECTED, "stem was silent")

    assert error.reason is FailureReason.NO_GUITAR_DETECTED
    assert "stem was silent" in str(error)


def test_note_event_is_immutable() -> None:
    event = NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)

    with pytest.raises(AttributeError):
        event.onset = 2.0  # type: ignore[misc]


def test_note_event_carries_no_fingering() -> None:
    """Stage 2 must not know about strings. Stage 4 decides fingering."""
    event = NoteEvent(onset=0.0, duration=0.1, midi=40, confidence=1.0)

    assert not hasattr(event, "string")
    assert not hasattr(event, "fret")


def test_a_fake_separator_satisfies_the_protocol() -> None:
    class FakeSeparator:
        def isolate(self, audio_path: Path) -> Path:
            return audio_path

    assert isinstance(FakeSeparator(), Separator)


def test_a_fake_transcriber_satisfies_the_protocol() -> None:
    class FakeTranscriber:
        def transcribe(self, stem_path: Path) -> list[NoteEvent]:
            return []

    assert isinstance(FakeTranscriber(), Transcriber)


def test_a_fake_mapper_satisfies_the_protocol() -> None:
    class FakeMapper:
        def assign(
            self, notes: Sequence[NoteEvent], tuning: Sequence[str]
        ) -> list[TabNote]:
            return []

    assert isinstance(FakeMapper(), FretboardMapper)


def test_an_unrelated_object_does_not_satisfy_the_protocol() -> None:
    assert not isinstance(object(), Separator)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_core.contracts'`.

- [x] **Step 3: Write the implementation**

Create `packages/core/src/guitarvis_core/contracts.py`:

```python
"""What the pipeline stages promise each other.

Each stage takes and returns plain data, and no stage knows what runs before or
after it. The worker orchestrates. Keeping these declarations in core — rather
than in the worker that implements them — is what lets tests, the api, and a
future desktop build reason about the pipeline without importing torch.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from guitarvis_core.tabdoc import Chord, Section, Timing


class FailureReason(str, Enum):
    """Why a job failed, in terms the UI can turn into actionable text.

    The user needs to know whether to try a different file, a different song,
    or come back later.
    """

    UNSUPPORTED_FORMAT = "unsupported_format"
    NO_GUITAR_DETECTED = "no_guitar_detected"
    TOO_LONG = "too_long"
    FETCH_FAILED = "fetch_failed"
    INTERNAL = "internal"


class PipelineError(Exception):
    """A job failure carrying a typed reason."""

    def __init__(self, reason: FailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class NoteEvent:
    """Stage 2 output: a pitch in time, with no opinion about fingering.

    Deliberately not string/fret, so a guitar-specific transcription model can
    later implement Transcriber without changing anything downstream.
    """

    onset: float
    duration: float
    midi: int
    confidence: float


@dataclass(frozen=True)
class TabNote:
    """Stage 4 output: a NoteEvent placed on the neck."""

    onset: float
    duration: float
    midi: int
    string: int
    fret: int
    confidence: float


@dataclass(frozen=True)
class StructureResult:
    """Stage 3 output. Any field may be empty; the UI omits what is missing."""

    timing: Timing
    chords: list[Chord]
    sections: list[Section]


@runtime_checkable
class Separator(Protocol):
    """Stage 1: isolate the guitar from a mix."""

    def isolate(self, audio_path: Path) -> Path: ...


@runtime_checkable
class Transcriber(Protocol):
    """Stage 2: turn an isolated stem into pitched events."""

    def transcribe(self, stem_path: Path) -> list[NoteEvent]: ...


@runtime_checkable
class StructureAnalyzer(Protocol):
    """Stage 3: beats and chords.

    Takes both the stem and the original mix: drums are the strongest beat cue,
    and the stem has them removed.
    """

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult: ...


@runtime_checkable
class FretboardMapper(Protocol):
    """Stage 4: place pitches on the neck. Deterministic, never learned."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]: ...
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: PASS, 8 passed.

- [x] **Step 5: Run the whole core suite and the type checker**

Run: `uv run pytest packages/core -v && uv run mypy packages/core/src`
Expected: all tests pass; mypy reports no issues.

- [x] **Step 6: Commit**

```bash
git add packages/core/src/guitarvis_core/contracts.py packages/core/tests/test_contracts.py
git commit -m "$(cat <<'EOF'
feat(core): add stage protocols and the failure taxonomy

NoteEvent deliberately carries no string or fret: stage 2 reports pitches
and stage 4 decides fingering, which is the seam a guitar-specific
transcription model slots into later without disturbing anything
downstream.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The api shell and its dependency boundary

**Files:**
- Modify: `apps/api/pyproject.toml` (add fastapi)
- Create: `apps/api/src/guitarvis_api/__init__.py`, `apps/api/src/guitarvis_api/app.py`
- Test: `apps/api/tests/test_boundaries.py`

**Interfaces:**
- Consumes: `guitarvis_core` from Task 2.
- Produces: `guitarvis_api.app:app` (a `FastAPI` instance with no routes); `guitarvis_api.__version__`. Phase 3 adds routes to this object.

- [x] **Step 1: Write the failing test**

Create `apps/api/tests/test_boundaries.py`:

```python
"""api must carry no ML code and no model weights.

The parent spec makes this a scaling property: api stays thin so it can scale
independently of GPU work. A comment saying so is something a tired developer
talks past at 2am, so it is a test instead.

Two checks, because they fail at different times. The AST scan catches a
forbidden import even when the package is not installed, which is the normal
state of this repo. The sys.modules check catches an import smuggled in
through a transitive dependency.
"""

import ast
import subprocess
import sys
from pathlib import Path

FORBIDDEN_ROOTS = {"torch", "demucs", "basic_pitch", "librosa", "numpy"}
API_SOURCE = Path(__file__).resolve().parents[1] / "src"


def imported_roots(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


def test_api_source_imports_nothing_from_the_ml_stack() -> None:
    offenders: dict[str, set[str]] = {}

    for source_file in sorted(API_SOURCE.rglob("*.py")):
        forbidden = imported_roots(source_file) & FORBIDDEN_ROOTS
        if forbidden:
            offenders[str(source_file)] = forbidden

    assert not offenders, (
        f"api must stay free of the ML stack, but found: {offenders}. "
        "That code belongs in apps/worker."
    )


def test_importing_api_loads_no_ml_modules() -> None:
    """Catches an ML module arriving through a transitive dependency."""
    probe = (
        "import sys, guitarvis_api.app;"
        f"leaked = sorted(set(sys.modules) & {FORBIDDEN_ROOTS!r});"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_api pulled in: {result.stdout.strip()}"
    )
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/api/tests/test_boundaries.py -v`
Expected: FAIL — `test_importing_api_loads_no_ml_modules` errors because
`guitarvis_api.app` does not exist yet.

- [x] **Step 3: Add fastapi to the api manifest**

Edit `apps/api/pyproject.toml`, replacing the `dependencies` line:

```toml
dependencies = [
    "guitarvis-core",
    "fastapi>=0.115",
]
```

- [x] **Step 4: Write the api shell**

`apps/api/src/guitarvis_api/__init__.py`:

```python
"""HTTP surface. Thin by design: no ML code, no model weights.

Everything expensive happens in the worker, reachable only through the queue.
See apps/api/tests/test_boundaries.py for the enforcement.
"""

__version__ = "0.1.0"
```

`apps/api/src/guitarvis_api/app.py`:

```python
"""The FastAPI application object.

Routes arrive in phase 3 (003 onwards). The object exists now so that the
dependency boundary is under test from the first commit rather than from the
first endpoint.
"""

from fastapi import FastAPI

app = FastAPI(
    title="GuitarVis API",
    version="0.1.0",
    description="Audio in, tab documents out.",
)
```

- [x] **Step 5: Sync and run the test to verify it passes**

Run: `uv sync && uv run pytest apps/api/tests/test_boundaries.py -v`
Expected: PASS, 2 passed.

- [x] **Step 6: Prove the boundary test actually fires**

This mechanism is worth nothing unless it fails when violated. Temporarily add
a forbidden import to `apps/api/src/guitarvis_api/app.py`:

```python
import numpy  # noqa: F401  — TEMPORARY, remove after verifying
```

Run: `uv run pytest apps/api/tests/test_boundaries.py -v`
Expected: FAIL — `test_api_source_imports_nothing_from_the_ml_stack` reports
`{'.../app.py': {'numpy'}}` with the message "That code belongs in apps/worker."

- [x] **Step 7: Remove the temporary import and confirm green**

```bash
# delete the `import numpy` line from apps/api/src/guitarvis_api/app.py
uv run pytest apps/api/tests/test_boundaries.py -v
git diff --stat   # expect: no change to app.py beyond Step 4's content
```
Expected: PASS, 2 passed.

- [x] **Step 8: Commit**

```bash
git add apps/api uv.lock
git commit -m "$(cat <<'EOF'
feat(api): add the FastAPI shell and enforce its dependency boundary

The spec's "api carries no ML code" is a scaling property, so it is a
test rather than a comment. A static AST scan catches a forbidden import
without the package being installed, and a sys.modules probe catches one
arriving transitively. Verified by adding a violation and watching it
fail.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Worker stage stubs

**Files:**
- Create: `apps/worker/src/guitarvis_worker/__init__.py`
- Create: `apps/worker/src/guitarvis_worker/stages/__init__.py`, `separation.py`, `transcription.py`, `structure.py`, `fretboard.py`
- Test: `apps/worker/tests/test_stages.py`

**Interfaces:**
- Consumes: the Protocols from Task 5.
- Produces: `DemucsSeparator`, `BasicPitchTranscriber`, `LibrosaStructureAnalyzer`, `ViterbiFretboardMapper`. Phase 1 (`003-pipeline-skeleton`) replaces each `NotImplementedError` with a body.

- [x] **Step 1: Write the failing test**

Create `apps/worker/tests/test_stages.py`:

```python
"""Every stage stub satisfies its protocol and refuses to pretend it works.

The classes exist before their bodies so that the shape of the pipeline is
reviewable, and type-checked, before any model is installed. The
NotImplementedError assertions are what stop a stub from being mistaken for a
working stage during phase 1.
"""

from pathlib import Path

import pytest

from guitarvis_core.contracts import (
    FretboardMapper,
    Separator,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_core.tabdoc import STANDARD_TUNING
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber


def test_stages_satisfy_their_protocols() -> None:
    assert isinstance(DemucsSeparator(), Separator)
    assert isinstance(BasicPitchTranscriber(), Transcriber)
    assert isinstance(LibrosaStructureAnalyzer(), StructureAnalyzer)
    assert isinstance(ViterbiFretboardMapper(), FretboardMapper)


def test_separation_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        DemucsSeparator().isolate(Path("song.wav"))


def test_transcription_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        BasicPitchTranscriber().transcribe(Path("stem.wav"))


def test_structure_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        LibrosaStructureAnalyzer().analyze(Path("stem.wav"), Path("mix.wav"))


def test_fretboard_is_not_implemented_yet() -> None:
    """Stage 4 names a different spec: the parent spec's build phase 2 pairs the
    mapper with the evaluation harness that measures it."""
    with pytest.raises(NotImplementedError, match="004-fretboard-mapper"):
        ViterbiFretboardMapper().assign([], STANDARD_TUNING)


def test_stage_modules_do_not_import_the_ml_stack_at_module_level() -> None:
    """Heavy imports belong inside the methods that use them.

    uv sync installs the worker without its ml extra, so a module-level
    `import torch` would break collection of this very test file.
    """
    import guitarvis_worker.stages.separation as separation

    assert separation is not None
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_stages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guitarvis_worker.stages'`.

- [x] **Step 3: Write the worker package docstring**

`apps/worker/src/guitarvis_worker/__init__.py`:

```python
"""The pipeline. The only component that needs torch, a GPU, or weights.

Reachable only through the queue: the worker exposes no HTTP surface, which is
what lets it move to a GPU host, another cloud, or a user's own machine without
an API change.
"""

__version__ = "0.1.0"
```

- [x] **Step 4: Write the stage stubs**

`apps/worker/src/guitarvis_worker/stages/__init__.py`:

```python
"""One module per pipeline stage.

No stage imports another. The worker orchestrates them; they exchange plain
data defined in guitarvis_core.contracts.

Heavy dependencies (torch, demucs, basic_pitch, librosa) are imported inside
methods, never at module level, so that importing a stage does not require the
ml extra to be installed.
"""
```

`separation.py`:

```python
"""Stage 1 — separation. Demucs htdemucs_6s, which has a dedicated guitar stem.

Output is normalised to 44.1kHz mono. When the guitar stem comes back empty or
near-silent — common when a heavily distorted guitar is attributed elsewhere —
the implementation falls back to the 4-stem `other` track and marks the
document with a quality warning. This stage dominates job time.
"""

from pathlib import Path


class DemucsSeparator:
    """Implements guitarvis_core.contracts.Separator."""

    def isolate(self, audio_path: Path) -> Path:
        raise NotImplementedError(
            "Stage 1 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
```

`transcription.py`:

```python
"""Stage 2 — transcription. Starts as basic-pitch: polyphonic, CPU-runnable,
and it emits per-note activation strength that maps to confidence.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from pathlib import Path

from guitarvis_core.contracts import NoteEvent


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber."""

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        raise NotImplementedError(
            "Stage 2 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
```

`structure.py`:

```python
"""Stage 3 — musical structure.

Beat and downbeat tracking run on the original mix, not the guitar stem: drums
are the strongest beat cue and the stem has them removed. Chord detection runs
on the stem via chroma template matching. Section labels are optional; when
unreliable the field stays empty and the UI omits them.
"""

from pathlib import Path

from guitarvis_core.contracts import StructureResult


class LibrosaStructureAnalyzer:
    """Implements guitarvis_core.contracts.StructureAnalyzer."""

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        raise NotImplementedError(
            "Stage 3 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
```

`fretboard.py`:

```python
"""Stage 4 — fretboard assignment. The deterministic core.

Notes within roughly 50ms group into a voicing; each voicing has a set of
playable combinations filtered by physical constraints; a Viterbi pass
minimises total cost, dominated by hand-position movement between consecutive
voicings because real players stay put.

Testable without audio: feed note sequences, assert fingerings. Every note it
emits must satisfy guitarvis_core.fretboard.check_invariant.
"""

from collections.abc import Sequence

from guitarvis_core.contracts import NoteEvent, TabNote


class ViterbiFretboardMapper:
    """Implements guitarvis_core.contracts.FretboardMapper."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        raise NotImplementedError(
            "Stage 4 lands in 004-fretboard-mapper; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
```

Stage 4's message names `004-fretboard-mapper` rather than
`003-pipeline-skeleton`, because the parent spec's build phase 2 pairs the
mapper with the evaluation harness that measures it. Step 1's test already
asserts this.

- [x] **Step 5: Run the test to verify it passes**

Run: `uv sync && uv run pytest apps/worker/tests/test_stages.py -v`
Expected: PASS, 6 passed.

- [x] **Step 6: Commit**

```bash
git add apps/worker
git commit -m "$(cat <<'EOF'
feat(worker): add typed stage stubs for the four pipeline stages

Each stub satisfies its protocol and raises NotImplementedError naming
the spec that will fill it, so the shape of the pipeline is reviewable
and type-checked before any model is installed. Heavy imports stay inside
methods so importing a stage does not require the ml extra.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: The eval package and tracked results

**Files:**
- Create: `apps/eval/src/guitarvis_eval/__init__.py`, `apps/eval/src/guitarvis_eval/__main__.py`
- Create: `eval/results/README.md`
- Test: `apps/eval/tests/test_eval.py`

**Interfaces:**
- Consumes: `guitarvis_core`.
- Produces: `python -m guitarvis_eval` as the entry point Task 11's `make eval` calls.

- [x] **Step 1: Write the failing test**

Create `apps/eval/tests/test_eval.py`:

```python
"""The harness is infrastructure, not a nice-to-have.

Without it, "swap in a better model later" is a wish. With it, it is a
measurement. These tests only hold the shape until phase 2 fills it in — plus
the one rule that must never be relaxed.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_results_directory_is_tracked() -> None:
    """eval/results/ holds the metric history. It must be in git, not ignored."""
    results = REPO_ROOT / "eval" / "results"

    assert results.is_dir()

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(results / "README.md")],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert ignored.returncode != 0, "eval/results/ must never be gitignored"


def test_harness_entry_point_exists_and_reports_its_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "guitarvis_eval"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "004-fretboard-mapper" in result.stderr
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest apps/eval/tests/test_eval.py -v`
Expected: FAIL — `eval/results` does not exist; `python -m guitarvis_eval` has no `__main__`.

- [x] **Step 3: Write the eval package**

`apps/eval/src/guitarvis_eval/__init__.py`:

```python
"""GuitarSet evaluation harness.

Reports note F1 (onset within 50ms plus correct pitch), string-assignment
accuracy, and chord accuracy against ground-truth annotations, written to
eval/results/ so changes are visible over time.

Measured, never gated. This must not be wired into CI pass/fail: a suite that
fails because a model got two percent worse on a Tuesday is a suite people
learn to ignore.
"""

__version__ = "0.1.0"
```

`apps/eval/src/guitarvis_eval/__main__.py`:

```python
"""Entry point for `make eval`.

Deliberately outside `make check`. If you find yourself wiring this into CI,
read the module docstring in __init__.py first.
"""

import sys


def main() -> int:
    print(
        "The evaluation harness lands in 004-fretboard-mapper, alongside the "
        "deterministic stage it measures. See "
        "docs/specs/001-guitarvis-design/spec.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Write `eval/results/README.md`**

```markdown
# Evaluation results

Tracked metric history. Each run of `make eval` writes a dated file here, and
those files are committed, because the point is comparing runs over time.

**This directory is deliberately not gitignored.** It looks generated. It is
not disposable.

Metrics, per the design spec:

- **note F1** — an onset within 50ms with the correct pitch counts as a hit
- **string accuracy** — of correctly-pitched notes, the share placed on the
  right string
- **chord accuracy** — frame-wise agreement with the ground-truth chord

These numbers are measured, never gated. No CI job may read them.
```

- [x] **Step 5: Run the test to verify it passes**

Run: `uv sync && uv run pytest apps/eval/tests/test_eval.py -v`
Expected: PASS, 2 passed.

- [x] **Step 6: Commit**

```bash
git add apps/eval eval
git commit -m "$(cat <<'EOF'
feat(eval): add the harness entry point and tracked results directory

The harness itself lands with the stage it measures. What lands now is
the entry point make eval calls, and a test asserting eval/results/ is
not gitignored — it looks generated, and the whole value is in comparing
runs over time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: The web workspace

**Files:**
- Create: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/vite.config.ts`, `web/eslint.config.js`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: npm scripts `dev`, `build`, `lint`, `typecheck`, `test`, `generate-types`, which Task 11's Makefile calls.

The files are hand-written rather than scaffolded with `npm create vite`, which
prompts interactively and pulls a template that would then need trimming.

- [x] **Step 1: Write `web/package.json`**

```json
{
  "name": "guitarvis-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "generate-types": "node scripts/generate-types.mjs"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@eslint/js": "^10.0.1",
    "@types/node": "^26.6.2",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^6.1.1",
    "eslint": "^10.11.0",
    "json-schema-to-typescript": "^16.0.0",
    "typescript": "^6.0.3",
    "typescript-eslint": "^8.70.1",
    "vite": "^8.3.1",
    "vitest": "^5.0.1"
  }
}
```

React stays at 18 deliberately; React 19 is a separate migration and out of scope
for a bootstrap.

TypeScript is held at 6.x rather than 7.x: TS 7 is the native/Go port, and the
current `typescript-eslint` peer range caps below 6.1. Revisit once
typescript-eslint supports it.

These versions clear `npm audit` completely. An earlier draft of this plan pinned
vite 5 / vitest 2, which carried a critical and a high advisory in dev tooling and
sat three majors behind — worth correcting while the web workspace still contains
one component and no tests.

- [x] **Step 2: Write the TypeScript configuration**

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vitest/globals", "node"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`web/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "skipLibCheck": true
  },
  "include": ["vite.config.ts"]
}
```

Note the absence of `noEmit`. A composite project may not disable emit —
TypeScript rejects the combination with TS6310, "Referenced project may not
disable emit." This matches how Vite's own React+TS template writes the file.

- [x] **Step 3: Write `web/vite.config.ts`**

```ts
// defineConfig comes from vitest/config, not vite: the vite one does not type
// the `test` block, and tsc would reject it.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "node",
  },
});
```

- [x] **Step 4: Write `web/eslint.config.js`**

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/types/tabDocument.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
```

The generated types file is excluded: it is regenerated by `make schema` and
hand-editing it is the mistake the drift check exists to catch.

- [x] **Step 5: Write the application shell**

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>GuitarVis</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("#root is missing from index.html");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`web/src/App.tsx`:

```tsx
/**
 * The client shell.
 *
 * The three synced views arrive in later specs. When they do, each one
 * subscribes to (tabDocument, currentTime) and holds no playback state of its
 * own: a PlaybackEngine owns the audio element and is the sole source of truth
 * for current time.
 */
export function App() {
  return (
    <main>
      <h1>GuitarVis</h1>
      <p>Pipeline first. Views land in a later spec.</p>
    </main>
  );
}
```

- [x] **Step 6: Install and generate the lockfile**

```bash
cd web && npm install && cd ..
```
Expected: `web/package-lock.json` is created. It must be committed — Task 11's
`make install` runs `npm ci`, which requires it.

- [x] **Step 7: Verify the toolchain boots**

```bash
cd web
npx tsc --noEmit
npx eslint .
npx vitest run --passWithNoTests
cd ..
```
Expected: all three exit 0. `--passWithNoTests` is a one-off for this task;
Task 10 adds the first real test and the Makefile never uses the flag.

- [x] **Step 8: Commit**

```bash
git add web
git commit -m "$(cat <<'EOF'
feat(web): add the Vite + React + TypeScript workspace

Hand-written rather than scaffolded, so nothing arrives that has to be
trimmed. ESLint ignores src/types/tabDocument.ts because that file is
generated and hand-editing it is exactly what the drift check exists to
catch.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Schema generation and the drift check

**Files:**
- Create: `packages/core/src/guitarvis_core/schema_export.py`
- Create: `web/scripts/generate-types.mjs`
- Create: `schema/tab-document.schema.json` (generated)
- Create: `web/src/types/tabDocument.ts` (generated)
- Test: `packages/core/tests/test_schema_export.py`, `web/src/types/tabDocument.test.ts`

**Interfaces:**
- Consumes: `TabDocument` from Task 3; the fixture at `packages/core/tests/fixtures/minimal.tabdoc.json`; the web workspace from Task 9.
- Produces: `python -m guitarvis_core.schema_export <path>`; npm script `generate-types`; the exported TypeScript type `TabDocument`. Task 11's `make schema` and `make schema-check` call both.

- [x] **Step 1: Write the failing Python test**

Create `packages/core/tests/test_schema_export.py`:

```python
"""The JSON Schema is generated, committed, and diff-checked.

Determinism matters more than prettiness here: an unstable key order would make
every regeneration look like a change and train everyone to ignore the diff.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SCHEMA = REPO_ROOT / "schema" / "tab-document.schema.json"


def test_export_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    for target in (first, second):
        subprocess.run(
            [sys.executable, "-m", "guitarvis_core.schema_export", str(target)],
            check=True,
        )

    assert first.read_text() == second.read_text()


def test_committed_schema_is_current(tmp_path: Path) -> None:
    """The same assertion CI makes, available before you push."""
    fresh = tmp_path / "fresh.json"
    subprocess.run(
        [sys.executable, "-m", "guitarvis_core.schema_export", str(fresh)],
        check=True,
    )

    assert COMMITTED_SCHEMA.exists(), "run `make schema` and commit the output"
    assert json.loads(fresh.read_text()) == json.loads(COMMITTED_SCHEMA.read_text()), (
        "schema/tab-document.schema.json is stale; run `make schema`"
    )


def test_schema_describes_the_documented_top_level_fields() -> None:
    schema = json.loads(COMMITTED_SCHEMA.read_text())

    assert set(schema["properties"]) == {
        "schema_version",
        "source",
        "instrument",
        "timing",
        "notes",
        "chords",
        "sections",
    }
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/core/tests/test_schema_export.py -v`
Expected: FAIL — `No module named guitarvis_core.schema_export`.

- [x] **Step 3: Write the exporter**

Create `packages/core/src/guitarvis_core/schema_export.py`:

```python
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
```

- [x] **Step 4: Generate the schema and run the Python test**

```bash
uv run python -m guitarvis_core.schema_export schema/tab-document.schema.json
uv run pytest packages/core/tests/test_schema_export.py -v
```
Expected: PASS, 3 passed. `schema/tab-document.schema.json` now exists.

- [x] **Step 5: Write the TypeScript generator**

Create `web/scripts/generate-types.mjs`:

```js
/**
 * Generate web/src/types/tabDocument.ts from the committed JSON Schema.
 *
 * Both artifacts are committed so a contract change shows up as a diff in
 * review. Run via `make schema`, never by hand.
 */
import { mkdirSync, writeFileSync } from "node:fs";

import { compileFromFile } from "json-schema-to-typescript";

const SCHEMA = "../schema/tab-document.schema.json";
const OUTPUT = "src/types/tabDocument.ts";

const ts = await compileFromFile(SCHEMA, {
  bannerComment:
    "/* GENERATED FILE — do not edit.\n" +
    " * Source: schema/tab-document.schema.json (from packages/core tabdoc.py).\n" +
    " * Regenerate with `make schema`.\n" +
    " */",
  additionalProperties: false,
  style: { singleQuote: false },
});

mkdirSync("src/types", { recursive: true });
writeFileSync(OUTPUT, ts);

console.log(`wrote ${OUTPUT}`);
```

- [x] **Step 6: Write the failing TypeScript test**

Create `web/src/types/tabDocument.test.ts`:

```ts
/**
 * The shared fixture must satisfy the generated type.
 *
 * The CI diff check catches a forgotten regeneration. This catches the failure
 * the diff check cannot see: a generator that is silently emitting the wrong
 * types, where both sides are consistently wrong.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import type { TabDocument } from "./tabDocument";

// Resolved from this file, not from the working directory, so the test does
// not depend on where the runner was invoked.
const FIXTURE = new URL(
  "../../../packages/core/tests/fixtures/minimal.tabdoc.json",
  import.meta.url,
);

function loadFixture(): TabDocument {
  return JSON.parse(readFileSync(FIXTURE, "utf8")) as TabDocument;
}

describe("the tab document contract", () => {
  // Note the optional chaining throughout. Every field carrying a Pydantic
  // default is absent from the schema's `required` list and therefore optional
  // in TypeScript. That is correct — the degradation ladder depends on a
  // document being able to omit whole tracks — and a client must handle it.
  it("accepts the fixture that pytest also validates", () => {
    const doc = loadFixture();

    expect(doc.schema_version).toBe(1);
    expect(doc.instrument.tuning).toEqual(["E2", "A2", "D3", "G3", "B3", "E4"]);
    expect(doc.notes ?? []).toHaveLength(2);
    expect(doc.notes?.[1]?.string).toBe(2);
    expect(doc.notes?.[1]?.fret).toBe(2);
  });

  it("keeps seconds as the authoritative position", () => {
    const doc = loadFixture();

    // Notes carry `t` in seconds. Bars and beats live only in timing.beats.
    expect(doc.notes?.[0]?.t).toBe(0);
    expect(doc.timing.beats?.[0]?.bar).toBe(1);
  });

  it("models an omitted optional track as absent rather than malformed", () => {
    const degraded: TabDocument = { ...loadFixture(), chords: [] };

    expect(degraded.chords).toEqual([]);
  });
});
```

- [x] **Step 7: Run the TypeScript test to verify it fails**

```bash
cd web && npx vitest run; cd ..
```
Expected: FAIL — `Cannot find module "./tabDocument"`; the types are not
generated yet.

- [x] **Step 8: Generate the types and verify the test passes**

```bash
cd web
npm run generate-types
npx tsc --noEmit
npx vitest run
cd ..
```
Expected: `wrote src/types/tabDocument.ts`, then `tsc` exits 0, then 2 tests
pass.

- [x] **Step 9: Prove the drift check fires**

Add a field to `Note` in `packages/core/src/guitarvis_core/tabdoc.py`:

```python
    vibrato: bool = False  # TEMPORARY — remove after verifying the drift check
```

```bash
uv run pytest packages/core/tests/test_schema_export.py::test_committed_schema_is_current -v
```
Expected: FAIL with "schema/tab-document.schema.json is stale; run `make schema`".

- [x] **Step 10: Remove the temporary field and confirm green**

```bash
# delete the `vibrato` line from tabdoc.py
uv run pytest packages/core -v
git diff --stat packages/core/src/guitarvis_core/tabdoc.py   # expect: empty
```
Expected: all core tests pass, and the file is unchanged from Task 3.

- [x] **Step 11: Commit**

```bash
git add packages/core/src/guitarvis_core/schema_export.py \
        packages/core/tests/test_schema_export.py \
        schema web/scripts web/src/types
git commit -m "$(cat <<'EOF'
feat: generate and commit the tab document schema and web types

Pydantic is the source of truth; the JSON Schema and TypeScript types are
generated, committed, and diff-checked, so a contract change is visible in
review and a future iOS client reads language-neutral JSON rather than
Python. The shared fixture is validated by pytest and vitest both, which
catches a generator emitting consistently wrong types.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Makefile and CI

**Files:**
- Create: `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: every package and npm script from Tasks 2–10.
- Produces: `make check` as the single command CI runs and the one contributors are told about.

- [x] **Step 1: Write the `Makefile`**

```makefile
# The command surface. CI runs `make check` and nothing else, so anything that
# must not break belongs behind that target.
#
# `eval` is deliberately absent from `check`. Evaluation is measured, never
# gated: a suite that fails because a model got two percent worse on a Tuesday
# is a suite people learn to ignore.

.DEFAULT_GOAL := help
UV  := uv
NPM := npm --prefix web

# mypy is pointed at the source trees rather than the repo root: with a src
# layout it resolves package names from these directories, and tests stay out
# of the strict contract rules.
PY_SOURCES := packages/core/src apps/api/src apps/worker/src apps/eval/src

.PHONY: help install lint format typecheck test test-py test-web \
        schema schema-check check eval clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies and wire up the git hooks
	$(UV) sync
	$(NPM) ci
	git config core.hooksPath .githooks
	@echo "✓ hooks active — commits on main will be refused"

lint: ## Lint Python and TypeScript
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(NPM) run lint

format: ## Apply Python formatting and import order
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## Type-check Python and TypeScript
	$(UV) run mypy $(PY_SOURCES)
	$(NPM) run typecheck

test: test-py test-web ## Run every test

test-py:
	$(UV) run pytest

test-web:
	$(NPM) run test

schema: ## Regenerate the tab document schema and the web types
	$(UV) run python -m guitarvis_core.schema_export schema/tab-document.schema.json
	$(NPM) run generate-types

schema-check: schema ## Fail if the committed contract artifacts are stale
	@git diff --exit-code -- schema web/src/types || { \
	  echo ""; \
	  echo "✗ Contract artifacts are stale."; \
	  echo "  tabdoc.py changed without regenerating. Commit the diff above."; \
	  exit 1; \
	}

check: lint typecheck test schema-check ## Everything CI runs

eval: ## GuitarSet evaluation. Measured, never gated — not part of `check`.
	$(UV) run python -m guitarvis_eval

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .venv web/node_modules web/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

- [x] **Step 2: Verify `make check` passes on the current tree**

Run: `make check`
Expected: ruff clean, mypy clean, pytest green, vitest green, and
`schema-check` producing no diff. If ruff reports formatting issues, run
`make format`, re-run `make check`, and include the formatting in this task's
commit.

- [x] **Step 3: Verify `eval` is unreachable from `check`**

Run: `make -n check | grep -c guitarvis_eval`
Expected: `0`. The separation is the measured-not-gated rule expressed in the
build system, so wiring evaluation into CI would take an edit someone has to
justify.

- [x] **Step 4: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json

      - name: Install dependencies
        run: make install

      # CPU only. The worker's ml extra is never installed here, so no model
      # weights are downloaded and no GPU is required.
      - name: Check
        run: make check
```

- [x] **Step 5: Commit**

```bash
git add Makefile .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
build: add the Makefile command surface and CI

make check is the one command CI runs and the one contributors are told
about. make eval sits outside it on purpose: evaluation is measured, not
gated, and keeping the separation in the build system means wiring it
into CI takes an edit someone has to justify.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: README, CONTRIBUTING, CONVENTIONS, CLAUDE.md

**Files:**
- Modify: `README.md`
- Create: `CONTRIBUTING.md`, `CLAUDE.md`, `docs/CONVENTIONS.md`

**Interfaces:**
- Consumes: the command surface from Task 11 — every command named here must exist.
- Produces: the four documents later specs extend rather than replace.

- [x] **Step 1: Write `README.md`**

```markdown
# GuitarVis

Takes a recording of a song, isolates the guitar, transcribes what it plays,
and renders the result as tablature you can play along with — in three synced
views: scrolling tab, a 2D fretboard, and a 3D guitar.

**Status: pre-implementation.** The repository is bootstrapped and the design
is settled; phase 1 of 6 is next. There is nothing to run yet beyond the test
suite.

## How it works

```
upload ──▶ api ──▶ [jobs] ──▶ worker
                                │ separation      (progress 0–40%)
                                │ transcription   (40–65%)
                                │ structure       (65–80%)
                                │ fretboard       (80–100%)
                                ▼
                        tab document ──▶ api ──▶ web
```

Four independent stages, each behind a narrow interface. The last of them —
placing pitches on the neck — is deterministic code rather than a model, so
tablature correctness does not depend on transcription accuracy.

Everything the clients render is one JSON **tab document**, defined once in
`packages/core` and published as a JSON Schema in `schema/`. A future iOS or
desktop client reimplements rendering and nothing else.

## Honest limitations

Polyphonic guitar transcription with string and fret assignment is not a solved
problem. Expect roughly **70–85% note accuracy on clean recordings, and worse
on dense mixes.**

The design answers this rather than hoping it away: confidence is a first-class
field on every note and chord, low-confidence passages render de-emphasised or
fall back to chord symbols, and a stage that fails omits its track instead of
failing the job. A beginner cannot tell a wrong tab from a hard passage, and
will conclude they are bad at guitar — so silent wrongness is the failure mode
the whole design is shaped against.

v1 has no editing, so transcription errors cannot be corrected by hand.

## Layout

| Path | What lives there |
|---|---|
| `packages/core` | The tab document, the stage interfaces, the fretboard invariant |
| `apps/api` | FastAPI. Thin; no ML code, enforced by test |
| `apps/worker` | The pipeline. The only component that needs torch |
| `apps/eval` | GuitarSet evaluation harness |
| `web` | React + TypeScript client |
| `schema` | Generated JSON Schema — the cross-language contract |
| `docs/specs` | One numbered folder per feature: `spec.md`, `plan.md` |
| `docs/decisions` | ADRs, and the backlog of decisions still open |

## Getting started

```bash
make install   # uv sync, npm ci, and wire up the git hooks
make check     # lint, typecheck, test, and the contract drift check
make help      # every command
```

Requires Python 3.12+, Node 22+, and [uv](https://docs.astral.sh/uv/).

## Documentation

- [Design spec](docs/specs/001-guitarvis-design/spec.md) — the whole system,
  including the thirteen decisions still open
- [Contributing](CONTRIBUTING.md) — workflow and commands
- [Conventions](docs/CONVENTIONS.md) — how the code is written
- [Decisions](docs/decisions/) — what was chosen and why

## Licence

MIT. See [LICENSE](LICENSE).
```

- [x] **Step 2: Write `CONTRIBUTING.md`**

```markdown
# Contributing

## Setup

```bash
make install
make check
```

Requires Python 3.12+, Node 22+, and [uv](https://docs.astral.sh/uv/)
(`curl -LsSf https://astral.sh/uv/install.sh | sh`).

`make install` also runs `git config core.hooksPath .githooks`, which activates
the hook that refuses commits on `main`.

## Commands

| Command | What it does |
|---|---|
| `make install` | Dependencies and git hooks |
| `make lint` | ruff and ESLint |
| `make format` | Apply Python formatting and import order |
| `make typecheck` | mypy and `tsc --noEmit` |
| `make test` | pytest and vitest |
| `make schema` | Regenerate the JSON Schema and the web types |
| `make check` | Everything CI runs |
| `make eval` | GuitarSet evaluation — measured, never gated |

The worker's ML dependencies are an optional extra and are not installed by
default. When you need them: `uv sync --extra ml`.

## Every change starts with a spec

Work is organised as numbered spec folders under `docs/specs/`:

```
docs/specs/
├── 001-guitarvis-design/      spec.md
├── 002-repo-bootstrap/        spec.md  plan.md
└── 003-pipeline-skeleton/     spec.md  plan.md
```

Folder names are `NNN-short-name`: three digits, zero-padded, monotonic, never
reused, then one to three kebab-case words. `spec.md` is the design, `plan.md`
is the implementation plan, and companion notes stay in the same folder.

**The branch name is the folder name.** Work for `003-pipeline-skeleton`
happens on a branch called `003-pipeline-skeleton`. One lookup, and `git
branch` reads as a list of specs in flight.

`main` is never committed to directly. The pre-commit hook enforces it;
`--no-verify` exists for the genuine exception, which is rarer than it feels.

Open a pull request using the template, which requires a link to the spec.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `build:`, with an
optional scope such as `feat(core):`.

Write the body to explain *why*, not *what* — the diff already says what.

## Where things go

| Change | Where |
|---|---|
| Tab document field | `packages/core/.../tabdoc.py`, then `make schema` |
| Pipeline stage | `apps/worker/src/guitarvis_worker/stages/` |
| Stage interface | `packages/core/.../contracts.py` |
| HTTP endpoint | `apps/api/` — no ML imports, the test will catch you |
| Client view | `web/src/` |
| Evaluation metric | `apps/eval/` |

## Before you open a PR

- `make check` passes
- If you touched `tabdoc.py`, you ran `make schema` and committed the result
- The plan's checkboxes reflect reality
```

- [x] **Step 3: Write `docs/CONVENTIONS.md`**

```markdown
# Conventions

Rules that outlive any one change. The reasoning lives in
[the design spec](specs/001-guitarvis-design/spec.md); this is the short form.

## Python

- `src/` layout in every package. Distribution names use hyphens
  (`guitarvis-core`), import names use underscores (`guitarvis_core`).
- **mypy is strict on the contract modules** — `tabdoc`, `contracts`,
  `fretboard` — and lenient elsewhere. Exploratory pipeline code should not be
  fought with type errors; the contract should.
- **Failures carry a typed reason**, never a bare string. `FailureReason` in
  `guitarvis_core.contracts` is the closed set, and the UI maps each member to
  actionable text. Adding a reason means updating that mapping.
- **A stage never imports another stage.** Stages take and return plain data;
  the worker orchestrates. If a stage needs to know what ran before it, the
  interface is wrong.
- **Heavy imports go inside the method that uses them**, never at module level.
  Importing a stage must not require the `ml` extra.
- `apps/api` imports nothing from the ML stack. This is enforced by
  `apps/api/tests/test_boundaries.py`, not by good intentions.

## TypeScript

- **One clock.** A `PlaybackEngine` owns the audio element and is the sole
  source of truth for current time.
- **Views subscribe to `(tabDocument, currentTime)` and hold no playback
  state.** They never communicate with sibling views. A fourth view should be a
  new subscriber, not a refactor.
- **Confidence rendering lives in one shared function**, used identically by
  all three views. The rule must not drift between them.
- `web/src/types/tabDocument.ts` is generated. Never hand-edit it; run
  `make schema`.
- Canvas for the tab strip, SVG for the 2D fretboard. A four-minute song has
  thousands of notes, and SVG nodes at that count stutter.

## The tab document

- **Seconds are authoritative.** Every note carries a wall-clock onset. Bars
  and beats live only in `timing.beats`. Never store a note position as
  bar/beat — a tempo error would then desynchronise playback from audio, which
  is the one thing a play-along app must never do.
- **The note list is flat.** Measures are computed from the beat grid at render
  time.
- **Optional tracks are omittable.** A job that loses chord detection omits the
  chord track; it does not send empty scaffolding, and the client renders the
  fallback.
- Changing a field means running `make schema` and committing both generated
  artifacts. Adding an optional field is additive; removing or retyping one
  requires bumping `SCHEMA_VERSION`.

## Testing

**Correctness is tested; quality is measured.** Confusing the two produces a CI
suite that fails because a model got two percent worse on a Tuesday, and a
suite people learn to ignore.

- **Tested, and gating CI:** the fretboard mapper and its invariant, tab
  document schema validation and round-tripping, the degradation ladder,
  playback sync against a fake clock, pipeline integration with separation
  stubbed. All deterministic, all CPU, no model weights.
- **Measured, never gating:** the GuitarSet harness, run via `make eval`,
  writing to `eval/results/`.

No CI job may read `eval/results/`.

## Mechanisms over notes

Where a rule matters, it is enforced by something that fails:

| Rule | Mechanism |
|---|---|
| No ML in `api` | `apps/api/tests/test_boundaries.py` |
| No commits on `main` | `.githooks/pre-commit` |
| Generated artifacts stay current | `make schema-check` in CI |
| Every note's fingering matches its pitch | `guitarvis_core.fretboard.check_invariant` |
| Evaluation never gates | `make eval` is unreachable from `make check` |

Adding a rule to this document without a mechanism is worth doing, but expect
it to decay.
```

- [x] **Step 4: Write `CLAUDE.md`**

```markdown
# GuitarVis — working notes for Claude

Audio in, guitar tablature out, rendered in three synced views. Four pipeline
stages — separation, transcription, structure, fretboard assignment — each
behind a narrow interface. The client and the pipeline meet at one JSON tab
document.

Start here: [`docs/specs/001-guitarvis-design/spec.md`](docs/specs/001-guitarvis-design/spec.md).

## Commands

`make install` · `make check` · `make test` · `make schema` · `make eval` ·
`make help`

`make check` is what CI runs. Run it before claiming anything works.

## Invariants — do not violate these

1. `pitch_of(string, fret, tuning) == note.midi`, for every note, always.
2. **Seconds are authoritative.** Never store a note position as bar/beat.
3. `apps/api` must not import torch, demucs, basic_pitch, librosa, or numpy.
4. **Evaluation never gates CI.** `make eval` stays out of `make check`.
5. After changing `tabdoc.py`, run `make schema` and commit both generated
   artifacts.
6. **Never commit to `main`.** Branch, then open a PR.

## Workflow

Every change starts with a spec folder: `docs/specs/NNN-short-name/` holding
`spec.md` and `plan.md`. The branch is named after the folder. This overrides
any default that would write specs elsewhere — see
`.claude/skills/spec-workflow/`.

## Skills in this repo

| Skill | Read it when |
|---|---|
| `spec-workflow` | Starting any change; writing a spec or plan |
| `tab-document` | Touching `tabdoc.py`, `schema/`, or the generated types |
| `pipeline-stage` | Adding or changing a stage in `apps/worker` |
| `eval-harness` | Running or interpreting the evaluation |

## Build phases

1. Pipeline skeleton (CLI, no UI) ← **next**
2. Fretboard mapper and evaluation harness
3. API and job queue
4. Web client: tab view and sync
5. 2D fretboard, then 3D guitar
6. URL ingestion

Phases 1–2 hold the technical risk. The rest is conventional work.

## Things that will bite you

- The worker's ML dependencies are an optional extra. `uv sync --extra ml`.
- `web/src/types/tabDocument.ts` is generated. Editing it by hand fails CI.
- Transcription accuracy is 70–85% at best. Degrade, never fail: a broken stage
  omits its track and the job continues. Only "no usable guitar audio" fails a
  job outright.
```

- [x] **Step 5: Verify every command the docs name actually exists**

```bash
for target in install lint format typecheck test schema schema-check check eval help; do
  make -n "$target" >/dev/null 2>&1 && echo "ok   $target" || echo "MISSING $target"
done
```
Expected: `ok` for all ten. A document promising a command that does not exist
is worse than no document.

- [x] **Step 6: Commit**

```bash
git add README.md CONTRIBUTING.md CLAUDE.md docs/CONVENTIONS.md
git commit -m "$(cat <<'EOF'
docs: add README, CONTRIBUTING, CONVENTIONS, and CLAUDE.md

Four audiences, four documents, no overlap: the stranger, the operator,
the code author, the agent. The README states the 70-85% accuracy ceiling
next to the description rather than burying it, because the design is
shaped around that number rather than hoping past it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Architecture decision records

**Files:**
- Create: `docs/decisions/README.md`, `docs/decisions/template.md`
- Create: `docs/decisions/0001-staged-pipeline.md` … `0005-uv-workspace-monorepo.md`

**Interfaces:**
- Consumes: the parent spec, which each ADR links rather than restates.
- Produces: the numbering pattern and the open-decision backlog later specs add to.

- [x] **Step 1: Write `docs/decisions/template.md`**

```markdown
# NNNN. Title

**Status:** Proposed | Accepted | Superseded by [NNNN](NNNN-name.md)
**Date:** YYYY-MM-DD
**Spec:** [NNN-short-name](../specs/NNN-short-name/spec.md#section)

## Context

The forces at play. What made this a decision rather than an obvious step.

## Decision

What was chosen, stated in one or two sentences.

## Consequences

What this makes easy, what it makes hard, and what would force revisiting it.
```

- [x] **Step 2: Write `docs/decisions/0001-staged-pipeline.md`**

```markdown
# 0001. Staged pipeline rather than an end-to-end learned tab model

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#approach)

## Context

Audio to tablature can be one learned model or a sequence of narrow stages. The
end-to-end model has the higher ceiling: it would learn idiomatic fingerings
instead of inferring them. But the available ground truth — GuitarSet, roughly
three hours of clean solo guitar — is thin for generalising to full mixes, and
the approach needs GPU budget and ML depth a solo v1 does not have.

## Decision

Four independent stages — separation, transcription, structure, fretboard
assignment — each behind a narrow interface, each separately testable.
Transcription starts with a general-purpose polyphonic model and is designed to
be swapped once an evaluation harness can prove the swap is an improvement.

## Consequences

Something demoable exists in weeks rather than months, and each stage can be
tested without the others. The transcription interface returns pitches and not
fingerings, which is the seam a guitar-specific model slots into later.

The ceiling is lower: inferred fingerings will sometimes be unidiomatic where a
learned model would be natural. Revisit if transcription quality plateaus below
usefulness and training data has grown.
```

- [x] **Step 3: Write `docs/decisions/0002-seconds-are-authoritative.md`**

```markdown
# 0002. Seconds are authoritative; musical position is derived

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#the-tab-document)

## Context

Every note needs a position. It could be musical (bar 4, beat 2) or wall-clock
(12.84 seconds). Beat tracking is the most error-prone stage in the pipeline.

## Decision

Every note carries a wall-clock onset in seconds. Bars and beats live in a
separate `timing.beats` array mapping time to musical position, and measures
are computed at render time.

## Consequences

A bad beat grid yields ugly bar lines over correctly synced notes — a degraded
experience rather than a useless one. Had positions been musical, a tempo error
would desynchronise playback from audio, which is the one thing a play-along
app must never do.

Rendering must do more work: bar lines require a lookup into the beat grid
rather than being implicit in the data. Accepted.
```

- [x] **Step 4: Write `docs/decisions/0003-deterministic-fretboard.md`**

```markdown
# 0003. Fretboard assignment is deterministic code, not a learned model

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#stage-4--fretboard-assignment)

## Context

A pitch can be played in several places on a guitar neck. Choosing among them
could be learned along with transcription, or computed from physical
constraints.

## Decision

Stage 4 is deterministic code: candidate positions per pitch, filtered by
playability, with a Viterbi pass minimising hand movement between voicings. It
enforces a hard invariant — the pitch implied by `(string, fret, tuning)` must
equal the input MIDI pitch, always.

## Consequences

The step that makes the output *tablature* rather than MIDI is under full
control and can be correct even when the model above it is not. It is testable
without audio: feed note sequences, assert fingerings.

Fingerings will sometimes be mechanically sensible but unidiomatic — correct
notes in a position no guitarist would choose. That is a better failure than a
wrong note, and it is improvable by tuning costs rather than retraining.
```

- [x] **Step 5: Write `docs/decisions/0004-evaluation-is-measured-not-gated.md`**

```markdown
# 0004. Evaluation is measured, never gated

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#testing)

## Context

The GuitarSet harness reports note F1, string accuracy, and chord accuracy.
The obvious move is to put it in CI with a threshold.

## Decision

Evaluation runs on demand via `make eval` and writes to `eval/results/`. It is
unreachable from `make check`, which is the only thing CI runs. No CI job reads
those results.

## Consequences

CI stays fast, deterministic, CPU-only, and trustworthy: a red build always
means something is broken rather than that a model drifted two percent on a
Tuesday. A suite that cries wolf is a suite people learn to ignore, and then a
real failure goes unnoticed.

Nothing automatically stops a quality regression from merging. The tracked
results file makes it visible instead, which requires someone to look.
```

- [x] **Step 6: Write `docs/decisions/0005-uv-workspace-monorepo.md`**

```markdown
# 0005. A uv workspace monorepo with a shared core package

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [002-repo-bootstrap](../specs/002-repo-bootstrap/spec.md#approach)

## Context

The tab document is the contract between the pipeline and every client, present
and future. Where it physically lives determines whether it can drift. The
alternatives were a hand-written JSON Schema as source of truth, or fully
separate services each holding their own copy.

## Decision

A uv workspace with four members. `packages/core` owns the tab document as
Pydantic models — the single source of truth — and both `api` and `worker`
depend on it. The JSON Schema and the TypeScript types are generated from those
models, committed, and diff-checked in CI.

## Consequences

`api` and `worker` cannot hold different ideas of the contract, and a schema
change is visible as a diff in review. A future iOS client reads a
language-neutral JSON Schema from the repository rather than reverse-engineering
Python.

Generated artifacts in git will occasionally produce merge conflicts in
`schema/` and `web/src/types/`. That is a true signal — two branches changed the
contract — and is exactly when a human should look.
```

- [x] **Step 7: Write `docs/decisions/README.md`**

```markdown
# Architecture decisions

One file per decision. Each records what was chosen and what it costs, and
links the spec section that argued it rather than restating it.

New decisions take the next number and start from [`template.md`](template.md).

## Accepted

| # | Decision |
|---|---|
| [0001](0001-staged-pipeline.md) | Staged pipeline rather than an end-to-end learned tab model |
| [0002](0002-seconds-are-authoritative.md) | Seconds are authoritative; musical position is derived |
| [0003](0003-deterministic-fretboard.md) | Fretboard assignment is deterministic code |
| [0004](0004-evaluation-is-measured-not-gated.md) | Evaluation is measured, never gated |
| [0005](0005-uv-workspace-monorepo.md) | A uv workspace monorepo with a shared core package |

## Still open

From the design spec's
[Open decisions](../specs/001-guitarvis-design/spec.md#open-decisions). Each
names the default v1 takes and what would force a different answer. Resolving
one means writing the next ADR.

| Question | v1 default |
|---|---|
| Chord source: detected from the stem, or derived from notes | Detected from the stem |
| Beat tracker: `librosa` or `madmom` | `librosa` — **`madmom`'s non-commercial clause needs an answer before any commercial launch** |
| Tuning detection | Assume standard tuning |
| Capo detection | Assume no capo; schema slot exists |
| Polyphony ceiling in dense strums | Undecided; needs real output to judge |
| Multiple simultaneous guitar parts | Treated as one part; splitting is out of scope |
| Pitch-preserved slow-down | Undecided; the largest client-side risk |
| 3D guitar asset: procedural or sourced glTF | Procedural |
| Simultaneous 2D and 3D views | One at a time |
| Mobile and responsive scope | Desktop viewport only; bears on the planned iOS app |
| Accounts and persistence | Anonymous, session-scoped |
| Hosting and GPU | Undecided; needed before public users |
| Retention policy for stored copyrighted audio | Undecided; **needed before launch** |
```

- [x] **Step 8: Verify every ADR link resolves**

```bash
cd docs/decisions
for f in *.md; do
  grep -oE '\]\(([^)]+\.md)[^)]*\)' "$f" | sed -E 's/^\]\(//; s/#.*//; s/\)$//' | while read -r link; do
    [ -e "$link" ] && echo "ok   $f -> $link" || echo "BROKEN $f -> $link"
  done
done
cd ../..
```
Expected: every line starts with `ok`.

- [x] **Step 9: Commit**

```bash
git add docs/decisions
git commit -m "$(cat <<'EOF'
docs: add ADRs and the open-decision backlog

Five accepted decisions, each linking the spec section that argued it
rather than restating it. The design spec's thirteen unresolved questions
become the backlog, so resolving one has an obvious home and the honest
state of the project is visible rather than implied.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Repo-local skills

**Files:**
- Create: `.claude/skills/spec-workflow/SKILL.md`
- Create: `.claude/skills/tab-document/SKILL.md`
- Create: `.claude/skills/pipeline-stage/SKILL.md`
- Create: `.claude/skills/eval-harness/SKILL.md`

**Interfaces:**
- Consumes: everything above; each skill describes mechanisms that now exist.
- Produces: the guidance a cold session loads before touching the contract, a stage, the evaluation, or a new spec.

- [x] **Step 1: Write `.claude/skills/spec-workflow/SKILL.md`**

```markdown
---
name: spec-workflow
description: Use when starting any change to GuitarVis, writing a spec or an implementation plan, creating a branch, or opening a PR. This repo's spec layout differs from the Superpowers default, and this skill states the difference.
---

# Spec workflow

## Where specs live

```
docs/specs/NNN-short-name/
├── spec.md      the design
├── plan.md      the implementation plan
└── *.md         research notes, eval notes — same folder
```

`NNN` is three digits, zero-padded, monotonic, never reused. The name is one to
three kebab-case words. Every spec folder sits inside `docs/specs/`; none sits
at the top level of `docs/`.

**This overrides the Superpowers default**, which writes to
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and plans to
`docs/superpowers/plans/`. Do not use those paths. The date lives in git.

## The branch is the folder

Work for `003-pipeline-skeleton` happens on a branch called
`003-pipeline-skeleton`. Create it before writing the spec:

```bash
git checkout -b 003-pipeline-skeleton
mkdir -p docs/specs/003-pipeline-skeleton
```

`main` is never committed to directly. `.githooks/pre-commit` refuses it. If
you find yourself reaching for `--no-verify`, you are almost certainly on the
wrong branch rather than facing the genuine exception.

## Finding the next number

```bash
ls docs/specs | sort | tail -1
```

## Opening the PR

Use `.github/pull_request_template.md`. The **Spec:** line is required — a PR
with no spec is the signal that design was skipped.

## What belongs where

`spec.md` argues: purpose, approach, rejected alternatives, consequences,
risks, what is deliberately out of scope. It does not contain step-by-step
instructions.

`plan.md` instructs: tasks with exact file paths, real code, and a test cycle
per task. It does not re-argue the design; it links the spec.

## Build phase order

Recorded in the design spec, and worth respecting — phases 1–2 hold all the
technical risk:

1. Pipeline skeleton · 2. Fretboard mapper and eval harness · 3. API and queue ·
4. Tab view and sync · 5. 2D then 3D fretboard · 6. URL ingestion
```

- [x] **Step 2: Write `.claude/skills/tab-document/SKILL.md`**

```markdown
---
name: tab-document
description: Use when editing packages/core tabdoc.py, the generated schema/ or web/src/types/, or when adding, removing, or retyping any tab document field. The document is the contract between the pipeline and every client, and changing it wrong breaks clients silently.
---

# The tab document

The contract between the pipeline and every client, present and future.
Defined once in `packages/core/src/guitarvis_core/tabdoc.py`.

## After any change, regenerate

```bash
make schema
git add schema web/src/types
```

`schema/tab-document.schema.json` and `web/src/types/tabDocument.ts` are
generated from the Pydantic models and committed. CI runs `make schema` and
fails on any diff. Never hand-edit either file.

## When to bump `SCHEMA_VERSION`

**Additive, no bump:** a new optional field with a default; a widened
constraint; a new enum member that old clients can ignore.

**Breaking, bump required:** removing a field; renaming one; retyping one;
making an optional field required; narrowing a constraint.

Bumping means every client must be updated to accept the new version.
`schema_version` exists so a client can refuse a document it does not
understand rather than render it wrong.

## Rules that are not negotiable

**Seconds are authoritative.** Every note carries `t`, a wall-clock onset. Bars
and beats live only in `timing.beats`. Never add a bar/beat field to `Note`:
beat tracking is the most error-prone stage, and a tempo error would then
desynchronise playback from audio — the one failure a play-along app cannot
have. A bad beat grid should yield ugly bar lines over correctly synced notes.

**The note list stays flat.** Measures are computed from the beat grid at
render time. Nesting notes inside measures would make a timing correction
rewrite the note data and force the fretboard views to parse structure they do
not need.

**The fingering invariant.** `pitch_of(string, fret, tuning) == note.midi`, for
every note, always. `guitarvis_core.fretboard.check_invariant` is the single
implementation; call it rather than reimplementing the arithmetic.

**Confidence is first-class** and required on every note and chord. With no
editing in v1, the interface's honesty depends entirely on this field. A
beginner cannot distinguish a wrong tab from a hard passage, and will conclude
they are bad at guitar.

**Optional tracks are omittable.** `chords`, `sections`, and `timing.beats`
default to empty. A job that loses chord detection omits the track; it does not
send empty scaffolding.

## `extra="forbid"`

Every model refuses unknown fields. That is deliberate: a client sending a
field this version does not know about should be told, not silently ignored.

## Check before you push

```bash
uv run pytest packages/core/tests/test_tabdoc.py packages/core/tests/test_schema_export.py
cd web && npx vitest run; cd ..
```

The shared fixture `packages/core/tests/fixtures/minimal.tabdoc.json` is
validated by pytest and vitest both. If you add a required field, update the
fixture or both suites fail — which is the intended behaviour, not an
inconvenience.
```

- [x] **Step 3: Write `.claude/skills/pipeline-stage/SKILL.md`**

```markdown
---
name: pipeline-stage
description: Use when adding or modifying a pipeline stage in apps/worker, changing a stage interface in guitarvis_core.contracts, or handling pipeline failures. Stages have a narrow contract and a degradation rule that is easy to break by accident.
---

# Pipeline stages

Four stages, each behind a narrow interface, each separately testable.

| Stage | Interface | Progress |
|---|---|---|
| 1 Separation | `Separator.isolate(audio_path) -> Path` | 0–40% |
| 2 Transcription | `Transcriber.transcribe(stem_path) -> list[NoteEvent]` | 40–65% |
| 3 Structure | `StructureAnalyzer.analyze(stem, mix) -> StructureResult` | 65–80% |
| 4 Fretboard | `FretboardMapper.assign(notes, tuning) -> list[TabNote]` | 80–100% |

Protocols live in `packages/core/src/guitarvis_core/contracts.py`.
Implementations live in `apps/worker/src/guitarvis_worker/stages/`.

## The rules

**A stage never imports another stage.** They exchange plain data; the worker
orchestrates. If a stage needs to know what ran before it, the interface is
wrong — fix the interface, do not reach sideways.

**Stage 2 returns pitches, not fingerings.** `NoteEvent` is `(onset, duration,
midi, confidence)` and carries no string or fret. This is the single upgrade
point the staged architecture exists to protect: a guitar-specific model must
be able to implement `Transcriber` without anything downstream changing.

**Heavy imports go inside methods, never at module level.** `uv sync` installs
the worker without its `ml` extra, so a module-level `import torch` breaks test
collection. Use `uv sync --extra ml` when you need the real dependencies.

**Beat tracking runs on the original mix, not the stem.** Drums are the
strongest beat cue and the stem has them removed.

**Stages are idempotent and intermediates are cached by content hash.** A
stage-3 failure must not force re-running separation on retry.

## Degrade, do not fail

Every stage after separation is optional to the core promise. A job fails
outright only when there is no usable guitar audio.

| What broke | What the user gets |
|---|---|
| Beat tracking | Notes still sync to audio; no bar lines, no chord grid |
| Chord detection | Note tab only; chord track hidden |
| Confidence collapses in a passage | That passage shows chord symbols, not fret numbers |
| Guitar stem empty or near-silent | Retry with the 4-stem `other` track; if still empty, fail honestly |

When a stage fails, omit its track from the tab document and continue. Raise
`PipelineError` with a typed `FailureReason` only when the job genuinely cannot
produce anything: `unsupported_format`, `no_guitar_detected`, `too_long`,
`fetch_failed`, `internal`. Those strings are a contract — the UI maps each to
actionable text so the user knows whether to try a different file, a different
song, or come back later.

## Testing a stage

Test contracts and shapes, not musical accuracy. Accuracy is the evaluation
harness's job — see the `eval-harness` skill.

- Stub the expensive stage. A 5-second fixture clip with separation stubbed
  asserts the pipeline's shape without a GPU.
- Stage 4 needs no audio at all: feed note sequences, assert fingerings.
- Every note leaving stage 4 must pass
  `guitarvis_core.fretboard.check_invariant`.

## Adding a stage

1. Define the Protocol and its data types in `contracts.py`.
2. Add a module under `stages/` implementing it.
3. Assert `isinstance(YourStage(), YourProtocol)` in
   `apps/worker/tests/test_stages.py`.
4. Decide what the tab document loses when it fails, and add the row to the
   degradation table above and in the design spec.
```

- [x] **Step 4: Write `.claude/skills/eval-harness/SKILL.md`**

```markdown
---
name: eval-harness
description: Use when running GuitarSet evaluation, interpreting note F1 or string accuracy, comparing runs, or considering adding quality checks to CI. Contains the rule that evaluation must never gate the build.
---

# Evaluation harness

Infrastructure, not a nice-to-have. Without it, "swap in a better model later"
is a wish; with it, it is a measurement.

```bash
make eval
```

Writes to `eval/results/`, which is **tracked in git** — the whole value is in
comparing runs over time. It looks generated. It is not disposable, and it must
never be added to `.gitignore`.

## The rule

**Evaluation is measured, never gated.**

`make eval` is unreachable from `make check`, which is the only thing CI runs.
Do not wire it in. Do not add a threshold job. Do not have a workflow read
`eval/results/`.

A suite that fails because a model got two percent worse on a Tuesday is a
suite people learn to ignore — and then a real failure goes unnoticed.
Correctness is tested and gates the build; quality is measured and does not.
Confusing the two is how a CI suite becomes noise.

If you are about to add a quality check to CI, that is a decision requiring a
new ADR superseding
[`docs/decisions/0004-evaluation-is-measured-not-gated.md`](../../../docs/decisions/0004-evaluation-is-measured-not-gated.md),
not an implementation detail.

## The metrics

| Metric | Meaning |
|---|---|
| **note F1** | An onset within 50ms with the correct pitch counts as a hit |
| **string accuracy** | Of correctly-pitched notes, the share on the right string |
| **chord accuracy** | Frame-wise agreement with the ground-truth chord |

Ground truth is GuitarSet: audio with string and fret annotations, roughly
three hours of clean solo guitar. Held-out set only.

## Reading the numbers honestly

GuitarSet is clean solo guitar. Real material is dense, distorted, and mixed.
Expect production accuracy meaningfully below what the harness reports, and
treat the number as a relative signal between runs rather than a promise to
users. The design spec's 70–85% figure is for clean recordings.

**String accuracy is the one that isolates stage 4.** Note F1 can fall while
string accuracy holds, which means transcription regressed and the
deterministic mapper is fine. The reverse means the mapper's cost weights
changed for the worse.

## Before a model swap

Run the harness on the current model first and commit the result. A swap
without a before-number is not a measurement, and the whole reason the pipeline
is staged is to make that comparison possible.
```

- [x] **Step 5: Verify the skill frontmatter parses and names match directories**

```bash
for f in .claude/skills/*/SKILL.md; do
  dir=$(basename "$(dirname "$f")")
  name=$(awk -F': ' '/^name: /{print $2; exit}' "$f")
  [ "$dir" = "$name" ] && echo "ok   $dir" || echo "MISMATCH dir=$dir name=$name"
  head -1 "$f" | grep -q '^---$' || echo "BAD FRONTMATTER $f"
done
```
Expected: four `ok` lines, no mismatches, no frontmatter warnings.

- [x] **Step 6: Run the full check one last time**

Run: `make check`
Expected: PASS — ruff, mypy, pytest, vitest, and the schema drift check all
green on the complete tree.

- [x] **Step 7: Commit**

```bash
git add .claude/skills
git commit -m "$(cat <<'EOF'
docs: add four repo-local skills

spec-workflow exists because the Superpowers default writes specs to a
different path, and without something that fires during brainstorming the
convention decays in one cold session. The other three carry the rules
whose violations are silent: the contract, the stage degradation
contract, and the prohibition on gating CI with evaluation.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [x] **`make check` passes from a clean clone**

```bash
git clone . /tmp/guitarvis-verify && cd /tmp/guitarvis-verify
git checkout 002-repo-bootstrap
make install && make check
cd - && rm -rf /tmp/guitarvis-verify
```
Expected: green. This catches anything that works only because of state left in
the working directory.

- [x] **Every mechanism has been observed failing**

| Mechanism | Proven in |
|---|---|
| Pre-commit hook refuses `main` | Task 1, Step 9 |
| api dependency boundary | Task 6, Step 6 |
| Schema drift check | Task 10, Step 9 |
| `make eval` unreachable from `make check` | Task 11, Step 3 |

- [x] **Open the pull request**

```bash
gh pr create --title "Bootstrap the repository" --body "$(cat <<'EOF'
**Spec:** docs/specs/002-repo-bootstrap/spec.md

## What changed

A uv workspace monorepo with four Python members and a web workspace, the tab
document as a drift-checked contract, the documentation set, four repo-local
skills, and the spec-driven branch workflow with its enforcing hook.

No application code. `make check` is green on an essentially empty tree, which
is the point: a baseline that passes before there is code is the only way to
know which commit broke it.

## Verification

- [x] `make check` passes locally and from a clean clone
- [x] Each enforcement mechanism was observed failing, not only passing
- [x] Plan checkboxes updated

## Deviations from the spec

The worker's torch/demucs/basic-pitch dependencies became an optional `ml`
extra rather than default dependencies. The spec names them without specifying
install-time grouping; making them opt-in keeps `uv sync` and CI light, which
the spec does require. Phase 1 installs them with `uv sync --extra ml`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
