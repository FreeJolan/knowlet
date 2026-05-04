"""Health checks shared by `knowlet doctor` and the chat REPL `:doctor` slash."""

from __future__ import annotations

from rich.table import Table

from knowlet.cli._common import console
from knowlet.config import KnowletConfig, config_path, save_config
from knowlet.core.embedding import make_backend
from knowlet.core.index import Index, IndexDimensionMismatchError
from knowlet.core.llm import LLMClient
from knowlet.core.tools._registry import default_registry
from knowlet.core.vault import Vault


def run_doctor_checks(
    vault: Vault,
    cfg: KnowletConfig,
    *,
    skip_llm: bool = False,
    skip_embedding: bool = False,
) -> list[tuple[str, str, str]]:
    """Run the full check suite. Returns (status, name, detail) tuples.

    Pure logic — no console output here. Callers render via `print_doctor`.
    """
    results: list[tuple[str, str, str]] = []

    def ok(name: str, detail: str = "") -> None:
        results.append(("ok", name, detail))

    def fail(name: str, detail: str) -> None:
        results.append(("fail", name, detail))

    def warn(name: str, detail: str) -> None:
        results.append(("warn", name, detail))

    ok("vault", str(vault.root))
    ok("config file", str(config_path(vault.root)))
    if cfg.llm.api_key:
        ok("llm.api_key", "set")
    else:
        warn("llm.api_key", "empty — `knowlet config init` to set")
    ok("llm.base_url", cfg.llm.base_url)
    ok("llm.model", cfg.llm.model)
    ok("embedding.backend", f"{cfg.embedding.backend} ({cfg.embedding.model})")

    backend = None
    if skip_embedding:
        warn("embedding load", "skipped")
    else:
        try:
            backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
            v = backend.embed_query("test")
            ok("embedding load", f"dim={backend.dim}, sample shape={v.shape}")
            if backend.dim != cfg.embedding.dim:
                cfg.embedding.dim = backend.dim
                save_config(vault.root, cfg)
                warn("embedding dim", f"updated cfg.embedding.dim → {backend.dim}")
        except Exception as exc:  # noqa: BLE001
            fail("embedding load", f"{type(exc).__name__}: {exc}")

    if backend is not None:
        try:
            idx = Index(vault.db_path, backend)
            idx.connect()
            n = len(idx.list_notes(limit=10000))
            idx.close()
            ok("index", f"{n} note(s) indexed")
        except IndexDimensionMismatchError as exc:
            fail("index dim", str(exc))
        except Exception as exc:  # noqa: BLE001
            fail("index", f"{type(exc).__name__}: {exc}")
    else:
        warn("index", "skipped (no embedding backend)")

    # Vault integrity: parse every Note / Card / Draft / MiningTask file
    # and report counts. Anything that fails to parse is a red flag —
    # could be schema drift, manual edit gone wrong, or a partial write
    # from a crashed process. Lets the user catch silent corruption
    # before it bites them. Read-only; never modifies the vault.
    integrity_failures = _check_vault_integrity(vault)
    for entity, total, failed_paths in integrity_failures:
        if not total and not failed_paths:
            continue
        if failed_paths:
            fail(
                f"vault integrity / {entity}",
                f"{len(failed_paths)} of {total} failed to parse: "
                + ", ".join(str(p) for p in failed_paths[:3])
                + (" …" if len(failed_paths) > 3 else ""),
            )
        else:
            ok(f"vault integrity / {entity}", f"{total} file(s) parse cleanly")

    if skip_llm:
        warn("llm ping", "skipped")
    elif not cfg.llm.api_key:
        warn("llm ping", "skipped (no api_key)")
    else:
        llm = LLMClient(cfg.llm)
        try:
            resp = llm.chat(
                [{"role": "user", "content": "Reply with exactly: pong"}],
                max_tokens=8,
                temperature=0,
            )
            content = (resp.content or "").strip()
            if "pong" in content.lower():
                ok("llm ping", f"got {content!r}")
            else:
                warn("llm ping", f"unexpected reply {content!r}")
        except Exception as exc:  # noqa: BLE001
            fail("llm ping", f"{type(exc).__name__}: {exc} — check base_url / api_key / network")

        try:
            registry = default_registry()
            resp = llm.chat(
                [
                    {
                        "role": "user",
                        "content": (
                            "Call the search_notes tool with query='ping' and limit=1. "
                            "Do not answer in prose."
                        ),
                    }
                ],
                tools=registry.openai_schema(),
                max_tokens=128,
                temperature=0,
            )
            if resp.tool_calls:
                names = ", ".join(tc.name for tc in resp.tool_calls)
                ok("llm tool-calling", f"{len(resp.tool_calls)} call(s): {names}")
            else:
                fail(
                    "llm tool-calling",
                    "no tool_calls in response — backend may not support OpenAI tool-calling",
                )
        except Exception as exc:  # noqa: BLE001
            fail("llm tool-calling", f"{type(exc).__name__}: {exc}")

    return results


