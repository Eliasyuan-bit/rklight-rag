#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/deploy/board.env"
# shellcheck disable=SC1091
source "$ROOT/deploy/lightrag-upstream.env"

TARGET="$BOARD_APP_ROOT/third_party/LightRAG"
VENV="$BOARD_APP_ROOT/venv"
# Keep the conditional on the board.  Some adb shell implementations do not
# reliably return a failing `test` status to the host, which used to make a
# first deployment incorrectly take the `git -C` update path.
adb -s "$ADB_SERIAL" shell "
  set -e
  mkdir -p '$BOARD_APP_ROOT/third_party'
  if test -d '$TARGET/.git' && git -C '$TARGET' cat-file -e '$LIGHTRAG_UPSTREAM_REVISION^{commit}' 2>/dev/null; then
    :
  elif test -d '$TARGET/.git'; then
    git -C '$TARGET' fetch --depth 1 origin '$LIGHTRAG_UPSTREAM_REVISION'
  else
    test ! -e '$TARGET' || { echo '[ERROR] Invalid LightRAG target: $TARGET' >&2; exit 1; }
    git clone --depth 1 '$LIGHTRAG_UPSTREAM_URL' '$TARGET'
    git -C '$TARGET' fetch --depth 1 origin '$LIGHTRAG_UPSTREAM_REVISION'
  fi
  git -C '$TARGET' checkout --detach '$LIGHTRAG_UPSTREAM_REVISION'

  if test ! -x '$VENV/bin/python' || ! '$VENV/bin/python' -m pip --version >/dev/null 2>&1; then
    rm -rf '$VENV'
    if ! python3 -m venv --system-site-packages '$VENV'; then
      echo '[ACTION] Installing python3.11-venv for the board-local LightRAG environment.'
      apt-get update
      apt-get install -y python3.11-venv
      rm -rf '$VENV'
      python3 -m venv --system-site-packages '$VENV'
    fi
  fi
  PYTHON='$VENV/bin/python'

  # Older hook installation copied files into site-packages/lightrag/api.
  # After uninstalling that older package, this can leave a namespace-only
  # directory without __init__.py which shadows the editable source package.
  \"\$PYTHON\" -c '
import pathlib, shutil, sysconfig
package = pathlib.Path(sysconfig.get_paths()[\"purelib\"]) / \"lightrag\"
if package.is_dir() and not (package / \"__init__.py\").is_file():
    shutil.rmtree(package)
' || exit 1
  \"\$PYTHON\" -m pip install --disable-pip-version-check --no-deps --no-build-isolation --upgrade -e '$TARGET[api]'
  test -x '$VENV/bin/lightrag-server'
  \"\$PYTHON\" -c 'import lightrag; assert lightrag.__file__; print(lightrag.__file__)'
"

echo "Official LightRAG $LIGHTRAG_UPSTREAM_REVISION installed from $TARGET on board."
