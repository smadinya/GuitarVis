# Manual acceptance

**Spec:** [007 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here before the PR is
opened.

## Setup

- Commit: …
- Machine, OS and browser: …
- Songs: title, length, and the frets they reach

## End to end

- [ ] At 1×, the dots light with the audio and with the tab strip
- [ ] At 0.5×, the same
- [ ] A note plucked again and again on one fret shows each pluck, and the pulse does not distract
- [ ] With only the present on the neck, the tab strip gives enough warning to move the hand
- [ ] A seek, forwards and back, leaves the board right at once
- [ ] An A/B loop leaves the board right each time it restarts
- [ ] A song in open position gets twelve wide frets; a song up the neck fits, with room to spare

If the tab strip's warning was not enough, where it fell short (song, and time): …

Notes: …

## Dark mode and resizing

- [ ] Dark mode: the neck, dots and messages are all readable
- [ ] Light mode: a doubtful note's faded dot still shows a readable name
- [ ] Resizing the window during playback refits the neck, and the dots follow it

Notes: …

## The two string orders

The tab strip puts the highest string on top, and the fretboard the lowest.
Reading the two together, was the reversed order confusing? …
