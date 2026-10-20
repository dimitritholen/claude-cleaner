import os

import pytest

from claude_cleaner.fsutil import remove


@pytest.mark.skipif(os.name == "nt", reason="POSIX folder modes")
def test_removes_read_only_and_unlistable_folders(tmp_path):
    # Go's module cache: read-only folders; a crashed earlier run left one at 0200.
    top = tmp_path / "mod"
    (top / "pkg" / "deep").mkdir(parents=True)
    (top / "pkg" / "deep" / "f.go").write_text("x")
    (top / "pkg" / "deep").chmod(0o200)
    (top / "pkg").chmod(0o555)
    top.chmod(0o555)
    remove(top)
    assert not top.exists()
