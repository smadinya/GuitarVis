# Images

Captures of the real app, used by the top-level README and the guides in
[`docs/guides/`](../guides/). None is a mockup.

## How these were taken

- **When:** 2026-11-10, on branch `013-readme-showcase` at `8e1cde5`. The
  app's code is unchanged from `main` at `5313f80`.
- **Song:** the owner's cover of *Nutshell*, uploaded through the page as
  `Nutshell (cover).mp3`. The clip is not in the repository. Any song works
  for a retake, though the times below are this song's.
- **Stack:** `make services`, `make migrate`, `make api`, `make worker` and
  `make web`, as in [Run it locally](../guides/run-locally.md).
- **Browser:** headless Chromium driven by Playwright 1.63, with
  `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader` so
  the 3D guitar renders without a GPU.
- **Size:** a 1280-pixel-wide viewport at 2× device scale for every PNG,
  and 1280 × 800 for the player.

| File | What it shows |
|---|---|
| `demo.gif` | The 3D view playing 0:10 to 0:20 at 1×. Recorded with Chrome's screencast (`Page.startScreencast`, JPEG quality 92, about 14 fps), resampled to 12 fps, then `scale=960:-1`, `palettegen=max_colors=128:stats_mode=diff`, `paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`. Playwright's `recordVideo` is blurrier, and a screenshot loop manages about 1 fps under SwiftShader. |
| `upload.png` | The upload page, cropped to its content |
| `link.png` | The upload page with the Creative Commons link `https://youtu.be/kPdv44HtEoA` typed in |
| `processing.png` | The song page while the job reads *Isolating the guitar — 24%* |
| `player-3d.png`, `player-fretboard.png`, `player-tab.png` | The whole player, paused at 0:13, in each view |
| `view-3d.png`, `view-fretboard.png` | The `.guitar` element alone, from the same moment |
| `view-tab.png` | The chord lane and the tab strip alone, from the same moment |
| `low-confidence.png` | The tab strip at 0:18, where the transcriber is least sure: faded notes, and a hidden passage |
| `transport.png` | The transport with a loop from 0:10 to 0:20, 0.75× and *Guitar only* pressed |
| `failure.png` | The song page of a job that failed with *no usable guitar audio* (ten seconds of silence, uploaded as `Silence.mp3`) |

Two gotchas for a retake:

- **Clear focus before pressing Space.** After seeking by clicking the
  scrubber, call `document.activeElement.blur()` first. Otherwise the
  scrubber shows its keyboard-focus ring.
- **Make every upload byte-distinct.** Uploading the same bytes returns the
  existing job, so a fresh processing screen needs a new file.
  `ffmpeg -i in.mp3 -c copy -metadata comment=retake out.mp3` is enough.

PNGs over 400 KB are quantised to 256 colours. None were this time. The
whole folder is about 2 MB, against a budget of 10 MB.
