"""The pre-commit hook only runs if git can execute it.

`make install` wires `core.hooksPath` to `.githooks`, but git silently skips
a hook file that lacks its executable bit — there is no error, the commit
just goes through unguarded, which is exactly the "refuse commits on main"
protection this hook exists to provide. A stray `chmod -x`, or a checkout
tool that does not preserve the bit, would fail this way otherwise.

Lives in packages/core alongside the other repo-wide mechanism tests (see
test_py_typed_markers.py), since this check is not specific to any package.
"""

import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT_HOOK = REPO_ROOT / ".githooks" / "pre-commit"


def test_pre_commit_hook_is_executable() -> None:
    assert PRE_COMMIT_HOOK.is_file(), f"missing hook file: {PRE_COMMIT_HOOK}"

    mode = PRE_COMMIT_HOOK.stat().st_mode
    assert mode & stat.S_IXUSR, (
        f"{PRE_COMMIT_HOOK} is not executable (mode {oct(mode)}). git silently "
        "skips a non-executable hook rather than erroring, so the "
        "refuse-commits-on-main protection would just stop running. Fix with "
        f"`chmod +x {PRE_COMMIT_HOOK.relative_to(REPO_ROOT)}`."
    )


def test_pre_commit_hook_does_not_fail_open_on_an_unborn_branch() -> None:
    """git rev-parse --abbrev-ref HEAD fails (exit 128) before the first
    commit exists; the hook must not swallow that into "not main"."""
    source = PRE_COMMIT_HOOK.read_text()

    assert "git symbolic-ref" in source, (
        "the hook should resolve the branch name with `git symbolic-ref "
        "--short HEAD`, which works on an unborn branch, rather than `git "
        "rev-parse --abbrev-ref HEAD`, which does not"
    )
    # The actual branch-resolving assignment, not just any mention of the
    # phrase — the old failure mode is explained in a comment on purpose.
    assert 'branch="$(git rev-parse' not in source
