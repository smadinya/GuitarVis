"""Evaluation is measured, never gated — this test keeps that mechanical.

pyproject.toml's `testpaths = ["packages", "apps"]` means `make check`
collects every test under apps/eval/tests/, including this one. That is
exactly how a future contributor could accidentally gate CI on model quality:
add a test here that reads a file out of eval/results/ and asserts something
like `assert note_f1 > 0.7`, and CI now fails when a model gets worse on a
Tuesday, without touching anything that looks like a policy decision — see
docs/decisions/0004-evaluation-is-measured-not-gated.md.

This is a source scan for a *combination*, not a bare substring search on the
path: `test_eval.py`'s existing `test_results_directory_is_tracked` mentions
"eval/results/" legitimately (it only checks the directory exists and is
git-tracked, via `.is_dir()` and `git check-ignore` — it never reads a file's
contents), so flagging any file that merely names the path would be a false
positive on code this repo wants. What actually gates CI on model quality is
reading a *result file's contents* — via `open(`, `.read_text(`,
`.read_bytes(`, or a `json.load`/`json.loads` call — from a file whose source
also references "eval" and "results" together. Both conditions must hold.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
THIS_FILE = Path(__file__).resolve()

# The path, in any of the forms code plausibly spells it: a plain string, a
# Path()-joined pair of segments, or an f-string built from `eval` + `results`.
PATH_REFERENCE = re.compile(r"eval[/\\]results|[\"']eval[\"'].{0,20}[\"']results[\"']")

# Calls that actually pull a file's contents into the process, as opposed to
# checking the directory exists or asking git about it.
CONTENT_READ_CALL = re.compile(r"\bopen\(|\.read_text\(|\.read_bytes\(|json\.loads?\(")


def test_no_eval_test_reads_the_results_directory() -> None:
    scanned_files = [f for f in sorted(TESTS_DIR.rglob("*.py")) if f != THIS_FILE]
    assert scanned_files, "no test files found under apps/eval/tests/ to scan"

    offenders = []
    for source_file in scanned_files:
        source = source_file.read_text()
        if PATH_REFERENCE.search(source) and CONTENT_READ_CALL.search(source):
            offenders.append(str(source_file))

    assert not offenders, (
        "Evaluation is measured, never gated (see "
        "docs/decisions/0004-evaluation-is-measured-not-gated.md). A test "
        "under apps/eval/tests/ must not read the contents of a file out of "
        "eval/results/ and assert on what it finds there — testpaths "
        "includes apps/eval/tests, so such a test runs under `make check` "
        "and would gate CI on model quality without anyone editing anything "
        f"that looks like a decision. Offending files: {offenders}. Adding a "
        "quality gate to CI requires superseding that ADR, not writing a "
        "test."
    )
