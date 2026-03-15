#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../adf_to_md.sh"

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

PASS=0
FAIL=0

assert_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"

  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name"
    echo "        expected: $(printf '%s' "$expected" | od -c | head -3)"
    echo "        actual:   $(printf '%s' "$actual"   | od -c | head -3)"
    (( FAIL++ )) || true
  fi
}

# run: uses temp files to preserve exact output including trailing newlines.
# expected is written via printf so $'\n' sequences are preserved.
run() {
  local name="$1"
  local adf="$2"
  local expected="$3"
  local exp_file act_file
  exp_file="$(mktemp)"
  act_file="$(mktemp)"
  printf '%s' "$expected" > "$exp_file"
  render_adf_to_markdown "$adf" > "$act_file"
  if diff -q "$exp_file" "$act_file" > /dev/null 2>&1; then
    echo "  PASS  $name"
    (( PASS++ )) || true
  else
    echo "  FAIL  $name"
    diff "$exp_file" "$act_file" | head -10 | sed 's/^/        /'
    (( FAIL++ )) || true
  fi
  rm -f "$exp_file" "$act_file"
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

echo "=== ADF -> Markdown renderer tests ==="

# --- Plain text paragraph ---
run "paragraph plain text" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Hello world"}]}]}' \
  "Hello world"$'\n'

# --- Strong (bold) ---
run "text mark: strong" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"bold","marks":[{"type":"strong"}]}]}]}' \
  "**bold**"$'\n'

# --- Em (italic) ---
run "text mark: em" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"italic","marks":[{"type":"em"}]}]}]}' \
  "_italic_"$'\n'

# --- Inline code ---
run "text mark: code" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"myFunc","marks":[{"type":"code"}]}]}]}' \
  '`myFunc`'$'\n'

# --- Strike ---
run "text mark: strike" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"old","marks":[{"type":"strike"}]}]}]}' \
  "~~old~~"$'\n'

# --- Link ---
run "text mark: link" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"click here","marks":[{"type":"link","attrs":{"href":"https://example.com"}}]}]}]}' \
  "[click here](https://example.com)"$'\n'

# --- Multiple marks on one text node ---
run "text multiple marks: strong + em" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"both","marks":[{"type":"strong"},{"type":"em"}]}]}]}' \
  "_**both**_"$'\n'

# --- hardBreak ---
run "hardBreak" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"line1"},{"type":"hardBreak"},{"type":"text","text":"line2"}]}]}' \
  "line1  "$'\n'"line2"$'\n'

# --- Heading level 1 ---
run "heading level 1" \
  '{"type":"doc","content":[{"type":"heading","attrs":{"level":1},"content":[{"type":"text","text":"Title"}]}]}' \
  "# Title"$'\n'

# --- Heading level 2 ---
run "heading level 2" \
  '{"type":"doc","content":[{"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"Section"}]}]}' \
  "## Section"$'\n'

# --- Heading level 6 ---
run "heading level 6" \
  '{"type":"doc","content":[{"type":"heading","attrs":{"level":6},"content":[{"type":"text","text":"Deep"}]}]}' \
  "###### Deep"$'\n'

# --- Bullet list ---
run "bulletList simple" \
  '{"type":"doc","content":[{"type":"bulletList","content":[
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Alpha"}]}]},
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Beta"}]}]}
  ]}]}' \
  "- Alpha"$'\n'"- Beta"$'\n'

# --- Ordered list ---
run "orderedList simple" \
  '{"type":"doc","content":[{"type":"orderedList","content":[
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"First"}]}]},
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Second"}]}]},
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Third"}]}]}
  ]}]}' \
  "1. First"$'\n'"2. Second"$'\n'"3. Third"$'\n'

# --- Nested bullet list ---
run "bulletList nested" \
  '{"type":"doc","content":[{"type":"bulletList","content":[
    {"type":"listItem","content":[
      {"type":"paragraph","content":[{"type":"text","text":"Parent"}]},
      {"type":"bulletList","content":[
        {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Child"}]}]}
      ]}
    ]}
  ]}]}' \
  "- Parent"$'\n'"  - Child"$'\n'

# --- Code block without language ---
run "codeBlock no language" \
  '{"type":"doc","content":[{"type":"codeBlock","attrs":{},"content":[{"type":"text","text":"x = 1"}]}]}' \
  '```'$'\n'"x = 1"$'\n''```'$'\n'

# --- Code block with language ---
run "codeBlock with language" \
  '{"type":"doc","content":[{"type":"codeBlock","attrs":{"language":"swift"},"content":[{"type":"text","text":"let x = 1"}]}]}' \
  '```swift'$'\n'"let x = 1"$'\n''```'$'\n'

# --- Horizontal rule ---
run "rule" \
  '{"type":"doc","content":[{"type":"rule"}]}' \
  "---"$'\n'

# --- ## and --- inside paragraph text do not break structure ---
run "text with ## heading-like content" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"## not a heading"}]}]}' \
  "## not a heading"$'\n'

run "text with --- rule-like content" \
  '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"---"}]}]}' \
  "---"$'\n'

# The key check: ## inside a codeBlock sentinel is still safely wrapped
run "codeBlock body with ## and --- (sentinel robustness)" \
  '{"type":"doc","content":[{"type":"codeBlock","attrs":{},"content":[{"type":"text","text":"## heading\n---\nend"}]}]}' \
  '```'$'\n'"## heading"$'\n'"---"$'\n'"end"$'\n''```'$'\n'

# --- null / empty input returns empty ---
assert_eq "null input returns empty" "" "$(render_adf_to_markdown 'null')"
assert_eq "empty string returns empty" "" "$(render_adf_to_markdown '')"

# --- Multiple paragraphs ---
run "multiple paragraphs" \
  '{"type":"doc","content":[
    {"type":"paragraph","content":[{"type":"text","text":"First"}]},
    {"type":"paragraph","content":[{"type":"text","text":"Second"}]}
  ]}' \
  "First"$'\n\n'"Second"$'\n'

# --- Determinism: same input => byte-for-byte identical output ---
ADF_SAMPLE='{"type":"doc","content":[
  {"type":"heading","attrs":{"level":2},"content":[{"type":"text","text":"Summary"}]},
  {"type":"paragraph","content":[
    {"type":"text","text":"See "},
    {"type":"text","text":"link","marks":[{"type":"link","attrs":{"href":"https://example.com"}}]},
    {"type":"text","text":" for details."}
  ]},
  {"type":"bulletList","content":[
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Item 1"}]}]},
    {"type":"listItem","content":[{"type":"paragraph","content":[{"type":"text","text":"Item 2"}]}]}
  ]}
]}'

RUN1="$(render_adf_to_markdown "$ADF_SAMPLE")"
RUN2="$(render_adf_to_markdown "$ADF_SAMPLE")"
assert_eq "determinism: two runs produce identical output" "$RUN1" "$RUN2"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"
if (( FAIL > 0 )); then
  exit 1
fi
