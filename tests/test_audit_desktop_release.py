"""Regression tests for the 2026-11 desktop/release audit batch.

These tests lock the fixes for findings in scripts/ and .github/workflows/:

- prepare-version.sh must include pyproject.toml in its version consistency
  checklist (it is the authoritative Python package version source).
- release.yml must not interpolate workflow_dispatch inputs directly into
  shell (command injection on a runner holding signing keys).
- release.yml must refuse to publish when the built version does not match
  the release tag (otherwise latest.json silently freezes the update channel).
- release.yml must not mark semver pre-release tags as the `latest` release
  nor publish latest.json for them (otherwise all users auto-update to betas).
- ci.yml must at least `cargo check` the src-tauri Rust crate.
- build-macos.sh must regenerate (and re-sign) the updater archive after the
  post-build codesign pass, so auto-update ships the same bytes as the DMG.
- build-backend-sidecars.sh must install backend dependencies from uv.lock
  instead of re-resolving floating `>=` bounds from PyPI at release time.
- scripts/test-frontend.sh and scripts/build-frontend.sh must not point at
  the deleted knowlet/web/static tree.

Most scripts here are shell/YAML, so several tests assert on content shape
(the cheapest faithful regression lock for workflow files); the
prepare-version.sh test runs the real script against a sandboxed repo tree.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BUILD_MACOS = REPO_ROOT / "scripts" / "desktop" / "build-macos.sh"
SIDECARS = REPO_ROOT / "scripts" / "desktop" / "build-backend-sidecars.sh"
PREPARE_VERSION = REPO_ROOT / "scripts" / "release" / "prepare-version.sh"


# ---------------------------------------------------------------- helpers


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_sandbox_repo(tmp_path: Path, *, pyproject_version: str) -> Path:
    """Build a minimal repo tree that prepare-version.sh can run against."""
    root = tmp_path / "repo"
    version = "9.9.9"
    _write(root / "frontend" / "package.json", json.dumps({"version": version}))
    _write(
        root / "frontend" / "package-lock.json",
        json.dumps({"version": version, "packages": {"": {"version": version}}}),
    )
    _write(
        root / "frontend" / "src-tauri" / "tauri.conf.json",
        json.dumps({"version": version}),
    )
    _write(
        root / "frontend" / "src-tauri" / "Cargo.toml",
        f'[package]\nname = "knowlet-desktop"\nversion = "{version}"\n',
    )
    _write(root / "knowlet" / "__init__.py", f'__version__ = "{version}"\n')
    _write(
        root / "pyproject.toml",
        f'[project]\nname = "knowlet"\nversion = "{pyproject_version}"\n',
    )

    script = root / "scripts" / "release" / "prepare-version.sh"
    _write(script, PREPARE_VERSION.read_text(encoding="utf-8"))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    # Stub `gh` so the script never talks to the real GitHub API from a test.
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    gh = stub_bin / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)

    subprocess.run(
        ["git", "init", "--quiet", str(root)],
        check=True,
        capture_output=True,
    )
    return root


def _run_prepare_version(root: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'stub-bin'}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", "scripts/release/prepare-version.sh", "--allow-dirty", "v9.9.9"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


# ------------------------------------------------- prepare-version.sh


def test_prepare_version_rejects_stale_pyproject_version(tmp_path: Path) -> None:
    """A stale pyproject.toml version must fail the release preflight."""
    root = _make_sandbox_repo(tmp_path, pyproject_version="0.0.1")

    result = _run_prepare_version(root, tmp_path)

    assert result.returncode != 0, (
        "prepare-version.sh passed although pyproject.toml is at 0.0.1 while "
        f"the tag is v9.9.9\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "pyproject.toml" in result.stderr


def test_prepare_version_passes_when_all_versions_match(tmp_path: Path) -> None:
    root = _make_sandbox_repo(tmp_path, pyproject_version="9.9.9")

    result = _run_prepare_version(root, tmp_path)

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Release preflight passed" in result.stdout


# ------------------------------------------------------- release.yml


def test_release_workflow_never_interpolates_inputs_into_shell() -> None:
    """workflow_dispatch inputs must flow through env vars, not `${{ }}`
    template interpolation inside run scripts (command injection surface)."""
    content = RELEASE_YML.read_text(encoding="utf-8")
    yaml_mapping_line = re.compile(r"^\s*[\w.-]+:\s")
    offenders = [
        line
        for line in content.splitlines()
        if ("${{ inputs." in line or "${{ github.event.inputs" in line)
        and not yaml_mapping_line.match(line)
    ]
    assert offenders == [], (
        f"workflow_dispatch inputs are interpolated directly into a script block: {offenders}"
    )


def test_release_workflow_verifies_tag_matches_built_version() -> None:
    content = RELEASE_YML.read_text(encoding="utf-8")
    assert '"v$version"' in content and "RELEASE_TAG" in content, (
        "release.yml must compare the built tauri.conf.json version against "
        "the release tag before publishing"
    )
    assert "does not match release tag" in content


def test_release_workflow_does_not_mark_prereleases_latest() -> None:
    content = RELEASE_YML.read_text(encoding="utf-8")
    assert "prerelease=true" in content, (
        "release.yml must detect semver pre-release tags (containing '-')"
    )
    assert "--prerelease" in content, (
        "pre-release tags must create a GitHub pre-release, not a --latest "
        "release that the updater endpoint resolves"
    )


def test_release_workflow_skips_latest_json_for_prereleases() -> None:
    content = RELEASE_YML.read_text(encoding="utf-8")
    # latest.json must only be uploaded on stable releases; a pre-release
    # publishing latest.json would push every production user onto the beta.
    create_step = content.split("Create GitHub release", 1)[1]
    assert "PRERELEASE" in create_step and "latest.json" in create_step, (
        "the release-creation step must gate latest.json on the prerelease flag"
    )


# ------------------------------------------------------------ ci.yml


def test_ci_checks_desktop_rust_crate() -> None:
    content = CI_YML.read_text(encoding="utf-8")
    assert "cargo check" in content, (
        "ci.yml must at least `cargo check` frontend/src-tauri so Rust "
        "breakage surfaces before the manual release workflow"
    )
    assert "macos" in content, "the Rust check must run on a macOS runner"


# ------------------------------------------------------ build-macos.sh


def test_build_macos_regenerates_updater_archive_after_resign() -> None:
    content = BUILD_MACOS.read_text(encoding="utf-8")
    resign_app = content.index(
        'codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$APP"'
    )
    assert "Knowlet.app.tar.gz" in content, (
        "build-macos.sh must rebuild the updater archive from the re-signed app"
    )
    archive = content.index("Knowlet.app.tar.gz")
    signer = content.index("signer sign")
    assert resign_app < archive, (
        "the updater archive must be created AFTER the post-build codesign "
        "pass, otherwise auto-update ships the unsigned snapshot"
    )
    assert archive < signer or "signer sign" in content[resign_app:], (
        "the regenerated updater archive must be re-signed with the Tauri updater key"
    )


# ------------------------------------- build-backend-sidecars.sh


def test_sidecar_build_installs_locked_dependencies() -> None:
    content = SIDECARS.read_text(encoding="utf-8")
    assert '"$ROOT[sync]"' not in content, (
        "sidecar deps must come from uv.lock, not a fresh PyPI resolution of "
        "pyproject '>=' lower bounds at release time"
    )
    assert "uv export" in content and "--frozen" in content, (
        "sidecar build must export pinned requirements from uv.lock"
    )
    assert "--no-deps" in content, (
        "the knowlet project itself must be installed with --no-deps so the "
        "lockfile stays the single source of dependency versions"
    )


# ------------------------------------------- legacy frontend scripts


def test_legacy_frontend_scripts_do_not_reference_deleted_static_dir() -> None:
    for script in ("test-frontend.sh", "build-frontend.sh"):
        content = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert "knowlet/web/static" not in content, (
            f"scripts/{script} references knowlet/web/static which no longer "
            "exists; it must target the real frontend/ commands"
        )
