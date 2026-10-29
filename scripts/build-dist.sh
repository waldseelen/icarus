#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"
echo "==> Running unit test suite..."
python3 -m unittest discover tests

echo "==> Preparing dist directory..."
rm -rf dist build
mkdir -p dist

echo "==> Building standalone executable zipapp (dist/icarus)..."
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT

cp -r icarus "${STAGE_DIR}/"
cat > "${STAGE_DIR}/__main__.py" <<'EOF'
import sys
from icarus.cli import main
if __name__ == "__main__":
    sys.exit(main())
EOF

python3 -m zipapp "${STAGE_DIR}" -o dist/icarus -p "/usr/bin/env python3"
chmod +x dist/icarus

# Provide alias symlink
ln -sf icarus dist/icarusctl

echo "==> Testing standalone zipapp..."
dist/icarus help > /dev/null

echo "==> Building Debian (.deb) package..."
python3 scripts/build-deb.py

echo "==> Creating release tarball (dist/icarus-1.0.0.tar.gz)..."
tar -czf dist/icarus-1.0.0.tar.gz \
    --transform 's,^,icarus-1.0.0/,' \
    bin icarus packaging tests scripts pyproject.toml README.md

echo "==> Distribution artifacts built successfully:"
ls -lh dist/
