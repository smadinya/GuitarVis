# README Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A recruiter-first README with real captures of the app, an
architecture diagram GitHub draws itself, and three guides whose every
command was run from a fresh clone.

**Architecture:** Documentation only. Verify the existing setup first, so the
guides are written from what actually happened. Capture images from the dev
stack with a throwaway Playwright script. Write the guides, then the README,
then re-verify the shipped docs from a fresh clone and on GitHub itself.

**Tech Stack:** Markdown and Mermaid (GitHub-rendered), Playwright and
Chromium (captures, throwaway), ffmpeg (GIF), Pillow (PNG quantising, via
`uv run --with`).

**Spec:** [spec.md](spec.md)

## Global Constraints

- No change to app code, `web/` dependencies or `compose.yaml`. A bug found is
  filed as a GitHub issue (`gh issue create --body-file`, never `--body "@file"`).
  The documented step keeps a known-issue note linking that issue.
- The README names no licence: its licence line is exactly
  `See [LICENSE](LICENSE).` There is no licence badge.
- Images go in `docs/images/` and total under 10 MB. `demo.gif` is under
  5 MB and about 960 px wide. PNGs are 2× device scale at a 1280 px wide
  viewport.
- Demo song: `tmp/nutshell.mp3`, uploaded as `Nutshell (cover).mp3`. The GIF
  window is 0:10–0:20.
- The capture script and the clip are not committed.
- Accuracy figures carry their mode, date and file. Full mode
  (`eval/results/2026-10-20-7c8641c-full-test.json`) gives note F1 0.81 and
  string accuracy 59%. Oracle mode
  (`eval/results/2026-10-20-7c8641c-oracle-test.json`) gives 67% against a
  38% lowest-fret baseline.
- No counts that go stale on the next commit (commits, tests, specs).
- Guides say "Verified on Ubuntu under WSL2, 2026-11" and link official
  install pages for other platforms. `--device cuda` is marked "not verified
  here".
- The fresh clone lives at
  `$SCRATCH/guitarvis-fresh`, where `$SCRATCH` is this session's scratchpad.
  The dev stack is stopped with `docker compose stop` while it runs, never
  `down -v`.
