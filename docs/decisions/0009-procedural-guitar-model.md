# 0009. The guitar is built in code, not loaded from a model file

**Status:** Accepted
**Date:** 2026-10-16
**Spec:** [008-3d-guitar](../specs/008-3d-guitar/spec.md#the-model)

## Context

The design spec left the guitar's source open (decision 8): procedural
geometry, or a sourced glTF model. A glTF would look better for less modelling
work. It also brings licensing and file size to manage.

Its proportions are the larger problem. The guitar draws the notes, so the
dots have to be large enough to name. The spec widens the neck to `WIDE`, 1.7
times a real one, to make room for them. A sourced model has the proportions of
the instrument it was made from, and could not stretch to that width.

## Decision

A procedural neck and headstock, built with plain three.js from
`guitar/geometry.ts`, after [spike.html](../specs/008-3d-guitar/spike.html).

## Consequences

Every dimension is a tested constant, and any song's fret range fits. There is
no asset pipeline and no licence to track. In exchange:

- **The body, bridge and sound hole are not drawn.** The view shows the neck
  and headstock, which is where the hand goes.
- **It looks less finished than a modelled guitar would.**

Revisit if the look matters more than the fit. A sourced model would need the
geometry module's positions mapped onto it, and that mapping is the work to
do.
