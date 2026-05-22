"""Persistent role workspace scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True, slots=True)
class RoleWorkspace:
    role_name: str
    directory: Path
    agents_path: Path
    claude_path: Path


def _task_snapshot_root(workdir_root: Path, task_key: str) -> Path:
    return workdir_root / task_key


def _task_repo_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "repo"


def _task_runtime_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "runtime"


def _task_tmp_root(workdir_root: Path, task_key: str) -> Path:
    return _task_snapshot_root(workdir_root, task_key) / "tmp"


def _task_artifacts_root(workdir_root: Path, task_key: str) -> Path:
    return workdir_root / "factory-artifacts" / task_key


def _role_relevant_paths(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and coordinator outputs: `{task_artifacts_root}`",
            "- Main repo scripts: `{repo_root}/scripts`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "bug-fixer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Task description and comments: `{task_snapshot_root}/description.md`, `{task_snapshot_root}/comments.md`",
            "- Bug analysis report target: `{task_snapshot_root}/spec/bug-analysis.md`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and bug analysis outputs: `{task_artifacts_root}`",
            "- Main repo scripts: `{repo_root}/scripts`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and verification outputs: `{task_artifacts_root}`",
            "- Build/test/lint wrappers: `{repo_root}/scripts/run-build.sh`, `{repo_root}/scripts/run-test.sh`, `{repo_root}/scripts/run-lint.sh`",
            "- Final verification report target: `{task_snapshot_root}/spec/final-verification.md`",
            "- Verification strategy input: `{task_snapshot_root}/spec/verification-strategy.json`",
        ]
    if role_name == "code-reviewer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Review report directory and current pass target: `{task_snapshot_root}/review`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and review outputs: `{task_artifacts_root}`",
            "- Project conventions: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "code-scout":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Diff input: `{task_snapshot_root}/spec/diff.md`",
            "- Findings target: `{task_snapshot_root}/spec/findings.md`",
            "- Deferred findings input: `{task_snapshot_root}/spec/scout-deferred.md`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "mr-comments-analyst-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Raw MR comments input: `{task_artifacts_root}/mr-followup`",
            "- Follow-up plan directory: `{task_snapshot_root}/plan`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Diff source of truth: `{task_snapshot_root}/spec/full-diff.md`",
            "- Changed-doc targets inside the task repo worktree: `{task_repo_root}`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and documentation outputs: `{task_artifacts_root}`",
            "- Main repo diff helper: `{repo_root}/scripts/generate-diff.sh`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Required snapshot inputs: `{task_snapshot_root}/description.md`, `{task_snapshot_root}/comments.md`",
            "- Proposal target: `{task_snapshot_root}/spec/proposal.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Required context output: `{task_snapshot_root}/spec/context/feature-overview.md`",
            "- Optional context outputs: `{task_snapshot_root}/spec/context/relevant-code.md`, `{task_snapshot_root}/spec/context/documentation.md`, `{task_snapshot_root}/spec/context/implementation-patterns.md`, `{task_snapshot_root}/spec/context/preconditions.md`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements target: `{task_snapshot_root}/spec/requirements.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements input: `{task_snapshot_root}/spec/requirements.md`",
            "- Acceptance criteria target: `{task_snapshot_root}/spec/acceptance_criteria.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "constraints-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements input: `{task_snapshot_root}/spec/requirements.md`",
            "- Acceptance criteria input: `{task_snapshot_root}/spec/acceptance_criteria.md`",
            "- Constraints target: `{task_snapshot_root}/spec/constraints.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements input: `{task_snapshot_root}/spec/requirements.md`",
            "- Acceptance criteria input: `{task_snapshot_root}/spec/acceptance_criteria.md`",
            "- Constraints input: `{task_snapshot_root}/spec/constraints.md`",
            "- Verification target: `{task_snapshot_root}/spec/spec_verification.md`",
            "- Context directory: `{task_snapshot_root}/spec/context`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    if role_name == "task-decomposer-worker":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Proposal input: `{task_snapshot_root}/spec/proposal.md`",
            "- Requirements input: `{task_snapshot_root}/spec/requirements.md`",
            "- Acceptance criteria input: `{task_snapshot_root}/spec/acceptance_criteria.md`",
            "- Constraints input: `{task_snapshot_root}/spec/constraints.md`",
            "- Planning verification input: `{task_snapshot_root}/spec/spec_verification.md`",
            "- Decomposition target: `{task_snapshot_root}/spec/decomposition.md`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Project conventions and templates: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/.claude/`",
        ]
    return [
        "- Task snapshot metadata: `{task_snapshot_root}`",
        "- Task artifacts: `{task_artifacts_root}`",
        "- Main repo scripts: `{repo_root}/scripts`",
    ]


def _role_responsibility(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- You execute routed implementation work for one task session.",
            "- You focus only on the currently assigned work item.",
            "- You should not reason about other agents or hidden orchestration concerns.",
        ]
    if role_name == "bug-fixer":
        return [
            "- You execute unified bug work for one bug task session.",
            "- You retain bug-specific context across analysis, fix, and follow-up rounds.",
            "- You should not reason about other agents or hidden orchestration concerns.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- You execute routed verification work for one task session.",
            "- You validate changes through deterministic checks and review the resulting evidence.",
            "- You should not take ownership of implementation work except through explicit coordinator routing.",
        ]
    if role_name == "code-reviewer":
        return [
            "- You execute routed code review work for one task session.",
            "- You review only the routed task changes and produce compact review outcomes plus a durable structured review report for the current pass.",
            "- Across repeated passes, retain reviewer context for the same task instead of reinitializing from zero.",
        ]
    if role_name == "code-scout":
        return [
            "- You execute one bounded Boy Scout pass for one completed coding session.",
            "- You inspect only the changed code area for real maintainability improvements and do not modify product code yourself.",
            "- You stop after writing either a clean result or structured findings for operator review.",
        ]
    if role_name == "mr-comments-analyst-worker":
        return [
            "- You execute one bounded MR review analysis task for one task session.",
            "- You transform unresolved MR comments into an actionable grouped follow-up plan package for the implementer.",
            "- You stop after writing the follow-up plan package and the routed summary; you do not remain the owner of later implementation work.",
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- You execute one bounded documentation-harvest task for one completed task session.",
            "- You update or create feature-level README files from grounded diff evidence in the task worktree.",
            "- You stop after committing only the documentation updates and reporting the compact result summary.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- You execute one bounded proposal/context preparation task for one story session.",
            "- Produce `spec/proposal.md` plus the `spec/context/` package, then stop; you do not remain the owner of later planning or implementation work.",
            "- Read `description.md` and `comments.md` first; when they conflict, treat `comments.md` as the fresher source and record the conflict explicitly in the proposal.",
            "- Resolve explicit HTTP/HTTPS links from the snapshot; use Notion MCP for `notion.so` content, and otherwise treat non-Notion external links as operator-provided context references rather than mandatory fetched inputs.",
            "- Resolve only explicit local file references from the snapshot before broadening to any narrower repo exploration.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- You execute one bounded requirements-clarification task for one story session.",
            "- When critical ambiguity remains, you must ask the operator directly in the live session and continue after the operator replies.",
            "- Produce the routed requirements result and then stop; you do not remain the owner of later planning or implementation work.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- You execute one bounded acceptance-criteria preparation task for one story session.",
            "- Produce the routed acceptance-criteria result and then stop; you do not remain the owner of later planning or implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "constraints-worker":
        return [
            "- You execute one bounded constraints-preparation task for one story session.",
            "- Produce the routed constraints result and then stop; you do not remain the owner of later planning or implementation work.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- You execute one bounded planning-verification task for one story session.",
            "- Produce the routed verification result and then stop only when the planning package is actually clean; if critical blockers remain, continue after the operator replies in the same live session.",
            "- You should not assume persistence across unrelated tasks or later implementation rounds.",
        ]
    if role_name == "task-decomposer-worker":
        return [
            "- You execute one bounded task-decomposition task for one story session.",
            "- Produce the routed decomposition result and then stop; you do not remain the owner of later implementation or verification work.",
            "- You should not assume persistence across unrelated tasks or later execution rounds.",
        ]
    return [
        "- You operate only on coordinator-routed work for one task session.",
        "- You should not infer responsibilities outside your current role.",
    ]


def _role_operating_rules(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Read all routed spec inputs before writing code.",
            "- For implementation work, read the task snapshot inputs (`description.md`, `comments.md`, and `spec/diff.md`) when they exist before concluding that no concrete work was routed.",
            "- Use RAG tools first for code exploration; fall back to filesystem search only for structural queries.",
            "- If the routed input is a narrow correction pass, keep scope limited to the listed issues unless a tiny directly related change is required.",
            "- Do not run workflow-level `run-build.sh`, `run-test.sh`, or `run-lint.sh` unless the routed work explicitly requires a narrow task-specific check.",
            "- Treat final test+lint verification as deferred to the coordinator.",
        ]
    if role_name == "bug-fixer":
        return [
            "- Preserve bug-specific context across analysis, fix, and follow-up rounds.",
            "- Support the routed bug modes inside one runtime identity: `analysis-only` before code changes, then `fix-only` for implementation, correction, and follow-up rounds.",
            "- In implementation and fix-only rounds, read `description.md`, `comments.md`, and `spec/diff.md` when they exist before deciding there is no concrete bug-fix work to perform.",
            "- In `analysis-only` mode, read task description/comments first, investigate the code path, write or update `spec/bug-analysis.md`, and stop before product-code changes when confidence is low or when the coordinator routed an analysis-only pass.",
            "- In `fix-only` mode, read the saved `spec/bug-analysis.md` first and treat it as the durable bug context unless a routed issues file or follow-up comments narrow the scope further.",
            "- If an `Issues file:` path is routed, treat it as the primary narrow-scope input for this round and keep the fix limited to those listed issues unless a tiny directly-related adjustment is required.",
            "- If `Follow-up comments:` are routed, prioritize the latest follow-up comments over redoing the original bug analysis from scratch.",
            "- Keep the current bug task scoped to the routed pass, saved bug analysis, and latest follow-up context.",
            "- Write or update `spec/bug-analysis.md` in bug-analysis rounds; keep final workflow-level verification deferred to the coordinator.",
            "- Treat final test+lint verification as deferred to the coordinator.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Run only deterministic verification work for the routed task session.",
            "- Start from the routed verification strategy file when it is provided and preserve its selected gate unless a clear repo signal forces a broader fallback.",
            "- When the routed strategy includes iOS impact mapping, treat that mapping as the primary source for impacted areas, preferred schemes, test targets, and fallback confidence instead of re-deriving repository scope heuristically.",
            "- Treat `run-test.sh` and `run-lint.sh` as the workflow-level verification gate. Always run them with the current task key, for example `bash scripts/run-test.sh \"$SDD_FACTORY_TASK_KEY\"` and `bash scripts/run-lint.sh \"$SDD_FACTORY_TASK_KEY\"`; do not run `run-build.sh` here.",
            "- When the routed strategy provides explicit iOS phase commands, prefer executing that routed iOS verification sequence instead of reconstructing the phase order manually.",
            "- If the routed strategy explicitly marks the task as docs-only with no code-verification phases, preserve that skip decision and explain it in the verification report instead of forcing a build/test pass.",
            "- For iOS tasks, prefer the routed task-local verification context paths for DerivedData, xcresult bundles, cloned source packages, and logs instead of relying on shared global Xcode state.",
            "- Always treat each verification round as a fresh deterministic gate and refresh the verification evidence.",
            "- Always write or refresh `spec/final-verification.md` for the current round; on failure include the failed checks and their relevant command output.",
            "- Keep the role evidence-first: summarize failures, but do not attempt fixes.",
            "- Do not modify product code.",
        ]
    if role_name == "code-reviewer":
        return [
            "- Review only the routed diff and conventions relevant to that diff.",
            "- Write or refresh the structured review report for the current pass before you finish.",
            "- Read previous review reports first when they are provided and do not re-flag the same issue twice.",
            "- Read only the convention files relevant to the touched diff area; do not broaden the review scope speculatively.",
            "- Keep outputs compact and fixer-oriented.",
            "- Do not re-flag issues that were already raised in previous review passes when that context is provided.",
        ]
    if role_name == "code-scout":
        return [
            "- Start from `spec/diff.md` and use it to decide whether the branch has strong enough maintainability signals for a Boy Scout pass.",
            "- Read full current files only for the most promising changed code paths; do not analyze raw diff hunks alone.",
            "- If signals are weak or no real findings exist, return a clean Boy Scout result and stop.",
            "- If real maintainability findings exist, write `spec/findings.md`, summarize the findings, and stop without changing product code.",
            "- Skip style nits, convention-only feedback, and speculative improvements.",
        ]
    if role_name == "mr-comments-analyst-worker":
        return [
            "- Treat this role as a bounded one-shot worker: analyze unresolved MR comments, write the grouped follow-up plan package, and exit.",
            "- Start from the latest MR comments artifact, group related discussions into actionable themes, and enrich them with just enough source-code context to make the plan executable.",
            "- Use `spec/context/feature-overview.md` first when it exists and pull in the rest of `spec/context/*` selectively when they clarify the expected pattern.",
            "- Write `plan/index.md` plus one or more `plan/NN-*.md` files only with grounded task-specific content; keep numbering only in filenames, not in human-facing task titles, and do not modify product code.",
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- Treat this role as a bounded one-shot worker: generate or refresh `spec/full-diff.md`, update grounded feature-level README targets, and exit.",
            "- Use `spec/full-diff.md` as the primary source of truth for branch changes and prefer changed README/doc anchors over broad repo scanning.",
            "- Read selectively and skip ambiguous multi-feature diffs instead of inventing a single arbitrary documentation target.",
            "- Commit only the README/doc files you changed, then report a compact summary for the coordinator.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- Treat this role as a bounded one-shot worker: produce `spec/proposal.md` and the `spec/context/` package, then exit.",
            "- Always write `spec/context/feature-overview.md`; write the other `spec/context/*` files only when they contain concrete task-specific findings.",
            "- Read snapshot description/comments first; use repo sources and local docs only when they are directly needed to ground the proposal/context outputs.",
            "- Keep the output compact and downstream-oriented so later story roles can reuse the written context package instead of rediscovering it.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- Treat this role as a bounded worker for one story session: clarify requirements, ask live follow-up questions when needed, then write the routed result and exit.",
            "- Start from `spec/proposal.md` and `spec/context/feature-overview.md`; read the rest of `spec/context/*` selectively when it materially helps resolve ambiguity.",
            "- If a risky ambiguity remains, ask the operator directly in the live session instead of guessing.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than unresolved requirements.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare acceptance criteria, write the routed result, and exit.",
            "- Start from `spec/proposal.md`, clarified requirements, and `spec/context/feature-overview.md`; read other context files only when they materially affect behavior coverage.",
            "- Write independently testable criteria in WHEN-THEN-SHALL form and cover happy paths, edge cases, and error scenarios from the clarified requirements.",
            "- Ensure each meaningful decision from the clarified requirements is covered by at least one criterion before finishing.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than behavioral coverage gaps.",
        ]
    if role_name == "constraints-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare implementation constraints, write the routed result, and exit.",
            "- Start from the proposal, clarified requirements, acceptance criteria, and `spec/context/feature-overview.md`; use `implementation-patterns.md`, `documentation.md`, and `preconditions.md` when they materially shape constraints.",
            "- Treat `spec/context/project.md` as architectural ground truth, cite it instead of restating generic conventions, and keep constraints task-specific and grounded.",
            "- Express constraints as imperative MUST, MUST NOT, and SHOULD statements across only the applicable categories.",
            "- Keep the output compact and downstream-oriented so the later story-spec worker can focus on implementation structure rather than rediscovering constraints.",
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- Treat this role as a bounded planning verifier: verify the assembled planning package, write the routed result, and exit only when the package is actually clean.",
            "- Start from the proposal, requirements, acceptance criteria, constraints, and `spec/context/feature-overview.md`; use the rest of `spec/context/*` selectively when checking planning coherence.",
            "- Do not treat a missing `spec/spec_verification.md` as a blocker before the verification pass completes; that file is your output when the package is clean.",
            "- Treat `spec/context/documentation.md`, `implementation-patterns.md`, `preconditions.md`, and `relevant-code.md` as optional supporting inputs unless a specific planning claim depends on them.",
            "- Fix non-blocking issues autonomously. If critical blockers remain, summarize them clearly, ask the operator direct live questions, and continue verification after answers arrive.",
            "- Keep the output compact and downstream-oriented so decomposition can start from a verified planning package instead of rediscovering planning gaps.",
        ]
    if role_name == "task-decomposer-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare task decomposition, write the routed result, and exit.",
            "- Start from the verified planning package and `spec/context/feature-overview.md`; use `relevant-code.md` and `implementation-patterns.md` when they materially affect task boundaries.",
            "- Write the decomposition package directly into `plan/` inside your role workspace: `plan/index.md` plus self-contained Markdown task files for each task.",
            "- Keep ordering in filenames like `plan/NN-*.md`, but do not prefix the human-facing task titles or Markdown headings with `Task 01`, `Task 02`, and similar numbering.",
            "- Keep the routed output minimal: return a concise summary only after the `plan/` package is fully written.",
            "- Make every task file self-contained: copy relevant acceptance criteria, constraints, exact repo file paths, and validation steps into the task instead of pointing back to spec files.",
            "- Keep the output compact and downstream-oriented so execution can start from an explicit decomposition instead of implicit planning assumptions.",
        ]
    return [
        "- Stay within the routed task scope and use coordinator instructions as the active payload.",
    ]


def build_role_agents_md(
    *,
    role_name: str,
    task_key: str,
    repo_root: Path,
    workdir_root: Path,
    role_directory: Path,
) -> str:
    relevant_paths = [
        line.format(
            repo_root=repo_root,
            task_snapshot_root=_task_snapshot_root(workdir_root, task_key),
            task_repo_root=_task_repo_root(workdir_root, task_key),
            task_runtime_root=_task_runtime_root(workdir_root, task_key),
            task_tmp_root=_task_tmp_root(workdir_root, task_key),
            task_artifacts_root=_task_artifacts_root(workdir_root, task_key),
        )
        for line in _role_relevant_paths(role_name)
    ]
    responsibility = _role_responsibility(role_name)
    operating_rules = _role_operating_rules(role_name)
    return "\n".join(
        [
            f"# {role_name} AGENTS",
            "",
            "## Role",
            "",
            f"- Role name: `{role_name}`",
            f"- Task session: `{task_key}`",
            "",
            "## Responsibility",
            "",
            *responsibility,
            "",
            "## Relevant Paths",
            "",
            *relevant_paths,
            "",
            "## Runtime Rules",
            "",
            "- Start from this role workspace and keep your work scoped to the routed task session.",
            "- Re-read this file after context compaction or if role boundaries become unclear.",
            "- Use coordinator hydration and routed work instructions as the current task payload.",
            "- Treat this file as durable role context; treat routed handoff prompts as per-work instructions.",
            "- Paths written as `spec/...`, `review/...`, or `plan/...` refer to the task snapshot metadata root listed above, not to this role workspace current directory.",
            "- When hydration or the relevant-path list provides explicit absolute `*_path` values, use those exact paths directly instead of reconstructing task paths relative to the current directory.",
            f"- For terminal outcomes, write `RESULT.json` exactly to `{role_directory / 'RESULT.json'}` with a JSON object shaped like `{{\\\"output_type\\\":\\\"completed\\\",\\\"payload\\\":{{...}}}}` before you finish the turn.",
            "- Do not place `RESULT.json` in the task root, `spec/`, `plan/`, or any directory other than that exact terminal result target.",
            "- When the routed hydration payload includes `work_item_id`, echo that same `work_item_id` back inside the terminal payload. When it also includes `subtask_key`, echo that same `subtask_key` back unchanged too.",
            "- You may emit `SDD_PROGRESS` for intermediate updates and `SDD_ERROR` when operator visibility is required.",
            "- If you also emit terminal completion text directly, use the exact `SDD_OUTPUT: {...}` format described by the coordinator.",
            "",
            "## Operating Rules",
            "",
            *operating_rules,
        ]
    ) + "\n"


class RoleWorkspaceManager:
    """Create isolated persistent workspaces for long-running roles."""

    def __init__(self, runtime_root: Path, repo_root: Path, workdir_root: Path) -> None:
        self.runtime_root = runtime_root
        self.repo_root = repo_root
        self.workdir_root = workdir_root

    def session_root(self, task_key: str) -> Path:
        return _task_runtime_root(self.workdir_root, task_key) / "role-workspaces"

    def role_directory(self, task_key: str, role_name: str) -> Path:
        return self.session_root(task_key) / role_name

    def ensure_role_workspace(self, task_key: str, role_name: str) -> RoleWorkspace:
        directory = self.role_directory(task_key, role_name)
        directory.mkdir(parents=True, exist_ok=True)

        agents_path = directory / "AGENTS.md"
        agents_path.write_text(
            build_role_agents_md(
                role_name=role_name,
                task_key=task_key,
                repo_root=self.repo_root,
                workdir_root=self.workdir_root,
                role_directory=directory,
            )
        )

        claude_path = directory / "CLAUDE.md"
        if claude_path.exists() or claude_path.is_symlink():
            claude_path.unlink()
        relative_target = os.path.relpath(agents_path, start=directory)
        claude_path.symlink_to(relative_target)

        return RoleWorkspace(
            role_name=role_name,
            directory=directory,
            agents_path=agents_path,
            claude_path=claude_path,
        )
