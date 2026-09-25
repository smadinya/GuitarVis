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

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1

STANDARD_TUNING = ("E2", "A2", "D3", "G3", "B3", "E4")


class Strict(BaseModel):
    """Base for every document model.

    extra="forbid" is the point. Clients consume tab documents; they do not
    produce them — the pipeline is the only writer. The producer that matters
    here is a future version of this pipeline: a v2 field this version does
    not know about must raise a validation error when an old client parses a
    new document, rather than silently dropping the field and rendering an
    incomplete or wrong tab.
    """

    model_config = ConfigDict(extra="forbid")


class Technique(StrEnum):
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
    # v1 is always capo 0 (see docs/decisions/README.md's open-decision
    # table); when capo detection lands, Note.fret must stay measured from
    # the nut, matching this field, not from the capo. check_invariant
    # below assumes the same thing.
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
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Quality degradation the client must surface. A tab the user cannot "
            "tell is degraded is worse than one labelled as such."
        ),
    )

    # A validator rather than `Literal[SCHEMA_VERSION]` on the field itself:
    # a Literal type changes the generated JSON Schema's `schema_version`
    # property (from a plain integer to a single-value const/enum), which
    # would make `make schema` produce a diff unrelated to any real change.
    # This keeps the schema exactly as it is today and only adds runtime
    # rejection.
    @field_validator("schema_version")
    @classmethod
    def _reject_unknown_schema_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {value!r}: this client understands "
                f"schema_version {SCHEMA_VERSION} only. Refusing to guess at a "
                "document from a different version rather than risk rendering "
                "it wrong."
            )
        return value
