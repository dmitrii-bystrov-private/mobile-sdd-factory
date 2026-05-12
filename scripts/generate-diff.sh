#!/usr/bin/env bash
# Generates a structured git diff artifact and writes it to spec/*.md.
# Usage:
#   bash scripts/generate-diff.sh <KEY> [--mode source|docs|full] [--output <path>]
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: bash scripts/generate-diff.sh <KEY> [--mode source|docs|full] [--output <path>]

Modes:
  source  Source files only (.swift, .kt, .kts, .xml). Default.
  docs    Documentation-oriented files (.md, .adoc, .rst, .txt).
  full    Source + documentation-oriented files.
EOF
}

KEY="${1:-}"
if [[ -z "$KEY" ]]; then
  usage
  exit 1
fi
shift

MODE="source"
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

case "$MODE" in
  source)
    DEFAULT_OUT="diff.md"
    FILTER_DESC="source files (.swift, .kt, .kts, .xml)"
    PATTERNS=('*.swift' '*.kt' '*.kts' '*.xml')
    ;;
  docs)
    DEFAULT_OUT="doc-diff.md"
    FILTER_DESC="documentation files (.md, .adoc, .rst, .txt)"
    PATTERNS=('*.md' '*.adoc' '*.rst' '*.txt')
    ;;
  full)
    DEFAULT_OUT="full-diff.md"
    FILTER_DESC="source + documentation files"
    PATTERNS=('*.swift' '*.kt' '*.kts' '*.xml' '*.md' '*.adoc' '*.rst' '*.txt')
    ;;
  *)
    echo "ERROR: unsupported mode: $MODE" >&2
    usage
    exit 1
    ;;
esac

WORKDIR="${SDD_WORKDIR}/${KEY}"
REPO="${WORKDIR}/repo"
SPEC_DIR="${WORKDIR}/spec"
OUT="${OUTPUT:-${SPEC_DIR}/${DEFAULT_OUT}}"

if [[ ! -e "$REPO/.git" ]]; then
  echo "ERROR: repo not found at $REPO" >&2
  exit 1
fi

mkdir -p "$SPEC_DIR"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

name_status_file="$tmpdir/name-status.txt"
numstat_file="$tmpdir/numstat.txt"
raw_diff_file="$tmpdir/raw-diff.txt"
artifact_file="$tmpdir/artifact.md"

pathspec_args=()
for pattern in "${PATTERNS[@]}"; do
  pathspec_args+=("$pattern")
done
pathspec_args+=(':!*.generated.*' ':!Pods/' ':!node_modules/')

git -C "$REPO" diff --find-renames --name-status origin/master...HEAD -- "${pathspec_args[@]}" > "$name_status_file"
git -C "$REPO" diff --find-renames --numstat origin/master...HEAD -- "${pathspec_args[@]}" > "$numstat_file"
git -C "$REPO" diff --find-renames origin/master...HEAD -- "${pathspec_args[@]}" > "$raw_diff_file"

status_count() {
  local prefix="$1"
  if [[ ! -s "$name_status_file" ]]; then
    echo 0
    return
  fi

  awk -v prefix="$prefix" '
    {
      code = $1
      if (index(code, prefix) == 1) {
        count++
      }
    }
    END { print count + 0 }
  ' "$name_status_file"
}

doc_count="$(
  if [[ ! -s "$name_status_file" ]]; then
    echo 0
  else
    awk -F '\t' '
      function is_doc(path) {
        return path ~ /\.(md|adoc|rst|txt)$/
      }
      {
        if (NF >= 3) {
          if (is_doc($3)) count++
        } else if (NF >= 2) {
          if (is_doc($2)) count++
        }
      }
      END { print count + 0 }
    ' "$name_status_file"
  fi
)"

source_count="$(
  if [[ ! -s "$name_status_file" ]]; then
    echo 0
  else
    awk -F '\t' '
      function is_source(path) {
        return path ~ /\.(swift|kt|kts|xml)$/
      }
      {
        if (NF >= 3) {
          if (is_source($3)) count++
        } else if (NF >= 2) {
          if (is_source($2)) count++
        }
      }
      END { print count + 0 }
    ' "$name_status_file"
  fi
)"

total_files="$(
  if [[ ! -s "$name_status_file" ]]; then
    echo 0
  else
    wc -l < "$name_status_file" | tr -d ' '
  fi
)"

added_count="$(status_count "A")"
modified_count="$(status_count "M")"
deleted_count="$(status_count "D")"
renamed_count="$(status_count "R")"
copied_count="$(status_count "C")"

{
  printf '# Diff Artifact: %s\n\n' "$KEY"
  echo "## Scope"
  printf -- '- Base: `origin/master...HEAD`\n'
  printf -- '- Mode: `%s`\n' "$MODE"
  printf -- '- File filter: %s\n' "$FILTER_DESC"
  printf -- '- Includes uncommitted changes: `no`\n'
  echo
  echo "## Agent Notes"
  echo "- Lines prefixed with \`+\` are present in the final branch state."
  echo "- Lines prefixed with \`-\` are removed old content and are NOT part of the final branch state."
  echo "- Unprefixed context lines are reference only."
  echo "- Use the summary sections below for file scope and stats before interpreting raw patch hunks."
  echo
  echo "## Signals"
  printf -- '- Total changed files: %s\n' "$total_files"
  printf -- '- Added files: %s\n' "$added_count"
  printf -- '- Modified files: %s\n' "$modified_count"
  printf -- '- Deleted files: %s\n' "$deleted_count"
  printf -- '- Renamed files: %s\n' "$renamed_count"
  printf -- '- Copied files: %s\n' "$copied_count"
  printf -- '- Source files changed: %s\n' "$source_count"
  printf -- '- Documentation files changed: %s\n' "$doc_count"
  echo
  echo "## Changed Files"
  echo
  echo "| Status | Path |"
  echo "|---|---|"

  if [[ -s "$name_status_file" ]]; then
    while IFS=$'\t' read -r status path1 path2; do
      if [[ -z "$status" ]]; then
        continue
      fi

      case "$status" in
        A*)
          label="added"
          path="$path1"
          ;;
        M*)
          label="modified"
          path="$path1"
          ;;
        D*)
          label="deleted"
          path="$path1"
          ;;
        R*)
          label="renamed"
          path="${path1} -> ${path2}"
          ;;
        C*)
          label="copied"
          path="${path1} -> ${path2}"
          ;;
        *)
          label="$status"
          path="${path2:-$path1}"
          ;;
      esac

      printf '| %s | `%s` |\n' "$label" "$path"
    done < "$name_status_file"
  else
    echo "| — | No matching files in diff |"
  fi

  echo
  echo "## Line Stats"
  echo
  echo "| Added | Removed | Path |"
  echo "|---:|---:|---|"

  if [[ -s "$numstat_file" ]]; then
    while IFS=$'\t' read -r added removed path; do
      [[ -z "$added" ]] && continue
      printf '| %s | %s | `%s` |\n' "$added" "$removed" "$path"
    done < "$numstat_file"
  else
    echo "| 0 | 0 | No matching files in diff |"
  fi

  echo
  echo "## Raw Diff"
  echo

  if [[ -s "$raw_diff_file" ]]; then
    cat "$raw_diff_file"
  else
    echo "# No matching diff content."
  fi
} > "$artifact_file"

mv "$artifact_file" "$OUT"

if [[ ! -s "$raw_diff_file" ]]; then
  echo "WARNING: diff is empty (branch may not have commits ahead of master or no files matched mode '$MODE')" >&2
fi

echo "✅ diff written to $OUT"