def _check_vault_integrity(vault: Vault) -> list[tuple[str, int, list]]:
    """Walk every entity file in the vault and try to parse it. Returns
    [(entity_name, total_count, failed_paths)] per type. Pure read; never
    modifies anything. Failures might mean schema drift / partial writes
    / manual edits gone wrong — surface them so the user can investigate
    before the bad file silently propagates through index rebuilds."""
    from knowlet.core.card import Card
    from knowlet.core.drafts import Draft
    from knowlet.core.mining.task import MiningTask
    from knowlet.core.note import Note

    out: list[tuple[str, int, list]] = []

    # Notes — recursive walk via vault.iter_note_paths (skips .trash
    # and _attachments by design).
    note_paths = list(vault.iter_note_paths())
    note_failed = []
    for p in note_paths:
        try:
            Note.from_file(p)
        except Exception:  # noqa: BLE001
            note_failed.append(p.name)
    out.append(("notes", len(note_paths), note_failed))

    # Cards — JSON.
    card_failed = []
    card_paths = list(vault.cards_dir.glob("*.json")) if vault.cards_dir.exists() else []
    for p in card_paths:
        try:
            Card.from_file(p)
        except Exception:  # noqa: BLE001
            card_failed.append(p.name)
    out.append(("cards", len(card_paths), card_failed))

    # Drafts — Markdown + frontmatter.
    draft_failed = []
    draft_paths = list(vault.drafts_dir.glob("*.md")) if vault.drafts_dir.exists() else []
    for p in draft_paths:
        try:
            Draft.from_file(p)
        except Exception:  # noqa: BLE001
            draft_failed.append(p.name)
    out.append(("drafts", len(draft_paths), draft_failed))

    # Mining tasks — Markdown + frontmatter.
    task_failed = []
    task_paths = list(vault.tasks_dir.glob("*.md")) if vault.tasks_dir.exists() else []
    for p in task_paths:
        try:
            MiningTask.from_file(p)
        except Exception:  # noqa: BLE001
            task_failed.append(p.name)
    out.append(("mining_tasks", len(task_paths), task_failed))

    return out


def print_doctor(results: list[tuple[str, str, str]]) -> None:
    icons = {"ok": "[green]✓[/green]", "fail": "[red]✗[/red]", "warn": "[yellow]⚠[/yellow]"}
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("", width=2)
    table.add_column("check", style="bold")
    table.add_column("detail", overflow="fold")
    for status, name, detail in results:
        table.add_row(icons[status], name, detail)
    console.print(table)
    failures = sum(1 for r in results if r[0] == "fail")
    warnings = sum(1 for r in results if r[0] == "warn")
    if failures:
        console.print(f"\n[red]doctor: {failures} failure(s), {warnings} warning(s)[/red]")
    elif warnings:
        console.print(f"\n[yellow]doctor: {warnings} warning(s)[/yellow]")
    else:
        console.print("\n[green]doctor: all checks passed[/green]")
