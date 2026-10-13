# Manual acceptance

**Spec:** [006 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here before the PR is
opened.

## Setup

- Commit: …
- Machine and OS: …
- Audio output: wired / Bluetooth (which one)
- Songs: title, length and format of each

## End to end

- [ ] Upload from the upload page: the progress bar moves, and the page changes to the song
- [ ] The song page names each of the four stages, with a moving percent
- [ ] Re-uploading the same file lands on the same song
- [ ] At 1×, the tab strip stays in sync by ear across the whole song
- [ ] At 0.5×, the same
- [ ] Mix → guitar → mix while playing keeps the position and keeps playing
- [ ] A and B set a loop that repeats; × clears it
- [ ] Playback still works after the presigned URLs expire: leave a song paused for over 15 minutes, then play and seek

Notes: …

## Speed listening test (ADR 0008)

At 0.75× and 0.5×, on a guitar-heavy passage. "Usable" means you could play
along with it. "Unusable" means smeared or watery enough that you could not.

| Browser | Version | 0.75× | 0.5× | Verdict |
|---|---|---|---|---|
| Chrome | … | … | … | … |
| Firefox | … | … | … | … |
| Safari | … | … | … | untested if no Mac is to hand — not assumed to pass |

## Offset between the mix and the stem

After switching, is the guitar early or late against where it was in the
mix? By roughly how much, and on which file format? …

## Output latency

Does the strip visibly lead the audio? Compare wired output with Bluetooth,
if both are to hand. …
