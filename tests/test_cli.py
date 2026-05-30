"""CLI smoke tests — every command and sub-app should at least parse `--help`.

The W1 split (M6.5) put each Typer sub-app in its own file. These tests are
the safety net that catches "I renamed a helper but forgot one import" the
moment it happens, instead of at the next dogfood.

Per ADR-0008 §"Update 2026-05-02", the CLI shell discipline now demands that
hand-rolled UI logic with state machinery has tests; this is the CLI half.
We don't test command bodies (those exercise backend functions that already
have their own tests) — we test that every command is *reachable* and that
the option-parsing surface compiles cleanly.
"""

import click
import sys
from types import SimpleNamespace
from typer.main import get_command
from typer.testing import CliRunner

from knowlet.cli.main import DESKTOP_PARENT_PID_ENV, _desktop_parent_pid_from_env, app

runner = CliRunner()


def _help(*argv: str) -> str:
    """Run `knowlet ... --help` and assert it succeeds. Returns stdout."""
    result = runner.invoke(
        app,
        [*argv, "--help"],
        color=False,
        terminal_width=200,
    )
    assert result.exit_code == 0, (
        f"`knowlet {' '.join(argv)} --help` exit={result.exit_code}\nstdout:\n{result.stdout}"
    )
    return result.stdout


def _option_names(*argv: str) -> set[str]:
    command: click.Command = get_command(app)
    for name in argv:
        assert isinstance(command, click.Group)
        command = command.commands[name]
    return {
        option
        for param in command.params
        if isinstance(param, click.Option)
        for option in [*param.opts, *param.secondary_opts]
    }


def test_root_help_lists_all_subcommands():
    out = _help()
    for sub in (
        "vault",
        "config",
        "user",
        "cards",
        "digest",
        "mining",
        "drafts",
        "notes",
        "web",
        "ls",
        "reindex",
        "doctor",
        "chat",
        "check-note",
    ):
        assert sub in out, f"`{sub}` missing from `knowlet --help`"


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "knowlet" in result.stdout


def test_desktop_parent_pid_env_parser(monkeypatch):
    monkeypatch.delenv(DESKTOP_PARENT_PID_ENV, raising=False)
    assert _desktop_parent_pid_from_env() is None

    monkeypatch.setenv(DESKTOP_PARENT_PID_ENV, "4242")
    assert _desktop_parent_pid_from_env() == 4242

    monkeypatch.setenv(DESKTOP_PARENT_PID_ENV, "not-a-pid")
    assert _desktop_parent_pid_from_env() is None

    monkeypatch.setenv(DESKTOP_PARENT_PID_ENV, "0")
    assert _desktop_parent_pid_from_env() is None


# ----------------------------------------------------------------- sub-apps


def test_vault_help():
    out = _help("vault")
    assert "init" in out


def test_config_help():
    out = _help("config")
    for cmd in ("init", "set", "show"):
        assert cmd in out


def test_user_help():
    out = _help("user")
    for cmd in ("show", "edit"):
        assert cmd in out


def test_cards_help():
    out = _help("cards")
    for cmd in ("new", "due", "review", "show"):
        assert cmd in out


def test_mining_help():
    out = _help("mining")
    for cmd in ("list", "add", "edit", "remove", "run", "reset", "run-all"):
        assert cmd in out


def test_digest_help():
    out = _help("digest")
    for cmd in ("list", "add", "enable", "disable", "remove", "run", "discard", "clear"):
        assert cmd in out


def test_drafts_help():
    out = _help("drafts")
    for cmd in ("list", "show", "approve", "commit", "reject", "accept-diff", "reject-diff"):
        assert cmd in out


def test_notes_help():
    out = _help("notes")
    for cmd in ("delete", "restore", "trash"):
        assert cmd in out


# ----------------------------------------------------------------- top-level commands


def test_top_level_command_helps():
    """Each top-level command parses --help."""
    for cmd in ("web", "ls", "reindex", "doctor", "chat", "check-note"):
        _help(cmd)


def test_web_starts_without_llm_api_key(tmp_path, monkeypatch):
    """Opening a desktop vault must not be blocked by missing AI credentials."""
    from knowlet.config import KnowletConfig, save_config
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = ""
    save_config(v.root, cfg)

    called = {}

    def fake_run(app_obj, *, host, port, log_level):
        called["host"] = host
        called["port"] = port
        called["log_level"] = log_level
        called["app"] = app_obj

    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    result = runner.invoke(app, ["web", "--port", "0"])

    assert result.exit_code == 0, result.stdout
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 0


# ----------------------------------------------------------------- second-level


def test_cards_new_options_parse():
    """Verify a sample option-rich command's signature compiles."""
    opts = _option_names("cards", "new")
    assert "--front" in opts
    assert "--back" in opts
    assert "--tags" in opts


def test_mining_add_options_parse():
    opts = _option_names("mining", "add")
    for opt in ("--name", "--rss", "--url", "--every", "--cron", "--prompt", "--output-language"):
        assert opt in opts


def test_digest_add_options_parse():
    opts = _option_names("digest", "add")
    for opt in ("--name", "--rss", "--prompt"):
        assert opt in opts
    assert "--url" not in opts


def test_config_set_takes_two_arguments():
    """`config set <key> <value>` — running with no args should fail with a
    usage error (exit code 2), not a crash."""
    result = runner.invoke(app, ["config", "set"])
    assert result.exit_code != 0


# ----------------------------------------------------------------- vault migrate-filenames (B3)


def test_vault_migrate_filenames_renames_legacy_layout(tmp_path, monkeypatch):
    """A legacy `<id>-<slug>.md` file gets renamed to `<id>.md`."""
    from knowlet.core.note import Note, new_id
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    note = Note(id=new_id(), title="Hello world", body="body text")
    legacy = v.notes_dir / f"{note.id}-{note.slug}.md"
    legacy.write_text(note.to_markdown(), encoding="utf-8")
    assert legacy.exists()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    result = runner.invoke(app, ["vault", "migrate-filenames"])
    assert result.exit_code == 0, result.stdout

    target = v.notes_dir / f"{note.id}.md"
    assert target.exists(), result.stdout
    assert not legacy.exists()


def test_vault_migrate_filenames_idempotent(tmp_path, monkeypatch):
    """Running twice on a vault that's already canonical is a no-op."""
    from knowlet.core.note import Note, new_id
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    note = Note(id=new_id(), title="Already canonical", body="body")
    canonical = v.notes_dir / f"{note.id}.md"
    canonical.write_text(note.to_markdown(), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    r1 = runner.invoke(app, ["vault", "migrate-filenames"])
    r2 = runner.invoke(app, ["vault", "migrate-filenames"])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    assert canonical.exists()
    assert "already at <id>.md" in r2.stdout or "already canonical" in r2.stdout


def test_vault_migrate_filenames_dry_run_does_not_touch_disk(tmp_path, monkeypatch):
    from knowlet.core.note import Note, new_id
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    note = Note(id=new_id(), title="Hello", body="b")
    legacy = v.notes_dir / f"{note.id}-{note.slug}.md"
    legacy.write_text(note.to_markdown(), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    result = runner.invoke(app, ["vault", "migrate-filenames", "--dry-run"])
    assert result.exit_code == 0
    assert legacy.exists(), "dry-run must not rename"
    assert not (v.notes_dir / f"{note.id}.md").exists()
    assert "would rename" in result.stdout
