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
| `demo.gif` | The 3D view playing 0:10 to 0:20 at 1×. Recorded with Chrome's screencast (`Page.startScreencast`, JPEG quality 92, about 14 fps). Each frame is timed by its arrival on a monotonic clock, then resampled to 12 fps. The encode is `scale=960:-1`, then `palettegen=max_colors=128:stats_mode=diff`, then `paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`. Playwright's `recordVideo` is blurrier, and a screenshot loop manages about 1 fps under SwiftShader. |
| `upload.png` | The upload page, cropped to its content |
| `link.png` | The upload page with the Creative Commons link `https://youtu.be/kPdv44HtEoA` typed in |
| `processing.png` | The song page while the job reads *Isolating the guitar — 24%* |
| `player-3d.png`, `player-fretboard.png`, `player-tab.png` | The whole player, paused at 0:13, in each view |
| `view-3d.png`, `view-fretboard.png` | The `.guitar` element alone, from the same moment |
| `view-tab.png` | The chord lane and the tab strip from the same moment, cropped to the left 645 CSS pixels so the frets still read on a phone |
| `low-confidence.png` | The tab strip at 0:18, where the transcriber is least sure: faded notes, and a hidden passage |
| `transport.png` | The transport with a loop from 0:10 to 0:20, 0.75× and *Guitar only* pressed |
| `failure.png` | The song page of a job that failed with *no usable guitar audio* (ten seconds of silence, uploaded as `Silence.mp3`) |

Gotchas for a retake:

- **Check that the GIF plays.** Decode it and compare frames. A good take
  has nearly every frame distinct, no identical run longer than half a
  second, and the clock on the last frame near 0:20. Single frames can look
  right in a GIF that is frozen for most of its loop.
- **Time frames on a monotonic clock.** The screencast's own timestamps,
  and `Date.now()` under WSL, jumped by about 64 seconds mid-recording.
  Timing on them made the first take repeat a few frames for most of its
  length.
- **Play the window through once before recording.** Right after a seek,
  playback stalled for about a second while the audio buffered.
- **Clear focus before pressing Space.** After seeking by clicking the
  scrubber, call `document.activeElement.blur()` first. Otherwise the
  scrubber shows its keyboard-focus ring.
- **Make every upload byte-distinct.** Uploading the same bytes returns the
  existing job, so a fresh processing screen needs a new file.
  `ffmpeg -i in.mp3 -c copy -metadata comment=retake out.mp3` is enough.

PNGs over 400 KB are quantised to 256 colours; none were this time. The GIF
is about 3.5 MB, and the whole folder about 4.7 MB, against a budget of
10 MB.
