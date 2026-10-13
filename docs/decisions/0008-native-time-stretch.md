# 0008. Slow-down uses the browser's own time-stretching, on one media element

**Status:** Accepted, provided the listening test in [acceptance.md](../specs/006-tab-view-sync/acceptance.md) passes
**Date:** 2026-10-08
**Spec:** [006-tab-view-sync](../specs/006-tab-view-sync/spec.md#the-audio-path-one-media-element)

## Context

Learners slow a passage down to play along with it, so 0.5× and 0.75× have to
keep the song in tune. The design spec called pitch-preserved slow-down the
largest client-side risk (open decision 7), on the assumption that
`playbackRate` shifts pitch. That is no longer true for media elements:
current browsers time-stretch them natively when `preservesPitch` is set.
Web Audio buffer sources still shift pitch with rate, and would need a phase
vocoder.

## Decision

The `PlaybackEngine` plays through a single `HTMLMediaElement`, with
`preservesPitch` (and `webkitPreservesPitch` where it exists) set, and with
`playbackRate` and `defaultPlaybackRate` set together to 0.5, 0.75 or 1. A
browser that has neither property gets no speed control, rather than audio
at the wrong pitch.

## Consequences

Slow-down costs almost nothing to build, and the clock is the element's own.
In exchange:

- **Switching between the mix and the guitar stem leaves a short gap**, because
  it changes `src`. It is not an instant crossfade.
- **Stretch quality is whatever the browser's algorithm gives.** That is judged
  by ear in acceptance.md, per browser.
- **Output latency is not compensated.**

Revisit if the listening test fails in a browser people need, or if the
toggle gap proves bad. The alternative is Web Audio with both tracks decoded,
behind the same `PlaybackEngine`, so no view changes (see the spec's
*Rejected alternatives*). It brings back the phase vocoder, needs CORS on the
storage bucket, and costs about 170 MB of decoded audio per four-minute song.
