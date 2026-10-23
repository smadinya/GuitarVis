# Manual acceptance

**Spec:** [011 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here.

Filled in before the PR is merged.

## Setup

- Commit: …
- Machine and OS: …
- Browsers and versions: …
- Song: title, length, number of sections, and number of chords

Use a song this database has not seen, or delete its job row first. The api
dedupes uploads by content hash and returns any job that has not failed, and
the compose volumes keep old jobs across restarts. To reuse a song, delete its
row from the `jobs` table first, as
[008's record](../008-3d-guitar/acceptance.md#setup) explains (a job's `title`
is the upload's file name without its extension):

```
docker compose exec postgres psql -U guitarvis -d guitarvis -c "DELETE FROM jobs WHERE title = '<song title>'"
```

## End to end

- [ ] The stack runs, and the song plays

Notes: …

## Docked transport

- [ ] The transport is visible at every scroll position at 1440 px wide
- [ ] The transport is visible at every scroll position at 1024 px wide
- [ ] The transport is visible at every scroll position at 800 px wide
- [ ] The transport is visible at every scroll position at a window height of 600 px
- [ ] The transport never covers the tab strip's last row

Notes: …

## Sections

- [ ] A click on a section jumps to it
- [ ] The highlight follows the song

Notes: …

## Chord lane

- [ ] The lane is in step with the tab strip at 1×
- [ ] The lane is in step with the tab strip at 0.5×
- [ ] The current cell stays in view
- [ ] Weak chords are faded

Notes: …

## Scrubber

- [ ] The playhead and the section ticks are drawn
- [ ] The loop is drawn at the same place on the scrubber and on the tab strip
- [ ] The loop is drawn at the same place with B set before A
- [ ] A drag seeks once

Notes: …

## Warnings

- [ ] The warnings show as one line
- [ ] The line expands to the full list

Notes: …

## Tab only

- [ ] No guitar chunk appears in the Network panel
- [ ] The chord lane stays

Notes: …

## Keyboard only

- [ ] From load to a working loop, using Tab, Space, the arrows, `[` and `]`, and the scrubber's Home and End

Notes: …

## Light and dark

Chrome, Firefox, Safari.

- [ ] Chrome, light: the page reads well
- [ ] Chrome, dark: the page reads well
- [ ] Firefox, light: the page reads well
- [ ] Firefox, dark: the page reads well
- [ ] Safari, light: the page reads well
- [ ] Safari, dark: the page reads well

Notes: …

## Free text

Frame rate: browser …, React commits per second while playing: … (Performance panel)

Section labels on this song: good enough / numbered fallback needed, because …

The legend without "Next": missed / not missed, because …
