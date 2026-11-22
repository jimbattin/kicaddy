#!/usr/bin/env bash
# Runs inside the kicaddy-clean container (tools/clean/run.sh): /src is the repo (read-only), /kicad/kicad.AppImage
# the chosen KiCad, /usr/local/bin/omp the host's omp.
set -euo pipefail

STAGE=start
trap 'status=$?; [[ $status -ne 0 ]] && echo "CLEAN INSTALL: FAIL $STAGE"; exit $status' EXIT
stage() { STAGE=$1; echo "== $1"; }
check() { "$@" || { echo "check failed: $*"; exit 1; }; }

stage kicad
cd ~ && /kicad/kicad.AppImage --appimage-extract >/dev/null
if [[ -d ~/squashfs-root ]]; then KICAD_DIR=~/squashfs-root; else KICAD_DIR=~/AppDir; fi
check test -d "$KICAD_DIR"
echo "extracted: $KICAD_DIR"

stage "omp install"
omp plugin marketplace add /src </dev/null
omp plugin install kicaddy@kicaddy </dev/null
omp plugin list </dev/null | tee /tmp/omp-list
check grep -q kicaddy /tmp/omp-list
P=~/.omp/plugins/node_modules/kicaddy
check test -f "$P/bin/kicaddy"
echo "plugin: $P"
K=(python3 "$P/bin/kicaddy")

stage unconfigured
set +e
"${K[@]}" doctor >/tmp/doctor0 2>&1
code=$?
set -e
cat /tmp/doctor0
check test "$code" -eq 1
check grep -q "config kicad" /tmp/doctor0

stage config
"${K[@]}" config kicad "$KICAD_DIR"

stage doctor
"${K[@]}" doctor | tee /tmp/doctor1
check grep -q "^ready:" /tmp/doctor1
check grep -qE "^(ok|warn) +tested " /tmp/doctor1

stage ne555
"${K[@]}" run "$P/skills/kicaddy/examples/ne555_blinker.py" --out ~/ne555 | tail -12
check test -f ~/ne555/ne555_blinker.kicad_sch
check test -f ~/ne555/ne555_blinker_crop.png

stage bom
"${K[@]}" bom ~/ne555
head -3 ~/ne555/ne555_blinker_bom.csv
check grep -q '^"Reference","Value"' <(head -1 ~/ne555/ne555_blinker_bom.csv)

stage "pi install"
pi install /src/plugin
pi list | tee /tmp/pi-list
check grep -q /src/plugin /tmp/pi-list

stage "pi smoke"
mkdir ~/pi-work && cd ~/pi-work
KICADDY_SMOKE_SCRIPT=/src/plugin/skills/kicaddy/examples/ne555_blinker.py KICADDY_SMOKE_OUT=$HOME/pi-ne555 \
	pi -e /src/tools/clean/pi-faux.ts --model faux/faux-1 --mode json --no-session "run the kicaddy smoke test" \
	>pi.jsonl 2>pi.stderr </dev/null || { tail -20 pi.stderr; exit 1; }
python3 /src/tools/clean/check_pi.py pi.jsonl pi.stderr ~/pi-ne555

stage "no orphan"
for _ in $(seq 50); do
	pgrep -f 'api-server --socket' >/dev/null || break
	sleep 0.1
done
if pgrep -af 'api-server --socket'; then
	echo "api-server still running"
	exit 1
fi

echo "CLEAN INSTALL: ok"
