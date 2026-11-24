#!/usr/bin/env bash
# Copy Markdown to the macOS clipboard as rich HTML via mdclip
# (https://github.com/meain/mdclip), installing mdclip on first use.
#
# usage: copy-to-html.sh [--target teams|confluence] [--hardbreaks] [FILE]
#   FILE   Markdown file to convert. "-" or no FILE with piped stdin reads stdin.
#          No FILE and no piped stdin converts whatever Markdown is already
#          on the clipboard (mdclip's no-stdin mode).
set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
MDCLIP="${BIN_DIR}/mdclip"
TARBALL="https://github.com/meain/mdclip/archive/refs/heads/master.tar.gz"

die() { echo "copy-to-html: $*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "macOS only (mdclip uses the system pasteboard)"

mdclip_args=()
file=""
while (($#)); do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || die "--target needs teams|confluence"
      case "$2" in teams | confluence) ;; *) die "unknown target: $2" ;; esac
      mdclip_args+=(--target "$2")
      shift 2
      ;;
    --hardbreaks) mdclip_args+=(--hardbreaks); shift ;;
    -h | --help) sed -n '2,10p' "$0"; exit 0 ;;
    *) [[ -z "$file" ]] || die "only one FILE allowed"; file="$1"; shift ;;
  esac
done

install_mdclip() {
  command -v swift >/dev/null || die "mdclip is not installed and swift is missing (need Swift 5.10+)"
  echo "copy-to-html: installing mdclip to ${MDCLIP}" >&2
  local work
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' RETURN
  curl -fsSL "$TARBALL" | tar -xz -C "$work" --strip-components=1
  (cd "$work" && make install) >&2
}

if command -v mdclip >/dev/null; then
  MDCLIP="$(command -v mdclip)"
elif [[ ! -x "$MDCLIP" ]]; then
  install_mdclip
  [[ -x "$MDCLIP" ]] || die "install finished but ${MDCLIP} is missing"
fi

if [[ -n "$file" && "$file" != "-" ]]; then
  [[ -r "$file" ]] || die "cannot read: $file"
  "$MDCLIP" "${mdclip_args[@]}" <"$file"
elif [[ "$file" == "-" || ! -t 0 ]]; then
  "$MDCLIP" "${mdclip_args[@]}"
else
  "$MDCLIP" "${mdclip_args[@]}" </dev/null
fi

# Confirm the pasteboard now carries an HTML flavor.
if osascript -e 'clipboard info' 2>/dev/null | grep -q 'HTML'; then
  echo "copy-to-html: clipboard now holds HTML"
else
  die "mdclip ran but the clipboard has no HTML flavor"
fi
