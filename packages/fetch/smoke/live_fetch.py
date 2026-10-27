"""`make smoke-url`: one real lookup and download from YouTube (spec 012).

Never part of `make check`: it depends on YouTube's behaviour that day, and
from a CI runner's datacenter address YouTube usually demands sign-in. The
file is not named test_*.py, so pytest finds it only when given its path;
it also skips unless GUITARVIS_LIVE_FETCH=1. Needs Deno 2.3 or later.

Run it after bumping yt-dlp and before a release. The messages it prints
for a private and a removed video refresh tests/fixtures/youtube-messages.json.
"""

import os
from pathlib import Path

import pytest
from guitarvis_core.audio import probe_duration
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import ChildFetcher, FetchError, check_info
from guitarvis_fetch.links import parse

pytestmark = pytest.mark.skipif(
    os.environ.get("GUITARVIS_LIVE_FETCH") != "1",
    reason="live fetching is opt-in: run `make smoke-url`",
)

# "Elephants Dream - 10 years of open movies", on the Blender Foundation's own
# channel: 37 seconds, Creative Commons Attribution. Its staying online is
# this test's one outside dependency; if it goes, pick another short CC-BY
# video and say so in the commit.
SMOKE_VIDEO = "https://www.youtube.com/watch?v=kPdv44HtEoA"
SMOKE_SECONDS = 37.0
PRIVATE_VIDEO = "https://www.youtube.com/watch?v=yZIXLfi8CZQ"
REMOVED_VIDEO = "https://www.youtube.com/watch?v=Q39EVAstoRM"


def test_a_creative_commons_video_is_looked_up_downloaded_and_probed(
    tmp_path: Path,
) -> None:
    fetcher = ChildFetcher()
    link = parse(SMOKE_VIDEO)

    info = fetcher.lookup(link)
    download = fetcher.download(link, tmp_path, max_bytes=150 * 1024 * 1024)
    probed = probe_duration(download.path)

    print(f"\nlookup: {info}\ndownload: {download}\nffprobe: {probed:.2f} s")
    assert check_info(info) == pytest.approx(SMOKE_SECONDS, abs=1)
    # A diagnostic of what the child reported, not a safety check: the file's
    # containment and size are the worker's UrlSource's to enforce.
    assert download.path.parent == tmp_path
    assert probed == pytest.approx(SMOKE_SECONDS, abs=1)


@pytest.mark.parametrize(
    ("url", "kind"),
    [(PRIVATE_VIDEO, FetchKind.PRIVATE), (REMOVED_VIDEO, FetchKind.UNAVAILABLE)],
)
def test_what_youtube_says_for_a_private_and_a_removed_video(
    url: str, kind: FetchKind
) -> None:
    with pytest.raises(FetchError) as excinfo:
        ChildFetcher().lookup(parse(url))

    error = excinfo.value
    print(f"\n{kind}: ytdlp={error.versions.ytdlp} message={error.detail!r}")
    assert error.kind is kind
