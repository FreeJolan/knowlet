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

from typer.testing import CliRunner

from knowlet.cli.main import app

runner = CliRunner()


def _help(*argv: str) -> str:
    """Run `knowlet ... --help` and assert it succeeds. Returns stdout."""
    result = runner.invoke(app, [*argv, "--help"])
    assert result.exit_code == 0, (
        f"`knowlet {' '.join(argv)} --help` exit={result.exit_code}\n"
        f"stdout:\n{result.stdout}"
    )
    return result.stdout


def test_root_help_lists_all_subcommands():
    out = _help()
    for sub in ("vault", "config", "user", "cards", "mining", "drafts",
                "web", "ls", "reindex", "doctor", "chat"):
        assert sub in out, f"`{sub}` missing from `knowlet --help`"


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "knowlet" in result.stdout


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


def test_drafts_help():
    out = _help("drafts")
    for cmd in ("list", "show", "approve", "reject"):
        assert cmd in out


# ----------------------------------------------------------------- top-level commands

def test_top_level_command_helps():
    """Each top-level command (web/ls/reindex/doctor/chat) parses --help."""
    for cmd in ("web", "ls", "reindex", "doctor", "chat"):
        _help(cmd)


# ----------------------------------------------------------------- second-level


def test_cards_new_options_parse():
    """Verify a sample option-rich command's signature compiles."""
    out = _help("cards", "new")
    assert "--front" in out
    assert "--back" in out
    assert "--tags" in out


def test_mining_add_options_parse():
    out = _help("mining", "add")
    for opt in ("--name", "--rss", "--url", "--every", "--cron",
                "--prompt", "--output-language"):
        assert opt in out


def test_config_set_takes_two_arguments():
    """`config set <key> <value>` — running with no args should fail with a
    usage error (exit code 2), not a crash."""
    result = runner.invoke(app, ["config", "set"])
    assert result.exit_code != 0
