#!/usr/bin/env bash
# Clean-profile test: a fresh container with only the chosen KiCad AppImage installs kicaddy from the repo's
# marketplace catalog into omp, configures it, runs doctor, builds the NE555 example, writes its BOM, and runs
# the plugin on upstream pi with a scripted model.
#
#     tools/clean/run.sh [APPIMAGE]     default: the KiCad in kicaddy's config
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

python3 - "$REPO" <<'EOF'
import json, sys
repo = sys.argv[1]
plugin = json.load(open(f"{repo}/plugin/package.json"))["version"]
catalog = json.load(open(f"{repo}/.omp-plugin/marketplace.json"))["plugins"][0]["version"]
if plugin != catalog:
    sys.exit(f"version mismatch: plugin/package.json {plugin}, .omp-plugin/marketplace.json {catalog}")
EOF

if [[ $# -ge 1 ]]; then
	APPIMAGE=$(realpath "$1")
else
	CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/kicaddy/config.json"
	APPIMAGE=$(realpath "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["kicad"])' "$CONFIG")")
fi
if [[ ! -f $APPIMAGE ]]; then
	echo "not a file: $APPIMAGE" >&2
	exit 1
fi
OMP=$(realpath "$(command -v omp)")

docker build -t kicaddy-clean "$REPO/tools/clean"
docker run --rm -v "$REPO":/src:ro -v "$APPIMAGE":/kicad/kicad.AppImage:ro -v "$OMP":/usr/local/bin/omp:ro \
	kicaddy-clean bash /src/tools/clean/inside.sh
