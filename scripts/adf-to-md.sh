#!/usr/bin/env bash
# adf-to-md.sh — Deterministic Jira ADF-to-Markdown renderer.
#
# Source this file to get the render_adf_to_markdown function.
#
# Usage:
#   source scripts/adf-to-md.sh
#   render_adf_to_markdown '<adf_json_string>'
#   echo '<adf_json>' | render_adf_to_markdown

# ---------------------------------------------------------------------------
# jq program — pure functional, deterministic
# ---------------------------------------------------------------------------

_ADF_TO_MD_JQ='
# Render an inline node (text, hardBreak, or unknown inline) to a string.
def render_inline:
  if .type == "text" then
    (.marks // []) as $marks |
    (.text // "") |
    reduce $marks[] as $mark (
      .;
      if $mark.type == "strong" then "**" + . + "**"
      elif $mark.type == "em" then "_" + . + "_"
      elif $mark.type == "code" then "`" + . + "`"
      elif $mark.type == "strike" then "~~" + . + "~~"
      elif $mark.type == "link" then
        "[" + . + "](" + ($mark.attrs.href // "") + ")"
      else . end
    )
  elif .type == "hardBreak" then "  \n"
  else
    # Unknown inline — collect text from children if any
    [(.content // [])[] | render_inline] | join("")
  end;

# Render a block node to a Markdown string.
def render_block:
  # Helper: render a listItem node to its text content.
  # Nested lists are indented with two spaces.
  def item_content:
    [(.content // [])[] |
      if .type == "paragraph" then
        [(.content // [])[] | render_inline] | join("")
      elif .type == "bulletList" or .type == "orderedList" then
        "\n" + (
          render_block | rtrimstr("\n\n") |
          split("\n") | map(if . != "" then "  " + . else . end) | join("\n")
        )
      else render_inline end
    ] | join("");

  # Helper: strip all trailing newlines.
  def rstrip_nl:
    if endswith("\n") then .[:-1] | rstrip_nl else . end;

  if .type == "doc" then
    ([(.content // [])[] | render_block] | join("")) |
    gsub("\n{3,}"; "\n\n") | ltrimstr("\n") | rstrip_nl

  elif .type == "paragraph" then
    ([(.content // [])[] | render_inline] | join("")) + "\n\n"

  elif .type == "heading" then
    ((.attrs.level // 1) | if . < 1 then 1 elif . > 6 then 6 else . end) as $lvl |
    "######"[0:$lvl] + " " +
    ([(.content // [])[] | render_inline] | join("")) + "\n\n"

  elif .type == "bulletList" then
    ([(.content // [])[] | "- " + item_content] | join("\n")) + "\n\n"

  elif .type == "orderedList" then
    ([(.content // []) | to_entries[] |
      "\(.key + 1). " + (.value | item_content)
    ] | join("\n")) + "\n\n"

  elif .type == "codeBlock" then
    "```" + (.attrs.language // "") + "\n" +
    ([(.content // [])[] | .text // ""] | join("")) +
    "\n```\n\n"

  elif .type == "rule" then "---\n\n"

  elif .type == "blockquote" then
    ([(.content // [])[] | render_block] | join("")) |
    rtrimstr("\n") |
    split("\n") | map(if . == "" then "" else "> " + . end) | join("\n") | . + "\n\n"

  else
    # Unknown block — recurse into children if present, else treat as inline
    if (.content != null) then
      [(.content // [])[] | render_block] | join("")
    else render_inline end
  end;

render_block
'

# ---------------------------------------------------------------------------
# Shell function
# ---------------------------------------------------------------------------

render_adf_to_markdown() {
  local input
  if [[ $# -ge 1 ]]; then
    input="$1"
  else
    input="$(cat)"
  fi

  # Null/empty ADF (issue has no description)
  if [[ -z "$input" || "$input" == "null" ]]; then
    return 0
  fi

  printf '%s' "$input" | jq -r "$_ADF_TO_MD_JQ"
}
