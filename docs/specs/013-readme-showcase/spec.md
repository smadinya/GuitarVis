# README Showcase — Design

**Date:** 2026-11-10
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Mockup:** the wireframe agreed in the brainstorming session (summarised
under *The page, top to bottom*)

## Purpose

People reach this repository from its owner's GitHub profile, and the ones who
matter most here are recruiters and hiring managers. Today the README is a
thorough engineering document with no images. Its first screen is a
paragraph. A visitor who gives it ten seconds learns that the app exists, not
what it looks like or that it works.

This change makes the repository show what it does. The setup instructions
are also checked: a hiring manager who tries to run the app should get a
running app, and a README that fails on step three undoes the rest.

The README stays honest. The *Honest limitations* section survives, because
admitting a limitation and designing around it is one of the strongest
signals the project sends.

Success conditions:

1. On GitHub at desktop width, the README's first screen shows the name, one
   plain sentence saying what the app does, and an animated demo of the real
   app: a song playing, the tab strip scrolling and the guitar fingering the
   notes in sync.
2. Every image is a capture of the real app at this branch's commit, playing
   the chosen demo song. Nothing is a mockup.
3. The architecture is drawn by GitHub itself from text (Mermaid), so no
   diagram image can drift from the code.
4. Every setup command in the README and the guides has been run, in the order
   written, from a fresh clone on the dev machine (Ubuntu under WSL2). Each
   one worked as written, or the docs were changed until it did. The
   acceptance record says which commands were run and what was changed. The
   one exception is a command that needs hardware the dev machine lacks,
   which today means `--device cuda`. It stays documented, and the doc says
   it was not verified here.
5. The README does not name a licence. It says "See [LICENSE](LICENSE)", so
   changing the licence later means editing that one file.
6. Images added to the repository total under 10 MB.
7. `make check` passes.

## Audience

The primary reader is a recruiter or hiring manager. They are not
necessarily technical, they arrive from the profile, and they scan rather than
read. The secondary reader is an engineer, either on the hiring loop or trying
the app, who scrolls further and wants to know how it is built and how to run
it.

The order of the page follows that: what it does, then what it looks like,
then how it works, then why it is built well, then how to run it.

## The page, top to bottom

