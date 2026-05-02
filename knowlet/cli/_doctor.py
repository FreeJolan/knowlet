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
