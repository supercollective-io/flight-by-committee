#!/bin/bash
# Repeatable FlightGear nightly scenery profile. All distances are metric.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
profile_dir="$repo_dir/test-results/amsterdam"
fg_binary="${FLIGHTGEAR_NIGHTLY_BINARY:-/Applications/FlightGear-Nightly/FlightGear.app/Contents/MacOS/FlightGear}"
fg_data="${FLIGHTGEAR_NIGHTLY_DATA:-$HOME/FlightGear-Nightly/fgdata}"
fg_scenery="$HOME/Library/Application Support/FlightGear/TerraSync_WS3"
mode="${1:-airport}"
if [[ $# -gt 0 ]]; then shift; fi
if [[ ! -x "$fg_binary" || ! -f "$fg_data/Aircraft/ufo/ufo-set.xml" ]]; then
  echo 'FlightGear nightly or its UFO data is missing.' >&2
  exit 1
fi
args=(
  --launcher=false --ignore-autosave --no-default-config --disable-sentry --units-meters
  "--fg-root=$fg_data"
  "--fg-aircraft=$fg_data/Aircraft" --aircraft=ufo
  "--terrasync-dir=$fg_scenery" --enable-terrasync
  --compositor=Compositor/HDR/hdr
  --prop:/scenery/use-vpb=true
  '--prop:/sim/rendering/scenery-path-suffix[98]/enabled=true'
  '--prop:/sim/rendering/scenery-path-suffix[99]/enabled=true'
  # OpenStreetMap buildings, existing landmarks, pylons and vegetation.
  --prop:/sim/rendering/osm-buildings=true
  --prop:/sim/rendering/random-buildings=false
  '--prop:/sim/rendering/scenery-path-suffix[0]/enabled=true'
  '--prop:/sim/rendering/scenery-path-suffix[2]/enabled=true'
  '--prop:/sim/rendering/scenery-path-suffix[3]/enabled=true'
  '--prop:/sim/rendering/scenery-path-suffix[4]/enabled=true'
  '--prop:/sim/rendering/scenery-path-suffix[5]/enabled=true'
  # WS3 supplies roads: avoid the older duplicate road overlay.
  '--prop:/sim/rendering/scenery-path-suffix[1]/enabled=false'
  --prop:/sim/rendering/random-vegetation=true
  --prop:/sim/rendering/vegetation-density=1
  --prop:/sim/rendering/random-vegetation-shadows=true
  --prop:/sim/rendering/photoscenery/enabled=false
  --texture-filtering=16 --visibility=25000
  --timeofday=noon --disable-real-weather-fetch
  '--metar=EHAM 061200Z 24005KT CAVOK 12/06 Q1015'
  --prop:/sim/terrasync/ai-data-enabled=false
  --disable-fullscreen --geometry=1440x900 --log-level=warn
)
case "$mode" in
  # Explicit coordinates avoid this Nightly's failed airport-dynamics lookup.
  # Start over Schiphol's airport mesh: central Amsterdam's WS3 elevation
  # query can fail during startup and leave the splash screen up indefinitely.
  airport) args+=(--lat=52.3086 --lon=4.7639 --heading=45 --on-ground) ;;
  city) args+=(--lat=52.3086 --lon=4.7639 --altitude=600 --heading=45 --in-air) ;;
  *) echo "Usage: $0 [airport|city] [additional FlightGear options]" >&2; exit 2 ;;
esac
if [[ "${1:-}" == '--print-command' ]]; then
  printf '%q ' env -u FG_LAUNCHER "FG_HOME=$profile_dir/state" "$fg_binary" "${args[@]}"
  printf '\n'
  exit 0
fi
mkdir -p "$profile_dir/state" "$profile_dir/logs" "$fg_scenery"
log_file="$profile_dir/logs/$(date +%Y%m%d-%H%M%S)-$mode.log"
echo "Starting Amsterdam ($mode). Scenery downloads continue while flying."
echo "Log: $log_file"
(
  env -u FG_LAUNCHER "FG_HOME=$profile_dir/state" "$fg_binary" "${args[@]}" "$@" &
  fg_pid=$!
  activation_pid=''
  cleanup() {
    if [[ -n "$fg_pid" ]]; then
      kill -TERM "$fg_pid" 2>/dev/null || true
    fi
    if [[ -n "$activation_pid" ]]; then
      kill -TERM "$activation_pid" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [[ "$(uname -s)" == Darwin ]]; then
    # Direct executable launches can wait for a Dock click during macOS startup.
    # Activate only this process, retaining terminal logs and exit status.
    /usr/bin/osascript -l JavaScript - "$fg_pid" <<'JXA' &
ObjC.import('AppKit');
function run(argv) {
    var pid = Number(argv[0]);
    for (var attempt = 0; attempt < 40; attempt++) {
        var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(pid);
        if (app && !app.isNil()) {
            if (app.isTerminated) return;
            if (app.activateWithOptions(3)) return;
        }
        delay(0.25);
    }
    console.log('Automatic activation did not succeed; click FlightGear in the Dock.');
}
JXA
    activation_pid=$!
  fi
  status=0
  wait "$fg_pid" || status=$?
  fg_pid=''
  exit "$status"
) 2>&1 | tee "$log_file"
