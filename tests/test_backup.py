import json

from claude_cleaner import backup
from claude_cleaner.inventory import scan
from claude_cleaner.reset import Selection, apply_reset, plan_reset


def snapshot(paths):
    files = {}
    for root in (paths.config_dir,):
        for p in sorted(root.rglob("*")):
            if p.is_file() and "local" not in p.relative_to(root).parts:
                files[p.relative_to(root).as_posix()] = p.read_bytes()
    files[".claude.json"] = paths.global_config.read_bytes()
    return files


def test_reset_then_restore_round_trips(home):
    before = snapshot(home)
    archive = apply_reset(plan_reset(scan(home), Selection()))
    assert snapshot(home) != before

    safety = backup.restore(archive, home)
    assert snapshot(home) == before
    assert safety.exists() and safety != archive
    assert backup.list_backups(home)[-1] == safety


def test_backup_skips_local_install_and_has_manifest(home):
    archive = backup.create(home)
    import tarfile
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "manifest.json" in names and "global_config.json" in names
    assert "config_dir/.credentials.json" in names
    assert not any(n.startswith("config_dir/local") for n in names)
    manifest = backup.read_manifest(archive)
    assert manifest["roots"]["config_dir"] == str(home.config_dir)


def test_backups_do_not_overwrite_each_other(home):
    first = backup.create(home)
    second = backup.create(home)
    assert first != second
    assert sorted(backup.list_backups(home)) == sorted([first, second])


def test_backup_is_private(home):
    import os
    import stat
    archive = backup.create(home)
    if os.name != "nt":
        assert stat.S_IMODE(archive.stat().st_mode) == 0o600


def test_reset_reports_progress_to_the_end(home):
    plan = plan_reset(scan(home), Selection())
    seen = []
    apply_reset(plan, progress=lambda step, done, total: seen.append((step, done, total)))
    backups = [s for s in seen if s[0] == "backup"]
    deletes = [s for s in seen if s[0] == "delete"]
    assert backups and backups[-1][1] == backups[-1][2] > 0
    assert deletes[-1] == ("delete", len(plan.delete), len(plan.delete))


def test_backup_archives_unreadable_files_and_keeps_their_mode(home):
    import os
    import stat
    import tarfile
    if os.name == "nt":
        return
    locked = home.config_dir / "jobs" / "x" / "noperm.csv"
    locked.parent.mkdir(parents=True)
    locked.write_text("secret")
    locked.chmod(0)
    archive = backup.create(home)
    assert stat.S_IMODE(locked.stat().st_mode) == 0
    with tarfile.open(archive) as tar:
        member = tar.getmember("config_dir/jobs/x/noperm.csv")
        assert member.mode == 0
        assert tar.extractfile(member).read() == b"secret"
