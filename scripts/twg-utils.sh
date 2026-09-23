#!/usr/bin/env bash

run_twg_json() {
  local output_path="$1"
  shift

  local tmp_output tmp_error stdout_path
  tmp_output="$(mktemp)"
  tmp_error="$(mktemp)"

  if ! twg "$@" -o json >"$tmp_output" 2>"$tmp_error"; then
    cat "$tmp_error" >&2
    cat "$tmp_output" >&2
    rm -f "$tmp_output" "$tmp_error"
    return 1
  fi

  if jq -e . "$tmp_output" >/dev/null 2>&1; then
    cp "$tmp_output" "$output_path"
    rm -f "$tmp_output" "$tmp_error"
    return 0
  fi

  stdout_path="$(awk -F'"' '/^[[:space:]]*stdout: "/ {print $2; exit}' "$tmp_output")"
  if [[ -n "$stdout_path" && -f "$stdout_path" ]]; then
    cp "$stdout_path" "$output_path"
    rm -f "$tmp_output" "$tmp_error"
    return 0
  fi

  echo "ERROR: twg did not produce machine-readable JSON or an output_files.stdout path." >&2
  cat "$tmp_error" >&2
  cat "$tmp_output" >&2
  rm -f "$tmp_output" "$tmp_error"
  return 1
}

normalize_twg_issue_to_legacy_json() {
  local input_path="$1"
  jq '
    if has("fields") then
      .
    else
    def issue: (.data[0] // .data);
    issue as $i
    | {
        key: $i.key,
        id: $i.id,
        self: $i.self,
        fields: {
          issuetype: $i.issuetype,
          summary: $i.summary,
          status: $i.status,
          description: $i.description,
          parent: $i.parent,
          assignee: $i.assignee,
          priority: $i.priority,
          comment: (
            if ($i.comment // null) != null then
              $i.comment
            elif ($i.comments // null) != null then
              {
                comments: $i.comments,
                total: ($i.comments | length),
                maxResults: ($i.comments | length)
              }
            else
              null
            end
          )
        }
        | with_entries(select(.value != null))
      }
    end
  ' "$input_path"
}

twg_get_issue_legacy_json() {
  local output_path="$1"
  local key="$2"
  local fields="$3"
  shift 3

  local raw_json
  raw_json="$(mktemp)"
  if ! run_twg_json "$raw_json" jira workitem get "$key" --fields "$fields" "$@"; then
    rm -f "$raw_json"
    return 1
  fi
  normalize_twg_issue_to_legacy_json "$raw_json" >"$output_path"
  rm -f "$raw_json"
}

twg_jira_status_token() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]'
}

twg_jira_status_is_testing_or_later() {
  local status_token
  status_token="$(twg_jira_status_token "$1")"
  case "$status_token" in
    readyfortest|readyfortesting|intesting|testing|testdone|readytoprod|designreview|businesstest|resolved|done|closed)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

twg_jira_transition_to_first_available_status() {
  local output_path="$1"
  local key="$2"
  shift 2

  local transitions_json
  transitions_json="$(mktemp)"
  if ! run_twg_json "$transitions_json" jira workitem transition --id "$key"; then
    rm -f "$transitions_json"
    return 1
  fi

  local target_name transition_id desired_status
  for desired_status in "$@"; do
    target_name="$desired_status"
    transition_id="$(
      jq -r --arg target "$desired_status" '
        def norm: ascii_downcase | gsub("[^a-z0-9]"; "");
        first(
          .data.transitions[]
          | select(((.toName // "") | norm) == ($target | norm) or ((.name // "") | norm) == ($target | norm))
          | .id
        ) // ""
      ' "$transitions_json"
    )"
    if [[ -n "$transition_id" ]]; then
      if run_twg_json "$output_path" jira workitem transition --id "$key" --transition-id "$transition_id"; then
        rm -f "$transitions_json"
        printf '%s\n' "$target_name"
        return 0
      fi
      rm -f "$transitions_json"
      return 1
    fi
  done

  echo "ERROR: none of the requested transitions is available for $key: $*" >&2
  echo "Available transitions:" >&2
  jq -r '.data.transitions[]? | "  - \(.name // "") -> \(.toName // "") [\(.id // "")]"' "$transitions_json" >&2
  rm -f "$transitions_json"
  return 2
}

twg_query_issues_legacy_json() {
  local output_path="$1"
  local jql="$2"
  local fields="${3:-}"

  local raw_json
  raw_json="$(mktemp)"
  if ! run_twg_json "$raw_json" jira workitem query --jql "$jql" --first 100; then
    rm -f "$raw_json"
    return 1
  fi
  jq '
    if type == "array" then
      map(
        if has("fields") then
          .
        else
          {
            key: .key,
            id: .id,
            self: .self,
            fields: ({
              issuetype: .issuetype,
              summary: .summary,
              status: .status,
              description: .description,
              parent: .parent,
              assignee: .assignee,
              priority: .priority
            } | with_entries(select(.value != null)))
          }
        end
      )
    else
    (.data.issues // .data.items // .data // [])
    | map({
        key: .key,
        id: .id,
        self: .self,
        fields: ({
          issuetype: .issuetype,
          summary: .summary,
          status: .status,
          description: .description,
          parent: .parent,
          assignee: .assignee,
          priority: .priority
        } | with_entries(select(.value != null)))
      })
    end
  ' "$raw_json" >"$output_path"
  rm -f "$raw_json"
}
