#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TAURI="$ROOT/frontend/src-tauri"
BIN_DIR="$TAURI/binaries"
BUILD_ROOT="${KNOWLET_SIDECAR_BUILD_ROOT:-$TAURI/target/sidecars}"
PYINSTALLER_VERSION="6.20.0"

export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export LC_CTYPE="en_US.UTF-8"

mkdir -p "$BIN_DIR" "$BUILD_ROOT"

build_one() {
  local label="$1"
  local target_triple="$2"
  local python_request="$3"
  shift 3
  local arch_prefix=("$@")

  local venv="$BUILD_ROOT/venv-$label"
  local dist="$BUILD_ROOT/dist-$label"
  local work="$BUILD_ROOT/build-$label"
  local spec="$BUILD_ROOT/spec-$label"
  local output="$BIN_DIR/knowlet-backend-$target_triple"

  rm -rf "$venv" "$dist" "$work" "$spec"
  uv venv "$venv" --python "$python_request"
  uv pip install --python "$venv/bin/python" "pyinstaller==$PYINSTALLER_VERSION" "$ROOT"
  local python_cmd=("$venv/bin/python")
  if ((${#arch_prefix[@]})); then
    python_cmd=("${arch_prefix[@]}" "$venv/bin/python")
  fi

  (
    cd "$ROOT"
    "${python_cmd[@]}" -m PyInstaller \
      --clean \
      --onefile \
      --name knowlet-backend \
      --collect-binaries sqlite_vec \
      --exclude-module sentence_transformers \
      --exclude-module torch \
      --exclude-module transformers \
      --exclude-module scipy \
      --exclude-module sklearn \
      --distpath "$dist" \
      --workpath "$work" \
      --specpath "$spec" \
      knowlet/__main__.py
  )

  cp "$dist/knowlet-backend" "$output"
  chmod 755 "$output"
  file "$output"
}

build_one "aarch64" "aarch64-apple-darwin" "cpython-3.12.13-macos-aarch64-none"
build_one "x86_64" "x86_64-apple-darwin" "cpython-3.12.13-macos-x86_64-none" arch -x86_64

UNIVERSAL_OUTPUT="$BIN_DIR/knowlet-backend-universal-apple-darwin"
LAUNCHER_SRC="$BUILD_ROOT/knowlet-backend-launcher.c"
cat >"$LAUNCHER_SRC" <<'C'
#include <libgen.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char *backend_name(void) {
#if defined(__x86_64__)
  return "knowlet-backend-x86_64-apple-darwin";
#elif defined(__aarch64__) || defined(__arm64__)
  return "knowlet-backend-aarch64-apple-darwin";
#else
  return NULL;
#endif
}

static int exec_backend(const char *path, int argc, char **argv) {
  if (access(path, X_OK) != 0) {
    return -1;
  }

  char **child_argv = calloc((size_t)argc + 1, sizeof(char *));
  if (child_argv == NULL) {
    perror("calloc");
    return -1;
  }

  child_argv[0] = (char *)path;
  for (int i = 1; i < argc; i++) {
    child_argv[i] = argv[i];
  }
  execv(path, child_argv);
  perror(path);
  free(child_argv);
  return -1;
}

int main(int argc, char **argv) {
  const char *name = backend_name();
  if (name == NULL) {
    fprintf(stderr, "Knowlet backend does not support this CPU architecture.\n");
    return 127;
  }

  char raw_exe[PATH_MAX];
  uint32_t raw_size = sizeof(raw_exe);
  if (_NSGetExecutablePath(raw_exe, &raw_size) != 0) {
    fprintf(stderr, "Unable to resolve Knowlet backend launcher path.\n");
    return 127;
  }

  char resolved_exe[PATH_MAX];
  const char *exe_path = realpath(raw_exe, resolved_exe) != NULL ? resolved_exe : raw_exe;

  char dir_buffer[PATH_MAX];
  if (strlen(exe_path) >= sizeof(dir_buffer)) {
    fprintf(stderr, "Knowlet backend launcher path is too long.\n");
    return 127;
  }
  strcpy(dir_buffer, exe_path);
  char *exe_dir = dirname(dir_buffer);

  char candidate[PATH_MAX];
  if (snprintf(candidate, sizeof(candidate), "%s/%s", exe_dir, name) < (int)sizeof(candidate)) {
    exec_backend(candidate, argc, argv);
  }

  if (snprintf(candidate, sizeof(candidate), "%s/../Resources/knowlet-sidecars/%s", exe_dir, name) < (int)sizeof(candidate)) {
    exec_backend(candidate, argc, argv);
  }

  fprintf(stderr, "Knowlet backend sidecar not found for %s.\n", name);
  return 127;
}
C

clang \
  -arch arm64 \
  -arch x86_64 \
  -O2 \
  -mmacosx-version-min=13.0 \
  "$LAUNCHER_SRC" \
  -o "$UNIVERSAL_OUTPUT"
chmod 755 "$UNIVERSAL_OUTPUT"
file "$UNIVERSAL_OUTPUT"
"$UNIVERSAL_OUTPUT" --version
arch -x86_64 "$UNIVERSAL_OUTPUT" --version
