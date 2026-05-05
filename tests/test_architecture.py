"""Architecture-boundary tests (ADR-0020 §Layer 5).

knowlet's layering contract:

    knowlet.core   — pure business logic; no FastAPI, no typer, no UI
    knowlet.chat   — chat orchestration on top of core; no UI frameworks
    knowlet.web    — FastAPI server; may import core + chat
    knowlet.cli    — typer commands; may import core + chat
    knowlet.web    must NOT import knowlet.cli (and vice versa)

This test parses every module's imports with `ast` (no execution) and
asserts the contract. If a future change reaches sideways across layers,
this test is the canary that catches it before merge.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "knowlet"


# layer → set of layer prefixes that this layer is FORBIDDEN to import.
# `core.*` is allowed by everyone, so it never appears in any "forbidden" set.
FORBIDDEN: dict[str, set[str]] = {
    "knowlet.core": {"knowlet.web", "knowlet.cli", "knowlet.chat"},
    "knowlet.chat": {"knowlet.web", "knowlet.cli"},
    "knowlet.web": {"knowlet.cli"},
    "knowlet.cli": {"knowlet.web"},
}


def _module_dotted_name(path: Path) -> str:
    rel = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_in(path: Path) -> set[str]:
    """Return the set of fully-qualified module names imported at module top level.

    Function-local imports are deliberately *not* counted: they are the
    escape hatch for entry-point dispatch (e.g. `knowlet web` lazily imports
    FastAPI) and for breaking circular dep cycles. Top-level imports are
    what define the architecture, and that's what we enforce.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise AssertionError(f"failed to parse {path}: {exc}") from exc
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _layer_for(module: str) -> str | None:
    """Return the top-level knowlet layer for a dotted module name, or None."""
    for layer in FORBIDDEN:
        if module == layer or module.startswith(layer + "."):
            return layer
    return None


def _iter_source_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize(
    "path", _iter_source_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_module_respects_layer_boundaries(path: Path) -> None:
    """Every knowlet module's imports must respect the layer contract."""
    module = _module_dotted_name(path)
    layer = _layer_for(module)
    if layer is None:
        # Top-level knowlet/__init__.py etc. — exempt from layer rules.
        return

    forbidden = FORBIDDEN[layer]
    for imp in _imports_in(path):
        imp_layer = _layer_for(imp)
        if imp_layer is None:
            continue
        if imp_layer in forbidden:
            raise AssertionError(
                f"{module} (layer {layer}) imports {imp} (layer {imp_layer}) "
                f"— forbidden by ADR-0020 §Layer 5"
            )


def test_layer_definitions_are_complete() -> None:
    """Sanity: every top-level subpackage of knowlet/ has a layer entry."""
    expected = {p.name for p in PACKAGE_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")}
    declared = {layer.split(".", 1)[1] for layer in FORBIDDEN}
    missing = expected - declared
    # `core`, `chat`, `web`, `cli` are the four layers we care about today.
    # Anything new (e.g. `knowlet/desktop/`) should be added to FORBIDDEN.
    assert not missing, (
        f"new top-level subpackage(s) without layer rules: {missing}. "
        f"Add them to FORBIDDEN in tests/test_architecture.py."
    )
