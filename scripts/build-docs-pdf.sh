#!/usr/bin/env bash
# build-docs-pdf.sh — render docs/*.md to docs/pdf/*.pdf, plus a combined PDF.
#
# Pipeline: Markdown → standalone HTML (pandoc, docs/pdf/style.css inlined)
#           → headless Chrome --print-to-pdf → per-file PDF
#           → pdfunite → NemoClaw-AnSA-Complete-Documentation.pdf
#
# Requirements: pandoc 3.x, google-chrome, pdfunite (poppler-utils).
#
# Usage:
#   ./scripts/build-docs-pdf.sh              # rebuild everything
#   ./scripts/build-docs-pdf.sh 04-runbook.md  # rebuild one file (no combine)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS_DIR="$ROOT_DIR/docs"
PDF_DIR="$DOCS_DIR/pdf"
CSS_FILE="$PDF_DIR/style.css"
COMBINED="$PDF_DIR/NemoClaw-AnSA-Complete-Documentation.pdf"

PANDOC="${PANDOC:-pandoc}"
CHROME="${CHROME:-google-chrome}"
if ! command -v "$CHROME" >/dev/null 2>&1; then
  for c in google-chrome-stable chromium chromium-browser; do
    command -v "$c" >/dev/null 2>&1 && { CHROME="$c"; break; }
  done
fi

for bin in "$PANDOC" "$CHROME" pdfunite; do
  command -v "$bin" >/dev/null 2>&1 || { echo "missing required tool: $bin" >&2; exit 1; }
done
[ -r "$CSS_FILE" ] || { echo "missing stylesheet: $CSS_FILE" >&2; exit 1; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

render() {
  local md="$1" base html pdf
  base="$(basename "$md" .md)"
  html="$TMP_DIR/$base.html"
  pdf="$PDF_DIR/$base.pdf"

  "$PANDOC" "$md" \
    --standalone \
    --from=gfm \
    --metadata title="$base" \
    --css="$CSS_FILE" \
    --embed-resources \
    --output="$html"

  "$CHROME" \
    --headless \
    --disable-gpu \
    --no-sandbox \
    --no-pdf-header-footer \
    --virtual-time-budget=10000 \
    --print-to-pdf="$pdf" \
    "file://$html" >/dev/null 2>&1

  [ -s "$pdf" ] || { echo "  FAILED: $base" >&2; return 1; }
  printf '  %-34s %s\n' "$base.pdf" "$(du -h "$pdf" | cut -f1)"
}

mkdir -p "$PDF_DIR"

if [ $# -gt 0 ]; then
  for f in "$@"; do render "$DOCS_DIR/$(basename "$f")"; done
  echo "Single-file build complete — combined PDF not regenerated."
  exit 0
fi

echo "Rendering docs/*.md → docs/pdf/"
# README first, then numbered docs in order.
ORDERED=()
[ -f "$DOCS_DIR/README.md" ] && ORDERED+=("$DOCS_DIR/README.md")
while IFS= read -r f; do ORDERED+=("$f"); done < <(find "$DOCS_DIR" -maxdepth 1 -name '[0-9][0-9]-*.md' | sort)

for md in "${ORDERED[@]}"; do render "$md"; done

echo "Combining → $(basename "$COMBINED")"
PARTS=()
for md in "${ORDERED[@]}"; do
  PARTS+=("$PDF_DIR/$(basename "$md" .md).pdf")
done
pdfunite "${PARTS[@]}" "$COMBINED"
printf '  %-34s %s\n' "$(basename "$COMBINED")" "$(du -h "$COMBINED" | cut -f1)"
echo "Done — ${#PARTS[@]} documents."
