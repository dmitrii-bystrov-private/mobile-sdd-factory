#!/bin/bash
# Validate spec.md files have all required sections before writing.
# Runs as PreToolUse hook on Write|Edit. Exit 2 = block with feedback.

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only validate spec.md files in workdir
[[ "$FILE_PATH" =~ workdir/[^/]+/spec\.md$ ]] || exit 0

# For Edit, we can't validate the full content — only Write has it
if [[ "$TOOL" == "Write" ]]; then
  CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
else
  # For Edit, read the file after applying the edit is not possible in PreToolUse.
  # Skip validation for edits — the initial Write will catch missing sections.
  exit 0
fi

MISSING=()

echo "$CONTENT" | grep -q '## Context'             || MISSING+=("Context")
echo "$CONTENT" | grep -q '## Objective'            || MISSING+=("Objective")
echo "$CONTENT" | grep -q '## Acceptance Criteria'   || MISSING+=("Acceptance Criteria")
echo "$CONTENT" | grep -q '## Codebase Context'      || MISSING+=("Codebase Context")
echo "$CONTENT" | grep -q '## Implementation Plan'   || MISSING+=("Implementation Plan")
echo "$CONTENT" | grep -q '## Out of Scope'           || MISSING+=("Out of Scope")

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Spec is missing required sections: ${MISSING[*]}. Add them before saving." >&2
  exit 2
fi

exit 0