- Live YouTube: only the Creative Commons video `make smoke-url` uses
  (`https://youtu.be/kPdv44HtEoA`, as the README's curl example).

## Review Focus

1. **GitHub dark theme.** The diagram and the screenshots stay legible.
   Mermaid gets no hard-coded colours. Task 5 checks a dark-theme render.
2. **Narrow screens and the GitHub mobile view.** The three-screenshot row
   still reads at 390 px. Task 5 renders the page at 390 px.
3. **`make install` run after `uv sync --extra ml`.** If it drops the extra,
   the next `make worker` fails on `import torch`. Task 1 tries it, and
   `run-locally.md` explains it if it happens.
4. **The first worker job looks hung** while Demucs and basic-pitch download
   their weights. Task 1 times the first job from a cold model cache and
   records the download size. `run-locally.md` states both.
5. **Ports 5432, 6379 or 9000 are already taken** by a local Postgres or a
   second stack, and `make services` fails. Task 1 records the exact error by
   starting the fresh stack while the dev stack still runs. The guide's
   troubleshooting quotes it.

---

### Task 1: Verify today's setup from a fresh clone

**Files:**
- Create: `docs/specs/013-readme-showcase/acceptance.md`

**Interfaces:**
- Produces: `acceptance.md` with a `## Pass 1 — today's docs` table. Its
  columns are `Step | Command | Result | Doc change`. It also holds the list
  of doc defects that Tasks 3–4 fix, and any issue numbers filed.

- [x] **Step 1: Start the fresh stack with the dev stack still running**,
  for Review Focus 5. Clone with
  `git clone --branch 013-readme-showcase /home/smadinya/GuitarVis $SCRATCH/guitarvis-fresh`,
  then run `make services` inside the clone. Expected: it fails on a port
  conflict. Record the exact error line.
- [x] **Step 2: Stop the dev stack** with `docker compose stop` in
  `/home/smadinya/GuitarVis`. Then stop the background `make api`,
  `make worker` and `make web` tasks.
- [x] **Step 3: Follow README *Getting started* literally** in the clone:
  `make install`, `make check`. Expected: both pass. The integration tests
  skip without services; record the skip count.
- [x] **Step 4: Follow *Running the pipeline* literally.** Run
  `uv sync --extra ml`, then the `process` command on a copy of
  `tmp/nutshell.mp3`, then the `--stems-dir` variant. Run the first job with
  `TORCH_HOME` and `XDG_CACHE_HOME` pointed at an empty directory, for a cold
  model cache. Record the wall time and that directory's size afterwards
  (Review Focus 4).
- [x] **Step 5: Test the extra-drop.** Run `make install` again, then
  `uv run python -c "import torch"`. Record whether it fails (Review
  Focus 3). Run `uv sync --extra ml` again afterwards.
- [x] **Step 6: Follow *Running the service* literally.** Run
  `make services`, `make migrate`, `make api`, `make worker` and `make web`,
  then each curl in the README in order. Expected: `202` and a job id; the
  job reaches `succeeded`; the document and the audio redirect come back.
  Then run `make check` with `GUITARVIS_REQUIRE_SERVICES=1` and record that
  nothing skips.
- [x] **Step 7: Links, live.** Run `make smoke-url` with Deno on `PATH`
  (`export PATH="$HOME/.deno/bin:$PATH"`), then the README's `from-url` curl.
  Also run the curl once with a worker started without Deno on `PATH`, to
  record what a reader without it sees. Expected: smoke passes, the link job
  succeeds, and the Deno-less job fails as `fetch_failed`.
- [x] **Step 8: Check the README's other claims against the code.** Check
  the keys (`web/src/player/keys.ts`), the progress bands
  (`apps/worker/src/guitarvis_worker/pipeline.py`), the layout table against
  `ls`, and the `curl` paths against `apps/api/src/guitarvis_api/routes.py`.
  Each mismatch is a defect row.
- [x] **Step 9: Tear down the fresh stack** with `docker compose down -v`
  inside `$SCRATCH/guitarvis-fresh` only. Restart the dev stack:
  `docker compose start`, `make api`, `make worker`, `make web`.
- [x] **Step 10: Commit**

```bash
git add docs/specs/013-readme-showcase/
git commit -m "docs(013): spec, plan, and pass 1 of the setup check"
```

### Task 2: Capture the images

**Files:**
- Create: `docs/images/demo.gif`, `docs/images/upload.png`,
  `docs/images/link.png`, `docs/images/processing.png`,
  `docs/images/player-3d.png`, `docs/images/player-fretboard.png`,
  `docs/images/player-tab.png`, `docs/images/low-confidence.png`,
  `docs/images/transport.png`, `docs/images/failure.png`,
  `docs/images/README.md`
- Throwaway: `$SCRATCH/capture/capture.mjs` (not committed)

**Interfaces:**
- Consumes: the dev stack running (Task 1, Step 9).
- Produces: the image files above at those exact names, which Tasks 3–4
  reference.

- [x] **Step 1: Set up Playwright in the scratchpad.** Run `npm init -y` and
  `npm i playwright` in `$SCRATCH/capture`. Use the Chromium already in
  `~/.cache/ms-playwright` if its revision matches; otherwise run
  `npx playwright install chromium`. Smoke test: open
  `http://localhost:5173`, and screenshot it with a non-blank result.
- [x] **Step 2: Upload the demo song through the page.** Make a byte-distinct
  copy with `ffmpeg -c copy -metadata comment="013 demo"` named
  `Nutshell (cover).mp3`, so it is a new job and not the dedupe of an
  earlier one. Upload it with the page's file input. Take `upload.png` before
  choosing the file. Take `processing.png` while the stage label reads
  *Isolating the guitar* or *Transcribing notes*.
- [x] **Step 3: Take the player shots** at `/songs/<id>`, paused at 0:13,
  one per view: `player-3d.png` (3D), `player-fretboard.png` (Fretboard) and
  `player-tab.png` (Tab only). Expected: the 3D shot shows the guitar
  model, not an empty canvas. If WebGL is blank, retry with
  `--enable-unsafe-swiftshader`, then `--use-angle=swiftshader`, then headed
  Chromium under WSLg.
- [x] **Step 4: Take the detail shots.**
  - `low-confidence.png`: an element screenshot of the tab strip at a time
    with notes under 0.5 confidence. The document's notes give the times.
  - `transport.png`: an element screenshot of the transport, with a loop
    set, 0.75× pressed and *Guitar only* pressed.
  - `link.png`: the upload page with the CC video's link pasted.
  - `failure.png`: the song page of a job that fails as *no usable guitar
    audio*. Make the input with
    `ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo -t 10 silence.mp3`,
    named `Silence.mp3`.
- [x] **Step 5: Record `demo.gif`.** Record a video of the 3D view at a
  1280×720 viewport with `recordVideo`, seek to 0:10, press Play, and wait
  10.5 s. Trim to the playing span. Convert with
  `ffmpeg -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"`.
  Expected: the guitar's highlighted notes move and the tab scrolls. File
  size under 5 MB: if over, step fps down to 10, then width to 800.
- [x] **Step 6: Optimise the PNGs and check the budget.** Quantise any PNG
  over 400 KB with Pillow (`uv run --with pillow`, 256-colour adaptive).
  Run `du -cb docs/images/*` and expect a total under 10,000,000.
- [x] **Step 7: Write `docs/images/README.md`.** It gives the song (the
  owner's *Nutshell* cover, not committed; any song works for a retake), the
  commit, the viewport and scale, each image's state (time, view, controls),
  the GIF recipe from Step 5, and the Chromium flags that worked.
- [x] **Step 8: Look at every image** with the Read tool. Expected: no blank
  canvas, no dev overlay, no cursor, no "Untitled". Commit.

```bash
git add docs/images/
git commit -m "docs(013): captures of the app playing the demo song"
```

### Task 3: Write the three guides, and fix CONTRIBUTING

**Files:**
- Create: `docs/guides/run-locally.md`, `docs/guides/using-the-player.md`,
  `docs/guides/command-line.md`
- Modify: `CONTRIBUTING.md`, only for defects listed in `acceptance.md`

**Interfaces:**
- Consumes: Task 1's defect list and recorded outputs, and Task 2's image
  names.
- Produces: the three guide paths, which Task 4 links to.

- [x] **Step 1: `run-locally.md`.** Sections:
  - *What you need*: Python 3.12+, Node 22+, uv, Docker, ffmpeg, and Deno
    2.3+ for links. Each links to its official install page.
  - *Install*: `make install`, then `uv sync --extra ml`, with the
    extra-drop caveat if Task 1 Step 5 showed it.
  - *Start the services*, *Run the app*: three terminals, with a screenshot
    of `upload.png`.
  - *First run*: the weight download size and time from Task 1 Step 4.
  - *Stop and clean up*: `docker compose stop` versus `down -v`, with what
    each keeps.
  - *Troubleshooting*: the port-conflict line from Task 1 Step 1, the Deno
    `PATH` case, and the `make migrate` case from CLAUDE.md.
  - *Verified on*, from the Global Constraints.
- [x] **Step 2: `using-the-player.md`.** A screenshot tour in the order a
  user meets things: upload or link (`upload.png`, `link.png`), processing
  and its five labels (`processing.png`), the three views (the three player
  shots), the transport (`transport.png`), and the keys: Space, ←, →, `[`,
  `]`. It also covers confidence shading (`low-confidence.png`) and a failed
  job (`failure.png`). The label text is copied from
  `web/src/pages/progress.ts` and `web/src/player/*.tsx`, not paraphrased.
- [x] **Step 3: `command-line.md`.** Cover `process` with `-o`, `--device`
  (marked not verified here) and `--stems-dir`. Give a 10-line excerpt of
  the JSON output, taken from Task 1's run, with a pointer to
  `schema/tab-document.schema.json`. Then the curl walkthrough, as verified
  in Task 1 Step 6, including `audio/guitar`.
- [x] **Step 4: Fix `CONTRIBUTING.md`** where `acceptance.md` lists a
  defect that also appears there. Nothing else changes.
- [x] **Step 5: Run the link check.** Write it in `$SCRATCH/linkcheck.py`:
  for every `](path)` and `src="path"` in the changed `.md` files, the
  target exists relative to the file (anchors stripped, `http` skipped).
  Run it with `python3 -I $SCRATCH/linkcheck.py README.md CONTRIBUTING.md docs/guides/*.md docs/images/README.md`.
  Expected: `0 broken`. Commit.

```bash
git add docs/guides/ CONTRIBUTING.md
git commit -m "docs(013): run-locally, using-the-player and command-line guides"
```

### Task 4: Rewrite the README

**Files:**
- Modify: `README.md` (full rewrite, keeping the facts Task 1 confirmed)

**Interfaces:**
- Consumes: Task 2's images, Task 3's guide paths, and the eval figures in
  the Global Constraints.

- [x] **Step 1: Write the sections in the spec's order** (*The page, top to
  bottom*, 1–7).
  - First screen: `# GuitarVis`, the one sentence, and badges. CI is
    `https://github.com/smadinya/GuitarVis/actions/workflows/ci.yml/badge.svg?branch=main`.
    The stack badges are shields.io static badges (Python 3.12, TypeScript,
    React, three.js, PyTorch). Then `demo.gif`.
  - Feature tour: a three-column Markdown table, with the captions in the
    header row and the three player shots in the body.
  - How it works: a Mermaid `flowchart LR` with no style or colour lines,
    then `processing.png`.
  - Highlights: each bullet links its evidence (`packages/core`, the
    `schema-check` target, ADR 0003, ADR 0004, the two result files,
    `docs/specs/`).
  - Limitations: shortened, with `low-confidence.png`.
  - Quick start: `make install`, `uv sync --extra ml`, `make services`,
    `make migrate`, then the three `make` servers. It links all three
    guides.
  - Layout, Documentation and the licence line.
- [x] **Step 2: Run the link check** from Task 3 Step 5 on `README.md`.
  Expected: `0 broken`.
- [x] **Step 3: Grep for forbidden content.**
  `grep -n -i -E 'MIT|commits|[0-9]+ tests' README.md` should find
  nothing. Commit.

```bash
git add README.md
git commit -m "docs(013): a recruiter-first README with the demo up front"
```

### Task 5: Verify the shipped docs

**Files:**
- Modify: `docs/specs/013-readme-showcase/acceptance.md`
  (`## Pass 2 — shipped docs`, `## GitHub render`)
- Modify: `docs/specs/013-readme-showcase/plan.md` (checkboxes)

- [x] **Step 1: Run pass 2.** Make a fresh clone of the branch at HEAD in
  `$SCRATCH/guitarvis-fresh` (delete pass 1's first) and stop the dev stack.
  Then follow `docs/guides/run-locally.md` top to bottom, literally, through
  one upload in the browser. Then run `command-line.md`'s commands. Record
  each in the pass 2 table. Any failure means fixing the guide and
  re-running that step. Tear down as in Task 1 Step 9.
- [x] **Step 2: Run `make check`** in the working copy with
  `GUITARVIS_REQUIRE_SERVICES=1` and the dev stack up. Expected: pass,
  with no skips other than the mir_eval tests.
- [x] **Step 3: Check the GitHub render.** Run
  `git push -u origin 013-readme-showcase`, then use Playwright to open
  `https://github.com/smadinya/GuitarVis/blob/013-readme-showcase/README.md`
  at 1280 px, at 390 px, and at 1280 px with
  `colorScheme: 'dark'`. Expected:
  - at 1280 px, the first screen holds the title, the sentence, the badges
    and the GIF;
  - the Mermaid block renders as an SVG, not as code;
  - the three-shot table reads at 390 px;
  - in dark mode, nothing is dark-on-dark.

  Fix and re-push until all four hold. Record the result and keep the
  screenshots in `$SCRATCH`.
- [x] **Step 4: Tick this plan's checkboxes and commit.**

```bash
git add docs/specs/013-readme-showcase/
git commit -m "docs(013): pass 2 of the setup check and the GitHub render"
```

### Task 6: Review and PR

- [x] **Step 1:** Get a fresh whole-branch review of the docs against the
  spec (superpowers:requesting-code-review), and fix what it finds.
- [x] **Step 2:** Open the PR with `.github/pull_request_template.md`
  (`Spec:` line filled in, `--body-file`). Suggest to the owner, without
  doing it, an About text, topics, and a social preview image cropped from
  `player-3d.png`.
