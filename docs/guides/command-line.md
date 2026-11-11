# From the command line

Two ways to use GuitarVis without the browser: run the pipeline on a file
directly, or drive the HTTP api with `curl`. Both need the setup in
[Run it locally](run-locally.md). The CLI needs only the install step; the
api needs the services running too.

## The pipeline on one file

```bash
uv run guitarvis-worker process song.mp3 -o song.json
```

```
  separation       0%
  ...
  fretboard      100%
wrote song.json: 127 note events transcribed, 122 notes placed, 16 chords, 34 beats
warning: 5 notes in chords no hand could play were dropped.
```

No database, queue or storage is involved: one file in, one JSON file out.
It needs ffmpeg and the `ml` extra.

| Option | Does |
|---|---|
| `-o FILE` | Where to write the tab document. Required. |
| `--tuning D2,A2,D3,G3,B3,E4` | The open strings, lowest first. The default is standard tuning, `E2,A2,D3,G3,B3,E4`. |
| `--max-duration SECONDS` | Refuse anything longer. The default is 600 (ten minutes). |
| `--stems-dir DIR` | Keep Demucs's six stems (guitar, bass, drums, vocals, piano, other) in `DIR`, instead of a temporary directory that is deleted. Separation is most of the runtime, so this is handy for inspecting what it produced. |
| `--device cuda` | Run the models on a GPU. *Not verified here: the test machine has no working GPU.* |

Stems are uncompressed WAV, about 1 MB per second of audio for all six.

### What comes out

One JSON **tab document**. It is the only thing the web client reads, and it
is defined once, in
[`packages/core/src/guitarvis_core/tabdoc.py`](../../packages/core/src/guitarvis_core/tabdoc.py),
and published as a JSON Schema in
[`schema/tab-document.schema.json`](../../schema/tab-document.schema.json).
Shortened:

```json
{
  "schema_version": 1,
  "source": { "title": "song", "duration_sec": 24.790188 },
  "instrument": { "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"], "capo": 0, "string_count": 6 },
  "timing": { "tempo_bpm_avg": 95.7, "time_signature": "4/4", "beats": ["…"] },
  "notes": [
    { "id": "n_0000", "t": 5.157, "dur": 0.128, "midi": 43, "string": 0, "fret": 3,
      "confidence": 0.306, "loudness": 0.752, "technique": null }
  ],
  "chords": [ { "t": 0.07, "dur": 1.254, "symbol": "F", "confidence": 0.616 } ],
  "sections": [],
  "warnings": ["5 notes in chords no hand could play were dropped."]
}
```

- Times are in **seconds**. A note's position is never stored as a bar or
  a beat; the beat grid in `timing` is for display.
- `string` counts from 0, the lowest string. A note's `string` and `fret`
  always give back its `midi` pitch under the document's tuning. That is the
  fretboard invariant, checked on every note leaving stage 4
  ([`fretboard.py`](../../packages/core/src/guitarvis_core/fretboard.py)).
- `confidence` runs from 0 to 1. The player fades notes below 0.6, and hides
  runs of three or more notes at 0.5 and below.

### Running the worker

`make worker` runs the same pipeline as a queue worker:

```bash
uv run guitarvis-worker serve            # what make worker runs
uv run guitarvis-worker serve --burst    # finish the queued jobs, then exit
```

## The HTTP api

With `make services`, `make migrate`, `make api` and `make worker` running:

```bash
curl -F file=@song.mp3 localhost:8000/jobs
```

`202 Accepted`, and the job:

```json
{"id":"b7c7c626-…","status":"queued","stage":null,"percent":0,"attempts":0,"title":"song","duration_sec":24.790188,…}
```

The same file again returns `200` with the same job, unless that job failed.

| Request | Returns |
|---|---|
| `GET /jobs/<id>` | `status` (`queued`, `running`, `succeeded`, `failed`), `stage` and `percent` |
| `GET /jobs/<id>/document` | The tab document, once the job has succeeded |
| `GET /jobs/<id>/audio/mix` | A `307` redirect to the original audio in storage; use `curl -L` |
| `GET /jobs/<id>/audio/guitar` | A `307` redirect to the separated guitar stem (WAV) |
| `POST /jobs/from-url` | A job from a YouTube link (below) |
| `GET /features` | `{"url_ingestion":true}` when links are on |
| `GET /health` | Postgres, Redis and storage, each `ok` or not |

```bash
curl localhost:8000/jobs/<id>
curl localhost:8000/jobs/<id>/document -o song.json
curl -L localhost:8000/jobs/<id>/audio/mix -o mix.mp3
curl -L localhost:8000/jobs/<id>/audio/guitar -o guitar.wav
```

From a link, with Deno on the `PATH` of `make api` and `make worker`:

```bash
curl -H 'content-type: application/json' \
  -d '{"url": "https://youtu.be/kPdv44HtEoA"}' localhost:8000/jobs/from-url
```

`202`, titled with the video's title. Any form of the same video's link
returns the same job: `youtu.be/…`, `watch?v=…`, with `&t=` or `&list=`.

The api's request and response shapes are published in
[`schema/api.schema.json`](../../schema/api.schema.json). Uploads and
stems stay in storage until `docker compose down -v`.

Two known quirks:

- A `--max-duration` under 30 seconds reports the limit as "0 minutes":
  [#57](https://github.com/smadinya/GuitarVis/issues/57).
- Demucs is not fully deterministic, so two runs on the same file can differ
  by a note or two.