1. **First screen.** The name, one sentence ("Turns a song into guitar
   tablature you can play along with" or close to it), a row of badges, and the
   animated demo, about 10 seconds long. The badges are CI status (the
   `CI` workflow) and the stack: Python, TypeScript, React, three.js, PyTorch.
   There is no licence badge.
2. **Feature tour.** Three screenshots side by side, captioned: the tab strip,
   the 2D fretboard and the 3D guitar. Below them, four bullets: upload a file
   or paste a link; the guitar is isolated from the mix; it is transcribed to
   tab; play it back slowed down, looped, or with the guitar alone.
3. **How it works.** A Mermaid flowchart of the path from upload to player:
   client, api, queue, the four worker stages, the tab document, and back to
   the client. It has one short paragraph per stage. The screenshot of the
   processing screen goes here, showing stage progress.
4. **Engineering highlights.** For the technical reader, four or five
   bullets, each linking to evidence in the repo:
   - one typed contract (the tab document) shared by Python and TypeScript,
     generated and checked for drift in CI;
   - the fretboard invariant and deterministic stage 4, so a correct pitch
     always becomes a playable fret;
   - degrade, never fail: a broken stage drops its track and the job
     continues;
   - accuracy measured against GuitarSet and committed to `eval/results/`.
     The latest test-split run (2026-10-20, commit `7c8641c`) is quoted in
     full, with each figure labelled by its mode and file:
     - end to end (full mode), note F1 0.81 and string accuracy 59%;
     - stage 4 alone (oracle mode, true pitches in), string accuracy 67%
       against a 38% lowest-fret baseline.

     Quoting only the flattering one would be the misleading demo this spec
     warns against (my call). The figures are never stated as a promise;
   - a spec-first workflow: every feature has a numbered spec and plan, and
     decisions are recorded as ADRs.

   Counts that go stale on the next commit, such as commit or test totals, are
   left out.
5. **Honest limitations.** Kept, and shortened to its argument. If the demo
   song has low-confidence passages, a screenshot of them rendered faded goes
   here.
6. **Quick start.** The shortest command sequence that gets from clone to the
   app in a browser, with links to the three guides.
7. **Layout, documentation, licence.** The repository table and the
   documentation links as today, and the licence line from success
   condition 5.

## Guides

The README's long setup text moves to `docs/guides/`. Each guide has a
screenshot wherever a reader would otherwise wonder what they should be
seeing.

| Guide | Covers |
|---|---|
| `run-locally.md` | Prerequisites, including ffmpeg, Docker, Deno for links and the `ml` extra. Then services, migrate, api, worker, web, the first upload, and stopping and cleaning up. Common failures and their fixes. |
| `using-the-player.md` | A screenshot tour: uploading or pasting a link, the processing screen, the player, switching between tab, 2D and 3D, speed, looping (including the `[` and `]` keys, which the README omits today), the guitar-only track, confidence shading, and what a failed job looks like. |
| `command-line.md` | `guitarvis-worker process`, its flags (`--device`, `--stems-dir`), what the JSON output is, and the curl walkthrough of the HTTP api. |

`CONTRIBUTING.md` keeps its developer setup. Where verification finds it
wrong, it is fixed too. It is not otherwise rewritten.

## The demo song

The owner offered three of their clips: `tmp/test3.mp3`, `tmp/nutshell.mp3`
and `tmp/mysong.mp3`. They preferred `test3.mp3` because it is short, on
condition that its tab is accurate.

`test3.mp3` was transcribed with the CLI and cross-checked against an
independent pitch track (librosa's pYIN). It plays the six open strings one
at a time. The first five come out right: E, A, D, G and B, on the right
strings. The sixth, the open high E (MIDI 64), comes out an octave high
(MIDI 76, shown at fret 12). The pipeline also adds a spurious re-attack of
the B on the D string at fret 9. Two of seven notes are wrong, and six notes
over fifteen seconds make for an empty tab strip. It is not used as the
demo unless the owner overrides this.

The other two clips play chords, so a single-pitch tracker cannot check them
note by note. A rougher check asks whether each transcribed note's pitch
class is among the three strongest in the separated guitar stem at its onset.
The check cannot see octave errors: `test3.mp3` passes it 7 of 7.

| Clip | Length | Notes placed | Dropped (warnings) | Pitch class plausible |
|---|---|---|---|---|
| `nutshell.mp3` | 25 s | 121 | 6, unplayable chords | 89% |
| `mysong.mp3` | 70 s | 432 | 1 out of range, 9 unplayable | 89%, and 94–96% in 10–40 s |

The owner listened along to both in the running app, which is the only check
here that hears octaves and chord voicings. **They chose `nutshell.mp3`, a
cover.** It is shown under the title *Nutshell (cover)*. Its notes are
densest between 0:10 and 0:20 (82 of 122 in the current pipeline's run), so
that is the GIF's window. It has 32 low-confidence notes across the clip,
which supplies the faded-notes screenshot for *Honest limitations*.

**Acceptance for a demo song:** the owner's ear is the bar. Across the
window shown in the GIF and the screenshots, the owner hears no wrong note
in the tab. The automated checks above are only a pre-filter. The owner
confirms the choice before any capture is taken. If no clip passes, the
builder stops and asks rather than lowering the bar (my call).
Between candidates of equal accuracy, prefer the one whose tab has the most
going on in a ten-second window. Rank `nutshell.mp3` after `mysong.mp3` if both
pass: by its name it is likely a commercial recording, and the owner can
weigh that.

The job title shown in the player is the uploaded filename's stem, so the
song is uploaded under a readable name, not `test3`.

## How the captures are taken

- The full stack runs as the guides describe it: `make services`,
  `make migrate`, `make api`, `make worker`, `make web`. The song is uploaded
  through the browser, so the processing screenshot is real.
- Playwright drives headless Chromium. Screenshots are 2× device scale at a
  1280-pixel-wide viewport and saved as optimised PNG. The demo is recorded
  as video and converted to GIF with ffmpeg, about 960 pixels wide and under
  5 MB.
- Images live in `docs/images/`. `docs/images/README.md` records the song, the
  commit, the viewport and the steps, so anyone can retake them after a UI
  change. The clip itself is not committed (my call): retaking works with any
  song, and only the owner should decide to publish their audio. The README
  says so.
- The capture script stays out of the repository, and no dependency is added
  to `web/`. Retaking the images is rare, and a Playwright dependency would
  be a cost every `npm ci` pays.

## How the setup is verified

The instructions are followed literally from a fresh clone in a scratch
directory, not from the working copy, whose virtualenv and `node_modules`
would hide missing steps. Each command, its result, and any doc change it
forced go in `acceptance.md` in this folder.

Isolation (my call). `compose.yaml` sets no project name, so Docker names
the project after the folder. A clone in a folder called `GuitarVis` would
reuse the owner's dev database and storage. The clone therefore goes in a
folder called `guitarvis-fresh`, which gets its own project and volumes. The
ports are fixed, so the owner's stack is stopped with `docker compose stop`
for the duration and started again afterwards. `stop` keeps its data.
`docker compose down -v` is only ever run in the fresh clone.

Platform (my call). The guides are verified on Ubuntu under WSL2 and say
so, with the date. For other platforms they link to each tool's official
install page rather than give install commands nobody here has run.

Deno is installed at `~/.deno/bin`, which a non-interactive shell does not
have on its `PATH`. If the fresh run trips on that, the guide says how to
put it on the `PATH`.

Links are verified live. The owner approved fetching one YouTube video
during verification: the Creative Commons video `make smoke-url` uses, both
through `make smoke-url` and by pasting it into the running app. This also
closes spec 012's open item, which was that the fetcher has not been run
against live YouTube since its last fix.

Gaps already known from reading, to be confirmed by running:

- The README's requirements line omits ffmpeg. `CONTRIBUTING.md` has it.
- The README omits the `[` and `]` loop keys.
- `uv sync` is exact by default, so re-running `make install` after
  `uv sync --extra ml` may remove the ML extra again. If it does, the guide
  says so.

## Out of scope

- **Changes to the app.** A bug found while verifying is filed as an issue
  and noted, not fixed on this branch. A documented step that fails because
  of such a bug stays in the docs with a short known-issue note linking the
  issue. It is not deleted, since the bug is temporary and the feature is
  real.
- **A hosted live demo.** The pipeline needs PyTorch and minutes of CPU per
  song, and hosting is its own project.
- **The licence itself.** Only the README's wording changes.
- **The GitHub repository's About text, topics and social preview image.**
  These are settings, not files, and changing them is outward-facing. They are
  suggested to the owner at hand-off.
- **Committed capture tooling.** Covered above.

## Rejected alternatives

- **MP4 instead of GIF.** GitHub plays video only when it is uploaded through
  its web editor, which keeps the file outside git. A GIF lives in the repo,
  plays everywhere including the mobile app, and needs no upload step.
- **A diagram drawn as an image.** It drifts from the code with nobody
  noticing. Mermaid is text, renders on GitHub, and changes in the same diff
  as the thing it describes.
- **Keeping all setup in the README.** It pushes the visuals and the
  highlights below a wall of commands that a recruiter will not scroll past.

## Risks

- **Headless WebGL and audio.** The 3D guitar needs WebGL, and playback runs
  on the audio clock. Headless Chromium has SwiftShader and a null audio
  sink, and either may misbehave. The fallbacks are Chromium flags first,
  then a headed browser under WSLg.
- **Stale images.** The UI will change, and the images will not change with
  it. `docs/images/README.md` makes retaking them a recipe rather than
  archaeology.
- **Stale numbers.** Every metric carries its date and results file.
- **A demo that misleads.** Showing a cherry-picked song implies that accuracy
  holds everywhere. The highlights and limitations sections sit on the same
  page and say otherwise.
