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
            "- Task artifacts and generated outputs: `{task_artifacts_root}`",
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
            "- Documentation guide: `{task_repo_root}/DOCUMENTATION_GUIDE.md` when present",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and verification outputs: `{task_artifacts_root}`",
            "- Build/test/lint wrappers: `{repo_root}/scripts/run-build.sh`, `{repo_root}/scripts/run-test.sh`, `{repo_root}/scripts/run-lint.sh`",
            "- Platform-native verification phases: `{repo_root}/scripts/ios-*.sh`, `{repo_root}/scripts/android-*.sh`",
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
    if role_name == "convention-reviewer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Diff input: `{task_snapshot_root}/spec/diff.md`",
            "- Review report directory and current pass target: `{task_snapshot_root}/review/convention`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and review outputs: `{task_artifacts_root}`",
            "- Primary project guidance: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/README.md`",
        ]
    if role_name == "requirements-reviewer":
        return [
            "- Task repo worktree: `{task_repo_root}`",
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Canonical task ordering: `{task_snapshot_root}/statuses.md`",
            "- Task description and comments: `{task_snapshot_root}/description.md`, `{task_snapshot_root}/comments.md`",
            "- Diff input: `{task_snapshot_root}/spec/diff.md`",
            "- Review report directory and current pass target: `{task_snapshot_root}/review/requirements`",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task-local temp root: `{task_tmp_root}`",
            "- Task artifacts and review outputs: `{task_artifacts_root}`",
            "- Primary project guidance: `{task_repo_root}/CLAUDE.md`, `{task_repo_root}/README.md`",
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
    if role_name == "documentation-reviewer":
        return [
            "- Task snapshot metadata: `{task_snapshot_root}`",
            "- Documentation diff input: `{task_snapshot_root}/spec/doc-diff.md`",
            "- Full diff input: `{task_snapshot_root}/spec/full-diff.md`",
            "- Deterministic documentation precheck: `{task_snapshot_root}/spec/documentation-precheck.md`",
            "- Task repo worktree: `{task_repo_root}`",
            "- Documentation guide: `{task_repo_root}/DOCUMENTATION_GUIDE.md` when present",
            "- Task-local runtime root: `{task_runtime_root}`",
            "- Task artifacts and documentation review outputs: `{task_artifacts_root}`",
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
            "- Work only on the current routed task. Do not inspect or modify unrelated task/session state.",
        ]
    if role_name == "bug-fixer":
        return [
            "- You execute unified bug work for one bug task session.",
            "- You retain bug-specific context across analysis, fix, and follow-up rounds.",
            "- Work only on the current routed task. Do not inspect or modify unrelated task/session state.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- You execute routed verification work for one task session.",
            "- You validate changes through deterministic checks and review the resulting evidence.",
            "- Do not modify product code; report verification results and required corrections only.",
        ]
    if role_name == "code-reviewer":
        return [
            "- You execute routed code review work for one task session.",
            "- You review only the routed task changes and produce compact review outcomes plus a durable structured review report for the current pass.",
            "- For real findings, include optional `Evidence`, `Suggested approach`, and `Test expectations` sections only when they are grounded by the touched diff and likely to help the next correction pass.",
            "- Do not run build, test, or lint verification. Submit your review result; verification happens after this role finishes.",
            "- Across repeated passes, retain reviewer context for the same task instead of reinitializing from zero.",
        ]
    if role_name == "convention-reviewer":
        return [
            "- You execute one bounded convention review pass for one task session.",
            "- You review the routed diff against local repository conventions and produce a durable structured report for the current pass.",
            "- You do not review requirement completeness or broad maintainability cleanup.",
            "- Do not run build, test, or lint verification. Submit your review result; verification happens after this role finishes.",
        ]
    if role_name == "requirements-reviewer":
        return [
            "- You execute one bounded requirements review pass for one task session.",
            "- You review whether the current implementation satisfies the cumulative Jira task/subtask scope in canonical statuses order.",
            "- You protect earlier accepted subtasks from regressions unless a newer Jira follow-up explicitly overrides them.",
            "- You do not review convention/style/documentation hygiene unless it directly breaks behavior or coverage.",
            "- Do not run build, test, or lint verification. Submit your review result; verification happens after this role finishes.",
        ]
    if role_name == "code-scout":
        return [
            "- You execute one bounded Code Scout pass for one completed coding session.",
            "- You inspect only the changed code area for real maintainability improvements and do not modify product code yourself.",
            "- For real findings, include optional `Evidence`, `Suggested approach`, and `Test expectations` sections only when they are grounded by the touched code and likely to help the next cleanup pass.",
            "- You stop after writing either a clean result or structured findings for operator review.",
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- You execute one bounded documentation-harvest task for one completed task session.",
            "- You update or create feature-level README files from grounded diff evidence in the task worktree.",
            "- You use the repository documentation guide when present and fall back to stable behavior/contract documentation rules when it is absent.",
            "- You stop after committing only the documentation updates and reporting the compact result summary.",
        ]
    if role_name == "documentation-reviewer":
        return [
            "- You execute one bounded documentation quality review for one completed documentation pass.",
            "- You verify production docs and doc comments against the repository documentation guide when present, otherwise against stable behavior/contract documentation rules.",
            "- You do not edit files; report either a clean pass, a skip, or actionable documentation-only findings.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- You execute one bounded proposal/context preparation task for one story session.",
            "- Produce `spec/proposal.md` plus the `spec/context/` package, submit the result, then stop.",
            "- Read `description.md` and `comments.md` first; when they conflict, treat `comments.md` as the fresher source and record the conflict explicitly in the proposal.",
            "- Resolve explicit HTTP/HTTPS links from the snapshot as operator-provided context references rather than mandatory fetched inputs.",
            "- Resolve only explicit local file references from the snapshot before broadening to any narrower repo exploration.",
            "- Do not continue into requirements, decomposition, or implementation work.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- You execute one bounded requirements-clarification task for one story session.",
            "- When critical ambiguity remains, you must ask the operator directly in the live session and continue after the operator replies.",
            "- Produce the routed requirements result, submit it, then stop.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- You execute one bounded acceptance-criteria preparation task for one story session.",
            "- Produce the routed acceptance-criteria result, submit it, then stop.",
            "- Do not continue into constraints, decomposition, or implementation work.",
        ]
    if role_name == "constraints-worker":
        return [
            "- You execute one bounded constraints-preparation task for one story session.",
            "- Produce the routed constraints result, submit it, then stop.",
            "- Do not continue into decomposition or implementation work.",
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- You execute one bounded planning-verification task for one story session.",
            "- Produce the routed verification result and then stop only when the planning package is actually clean; if critical blockers remain, continue after the operator replies in the same live session.",
            "- Do not continue into decomposition or implementation work.",
        ]
    if role_name == "task-decomposer-worker":
        return [
            "- You execute one bounded task-decomposition task for one story session.",
            "- Produce the routed decomposition result, submit it, then stop.",
            "- Do not continue into implementation work.",
        ]
    return [
        "- You operate only on routed work for one task session.",
        "- You should not infer responsibilities outside your current role.",
    ]


def _role_operating_rules(role_name: str) -> list[str]:
    if role_name == "implementer":
        return [
            "- Read all routed spec inputs before writing code.",
            "- For implementation work, read the task snapshot inputs (`description.md`, `comments.md`, and `spec/diff.md`) when they exist before concluding that no concrete work was routed.",
            "- Treat repository conventions as the default implementation contract. A task spec, planning artifact, or decomposition note overrides a local convention only when Jira/operator input explicitly states that this task is intentionally changing that convention.",
            "- If a routed spec conflicts with established local convention without an explicit convention-change instruction, follow the convention when the semantic requirement can still be satisfied; escalate only when the conflict changes product behavior or cannot be resolved locally.",
            "- When you add or edit tests, follow the existing local test conventions in the touched area instead of inventing new fixture, assertion, naming, or helper patterns.",
            "- Use the closest existing test file as the reference implementation for structure, setup, and expectations before introducing a new style.",
            "- Use RAG tools first for code exploration; fall back to filesystem search only for structural queries.",
            "- Keep implementation aligned to the routed task or correction scope, but make any adjacent code changes that are necessary to fix the real root cause cleanly and avoid regressions.",
            "- If a routed correction conflicts with already-authoritative product/operator direction or cannot be resolved safely without a fresh operator decision, stop and escalate instead of forcing a local patch.",
            "- In that escalation, provide a reasoned disagreement package: the concrete conflict, the premise you believe is wrong or outdated, the technical direction you recommend instead, and the exact operator decision needed.",
            "- Do not run build, test, or lint verification. Submit your implementation result; verification happens after this role finishes.",
        ]
    if role_name == "bug-fixer":
        return [
            "- Preserve bug-specific context across analysis, fix, and follow-up rounds.",
            "- Support the routed bug modes inside one runtime identity: `analysis-only` before code changes, then `fix-only` for implementation, correction, and follow-up rounds.",
            "- In implementation and fix-only rounds, read `description.md`, `comments.md`, and `spec/diff.md` when they exist before deciding there is no concrete bug-fix work to perform.",
            "- Treat repository conventions as the default implementation contract. A task spec or follow-up overrides a local convention only when Jira/operator input explicitly states that this task is intentionally changing that convention.",
            "- In `analysis-only` mode, read task description/comments first, investigate the code path, write or update `spec/bug-analysis.md`, and stop before product-code changes when confidence is low or when the routed pass is analysis-only.",
            "- In `fix-only` mode, read the saved `spec/bug-analysis.md` first and treat it as the durable bug context unless a routed issues file or follow-up comments narrow the scope further.",
            "- If an `Issues file:` path is routed, treat it as the primary scoped input for this round, but make any adjacent code changes that are necessary to fix the root cause cleanly and avoid regressions.",
            "- If `Follow-up comments:` are routed, prioritize the latest follow-up comments over redoing the original bug analysis from scratch.",
            "- Keep the current bug task scoped to the routed pass, saved bug analysis, and latest follow-up context.",
            "- If a routed correction conflicts with already-authoritative product/operator direction or cannot be resolved safely without a fresh operator decision, stop and escalate instead of forcing a local patch.",
            "- In that escalation, provide a reasoned disagreement package: the concrete conflict, the premise you believe is wrong or outdated, the technical direction you recommend instead, and the exact operator decision needed.",
            "- Do not run build, test, or lint verification. Submit your implementation result; verification happens after this role finishes.",
            "- Write or update `spec/bug-analysis.md` in bug-analysis rounds.",
        ]
    if role_name == "verification-coordinator":
        return [
            "- Run only deterministic verification work for the routed task session.",
            "- Start from the routed verification strategy file when it is provided and preserve its selected gate unless a clear repo signal forces a broader fallback.",
            "- When the routed strategy includes iOS impact mapping, treat that mapping as the primary source for impacted areas, preferred schemes, test targets, and fallback confidence instead of re-deriving repository scope heuristically.",
            "- When the routed strategy provides explicit commands, execute that routed sequence as written instead of reconstructing the gate manually.",
            "- For iOS strategies, prefer the routed `bash scripts/ios-verify.sh \"$SDD_FACTORY_TASK_KEY\"` command or the routed iOS phase commands over manually invoking `run-test.sh` plus `run-lint.sh` separately.",
            "- For Android strategies, prefer the routed `bash scripts/android-verify.sh \"$SDD_FACTORY_TASK_KEY\"` command or the routed Android phase commands over manually invoking `run-test.sh` plus `run-lint.sh` separately.",
            "- When no explicit strategy commands are provided, treat `run-test.sh` and `run-lint.sh` as the fallback workflow-level verification gate and do not run `run-build.sh` here.",
            "- If the routed strategy explicitly marks the task as docs-only with no code-verification phases, preserve that skip decision and explain it in the verification report instead of forcing a build/test pass.",
            "- For iOS tasks, prefer the routed task-local verification context paths for DerivedData, xcresult bundles, cloned source packages, and logs instead of relying on shared global Xcode state.",
            "- For Android tasks, prefer the routed task-local Gradle user home and verification log paths instead of relying on shared global Gradle state.",
            "- Always treat each verification round as a fresh deterministic gate and refresh the verification evidence.",
            "- Always write or refresh `spec/final-verification.md` for the current round; on failure include the failed checks and their relevant command output.",
            "- Keep the role evidence-first: summarize failures, but do not attempt fixes.",
            "- Do not modify product code.",
        ]
    if role_name == "code-reviewer":
        return [
            "- Review only the routed diff and conventions relevant to that diff.",
            "- Write or refresh the structured review report for the current pass before you finish.",
            "- Structure real findings with enough direction to act: include the finding title or affected file/component, why it matters, required direction, and non-goals when they help keep the fix scoped.",
            "- Read previous review reports from the immediate correction chain first when they are provided and do not re-flag the same issue twice.",
            "- Read only the convention files relevant to the touched diff area; do not broaden the review scope speculatively.",
            "- When the diff adds or edits tests, verify that the tests follow the existing local test conventions for naming, fixtures, setup, helpers, and assertion style in that area.",
            "- Treat unnecessary test self-activity or ad-hoc testing patterns as real review findings when they diverge from established project conventions.",
            "- Keep outputs compact and fixer-oriented.",
            "- Do not re-flag issues that were already raised in the immediate correction chain when that context is provided.",
            "- Treat similar issues that return after later follow-up, subtask, or implementation work as normal failed review findings, not blocked review cycles.",
        ]
    if role_name == "convention-reviewer":
        return [
            "- Read the routed diff first, then inspect only touched full files and directly relevant local convention sources.",
            "- Primary project guidance: read `CLAUDE.md` when present, read `README.md` when present, and follow their links to relevant local convention docs/templates for the touched diff.",
            "- Infer conventions from the repository context; do not import platform-, language-, or architecture-specific rules from this factory repo.",
            "- Treat local repository convention sources and stable nearby precedent as authoritative over downstream spec/decomposition text unless Jira/operator input explicitly says this task is meant to change the convention.",
            "- If a task intentionally changes a convention, expect the diff to update the relevant convention source or adjacent canonical examples; otherwise report the inconsistency instead of accepting a silent convention override.",
            "- Check local structure, naming, layering, test style, fixtures, helpers, established APIs, and error handling only when grounded by touched files.",
            "- Write or refresh the structured convention review report before finishing.",
            "- Report findings only when they are concrete, actionable, and likely to improve consistency of the submitted diff.",
            "- Keep outputs compact and fixer-oriented.",
            "- Do not re-flag issues already raised in the immediate correction chain when that context is provided.",
            "- Treat similar issues that return after later follow-up, subtask, or implementation work as normal failed review findings, not blocked review cycles.",
        ]
    if role_name == "requirements-reviewer":
        return [
            "- Read `statuses.md` first when present and use Jira keys plus their order there as the canonical source of task/subtask ordering.",
            "- Read root description/comments and per-key Jira description/comments in statuses order; newer Jira follow-ups override older scope only on explicit conflict.",
            "- Treat earlier accepted subtasks as a regression contract unless a newer Jira follow-up explicitly overrides them.",
            "- Do not use `plan/index.md` or `plan/NN-*.md` as authoritative follow-up inputs.",
            "- Do not treat spec/decomposition wording as an implicit override of local code conventions. A convention override is authoritative only when Jira/operator input explicitly says the task intentionally changes that convention.",
            "- When a semantic requirement can be satisfied while following local convention, accept the convention-aligned implementation rather than requiring a literal spec shape that exists only in downstream planning artifacts.",
            "- Treat exact names, tags, string constants, analytics keys, and identifiers from downstream specs/decomposition as derived guidance unless they are explicitly present in Jira/operator input or already accepted in an earlier completed subtask.",
            "- When a derived exact value conflicts with local repository convention or a convention-review correction, do not require restoring the derived value; review the requirement at the semantic level instead.",
            "- Review cumulative behavior, missing requirements, edge cases, acceptance gaps, and tests that should protect the requirement.",
            "- Avoid convention/style/documentation findings unless they directly cause a behavior or coverage failure.",
            "- Write or refresh the structured requirements review report before finishing.",
            "- Keep outputs compact and fixer-oriented.",
            "- Do not re-flag issues already raised in the immediate correction chain when that context is provided.",
            "- Treat similar issues that return after later follow-up, subtask, or implementation work as normal failed review findings, not blocked review cycles.",
        ]
    if role_name == "code-scout":
        return [
            "- Start from `spec/diff.md` and use it to decide whether the branch has strong enough maintainability signals for a Code Scout pass.",
            "- Read full current files only for the most promising changed code paths; do not analyze raw diff hunks alone.",
            "- If signals are weak or no real findings exist, return a clean Code Scout result and stop.",
            "- If real maintainability findings exist, write `spec/findings.md`, summarize the findings, and stop without changing product code.",
            "- Structure each finding with a clear title, why it matters, required direction, and non-goals; affected files and additional context should be included when grounded by the diff.",
            "- Skip style nits, convention-only feedback, and speculative improvements.",
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- Treat this role as a bounded one-shot worker: generate or refresh `spec/full-diff.md`, update grounded feature-level README targets, and exit.",
            "- Use `spec/full-diff.md` as the primary source of truth for branch changes and prefer changed README/doc anchors over broad repo scanning.",
            "- Use `DOCUMENTATION_GUIDE.md` when present; otherwise write durable behavior and contract documentation without preserving task/review history.",
            "- Read selectively and skip ambiguous multi-feature diffs instead of inventing a single arbitrary documentation target.",
            "- Commit only the README/doc files you changed, then report a compact summary.",
        ]
    if role_name == "documentation-reviewer":
        return [
            "- Treat this role as a bounded one-shot reviewer: inspect documentation changes, write a terminal result, and exit.",
            "- Start from `spec/documentation-precheck.md`, `spec/doc-diff.md`, `spec/full-diff.md`, and `DOCUMENTATION_GUIDE.md` when present; otherwise apply the stable documentation rules from this prompt.",
            "- Review production README files, docs, and public/doc comments for stable-contract documentation quality.",
            "- Flag Jira/review history, file inventories in module READMEs, duplicated explanations, stale implementation narration, and documentation that preserves how the task was implemented instead of the durable behavior.",
            "- Do not edit files; keep findings scoped to documentation/comment changes.",
            "- Emit `skipped_not_needed` only when there are no documentation/comment changes to review.",
        ]
    if role_name == "proposal-context-worker":
        return [
            "- Treat this role as a bounded one-shot worker: produce `spec/proposal.md` and the `spec/context/` package, then exit.",
            "- Always write `spec/context/feature-overview.md`; write the other `spec/context/*` files only when they contain concrete task-specific findings.",
            "- Read snapshot description/comments first; use repo sources and local docs only when they are directly needed to ground the proposal/context outputs.",
            "- Keep the output compact and reusable for the next routed planning step.",
        ]
    if role_name == "requirements-clarifier-worker":
        return [
            "- Treat this role as a bounded worker for one story session: clarify requirements, ask live follow-up questions when needed, then write the routed result and exit.",
            "- Start from `spec/proposal.md` and `spec/context/feature-overview.md`; read the rest of `spec/context/*` selectively when it materially helps resolve ambiguity.",
            "- Preserve existing repository conventions as default constraints. Do not phrase a requirement as a convention override unless Jira/operator input explicitly asks to change that convention.",
            "- Do not invent exact names, tags, string constants, analytics keys, or identifiers when the source only asks for stable values; ground them in explicit Jira/operator input or existing repository convention, otherwise leave the requirement semantic and ask the operator when the value itself matters.",
            "- If a risky ambiguity remains, ask the operator directly in the live session instead of guessing.",
            "- Keep the output compact and reusable for the next routed planning step.",
        ]
    if role_name == "acceptance-criteria-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare acceptance criteria, write the routed result, and exit.",
            "- Start from `spec/proposal.md`, clarified requirements, and `spec/context/feature-overview.md`; read other context files only when they materially affect behavior coverage.",
            "- Write independently testable criteria in WHEN-THEN-SHALL form and cover happy paths, edge cases, and error scenarios from the clarified requirements.",
            "- Ensure each meaningful decision from the clarified requirements is covered by at least one criterion before finishing.",
            "- Keep the output compact and reusable for the next routed planning step.",
        ]
    if role_name == "constraints-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare implementation constraints, write the routed result, and exit.",
            "- Start from the proposal, clarified requirements, acceptance criteria, and `spec/context/feature-overview.md`; use `implementation-patterns.md`, `documentation.md`, and `preconditions.md` when they materially shape constraints.",
            "- Treat `spec/context/project.md` as architectural ground truth, cite it instead of restating generic conventions, and keep constraints task-specific and grounded.",
            "- State convention changes only when Jira/operator input explicitly requests them; otherwise constrain implementation to satisfy the requirement within existing local conventions.",
            "- For concrete names, tags, string constants, analytics keys, and identifiers, constrain the implementation to explicit Jira/operator values or local repository convention instead of inventing new literal values in the constraints.",
            "- Express constraints as imperative MUST, MUST NOT, and SHOULD statements across only the applicable categories.",
            "- Keep the output compact and reusable for the next routed planning step.",
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- Treat this role as a bounded planning verifier: verify the assembled planning package, write the routed result, and exit only when the package is actually clean.",
            "- Start from the proposal, requirements, acceptance criteria, constraints, and `spec/context/feature-overview.md`; use the rest of `spec/context/*` selectively when checking planning coherence.",
            "- Do not treat a missing `spec/spec_verification.md` as a blocker before the verification pass completes; that file is your output when the package is clean.",
            "- Treat `spec/context/documentation.md`, `implementation-patterns.md`, `preconditions.md`, and `relevant-code.md` as optional supporting inputs unless a specific planning claim depends on them.",
            "- Flag planning claims that silently override local repository conventions without explicit Jira/operator authority and without updating the relevant convention source or canonical examples.",
            "- Flag or fix planning package claims that invent exact names, tags, string constants, analytics keys, or identifiers without grounding in Jira/operator input or local repository convention.",
            "- Fix non-blocking issues autonomously. If critical blockers remain, summarize them clearly, ask the operator direct live questions, and continue verification after answers arrive.",
            "- Keep the output compact and downstream-oriented so decomposition can start from a verified planning package instead of rediscovering planning gaps.",
        ]
    if role_name == "task-decomposer-worker":
        return [
            "- Treat this role as a bounded one-shot worker: prepare task decomposition, write the routed result, and exit.",
            "- Start from the verified planning package and `spec/context/feature-overview.md`; use `relevant-code.md` and `implementation-patterns.md` when they materially affect task boundaries.",
            "- Write the decomposition package directly into `plan/` inside your role workspace: mandatory machine-readable `plan/tasks.json` plus self-contained Markdown task files for each task; `plan/index.md` is optional companion context only.",
            "- Keep ordering in filenames like `plan/NN-*.md`, but do not prefix the human-facing task titles or Markdown headings with `Task 01`, `Task 02`, and similar numbering.",
            "- `plan/tasks.json` is the source of truth for Jira subtask materialization. It must be valid JSON with `{ \"version\": 1, \"tasks\": [{ \"order\": 1, \"filename\": \"01-something.md\", \"title\": \"Human title\" }] }` and every listed file must exist.",
            "- Keep the routed output minimal: return a concise summary only after the `plan/` package is fully written.",
            "- Make every task file self-contained: copy relevant acceptance criteria, constraints, exact repo file paths, and validation steps into the task instead of pointing back to spec files.",
            "- Do not convert a semantic requirement into a convention override. If the verified planning package does not explicitly authorize changing a local convention, decompose the work so implementation follows the existing convention.",
            "- Do not introduce exact names, tags, string constants, analytics keys, or identifiers that are absent from the verified planning package; if a stable value is required but not specified, instruct implementation to follow the local repository convention.",
            "- Keep the output compact and downstream-oriented so execution can start from an explicit decomposition instead of implicit planning assumptions.",
        ]
    return [
        "- Stay within the routed task scope and use ROUTED_WORK.md as the active payload.",
    ]


def _terminal_result_contract(role_name: str) -> list[str]:
    helper = 'bash "$SDD_FACTORY_REPO_ROOT/scripts/write-result.sh"'
    common = [
        "- Replace `<work_item_id>` and `<subtask_key>` with the exact values from `HYDRATION.json` when present.",
        "- Keep summaries short and operator-readable.",
    ]
    if role_name in {"code-reviewer", "convention-reviewer", "requirements-reviewer"}:
        return [
            "- Clean review:",
            f"  `{helper} --work-item-id <work_item_id> --output-type passed --summary \"Review passed\"`",
            "- Review with findings:",
            f"  `{helper} --work-item-id <work_item_id> --output-type failed --summary \"Review found issues\" --issues-markdown-file <path>`",
            "- Non-converging correction loop that genuinely needs operator decision:",
            f"  `{helper} --work-item-id <work_item_id> --output-type blocked_review_cycle --summary \"Review cycle blocked\" --issues-markdown-file <path>`",
            *common,
        ]
    if role_name == "documentation-reviewer":
        return [
            "- Clean documentation review:",
            f"  `{helper} --work-item-id <work_item_id> --output-type passed --summary \"Documentation review passed\"`",
            "- No documentation/comment changes to review:",
            f"  `{helper} --work-item-id <work_item_id> --output-type skipped_not_needed --summary \"No documentation review needed\"`",
            "- Documentation findings:",
            f"  `{helper} --work-item-id <work_item_id> --output-type failed --summary \"Documentation review found issues\" --issues-markdown-file <path>`",
            *common,
        ]
    if role_name == "verification-coordinator":
        return [
            "- Verification passed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --result passed --summary \"Verification passed\"`",
            "- Verification failed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --result failed --summary \"Verification failed\" --failure \"<failed check>\"`",
            "- Non-converging verification loop that genuinely needs operator decision:",
            f"  `{helper} --work-item-id <work_item_id> --output-type blocked_verification_cycle --summary \"Verification cycle blocked\" --details \"<why blocked>\"`",
            *common,
        ]
    if role_name in {"implementer", "bug-fixer"}:
        return [
            "- Implementation completed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --summary \"Implementation completed\"`",
            "- Subtask implementation completed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --subtask-key <subtask_key> --summary \"Subtask completed\"`",
            "- Implementation could not complete:",
            f"  `{helper} --work-item-id <work_item_id> --output-type failed --summary \"Implementation blocked\" --details \"<what prevented completion>\"`",
            *common,
        ]
    if role_name == "code-scout":
        return [
            "- Clean scout pass:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --result clean --summary \"No maintainability findings\"`",
            "- Maintainability findings found:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --result findings_found --findings-count <count> --findings-path <path> --summary \"Maintainability findings found\"`",
            "- Scout not needed for this diff:",
            f"  `{helper} --work-item-id <work_item_id> --output-type skipped_not_needed --result clean --summary \"Scout not needed\"`",
            *common,
        ]
    if role_name == "doc-harvest-worker":
        return [
            "- Documentation updated:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --summary \"Documentation updated\"`",
            "- No documentation update needed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type skipped_not_needed --summary \"No documentation update needed\"`",
            *common,
        ]
    if role_name == "spec-verifier-worker":
        return [
            "- Planning package verified:",
            f"  `{helper} --work-item-id <work_item_id> --output-type passed --summary \"Planning package verified\" --verified-focus \"<verified scope>\"`",
            "- Planning package has blockers:",
            f"  `{helper} --work-item-id <work_item_id> --output-type failed --summary \"Planning verification failed\" --blocker-question \"<question or blocker>\"`",
            *common,
        ]
    if role_name in {
        "proposal-context-worker",
        "requirements-clarifier-worker",
        "acceptance-criteria-worker",
        "constraints-worker",
        "task-decomposer-worker",
    }:
        return [
            "- Planning step completed:",
            f"  `{helper} --work-item-id <work_item_id> --output-type completed --summary \"Planning step completed\"`",
            "- Planning step needs operator input:",
            f"  `{helper} --work-item-id <work_item_id> --output-type failed --summary \"Planning blocked\" --needs-operator-input --blocker-question \"<question>\"`",
            *common,
        ]
    return [
        f"- Use `{helper} --work-item-id <work_item_id> --output-type completed --summary \"Completed\"` for normal completion.",
        *common,
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
    terminal_result_contract = _terminal_result_contract(role_name)
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
            "- Read this file once when the role starts. Do not reread it on every routed work item unless context was compacted or role boundaries are unclear.",
            "- Use HYDRATION.json and routed work instructions as the current task payload.",
            "- Treat this file as durable role context; treat routed handoff prompts as per-work instructions.",
            "- Paths written as `spec/...`, `review/...`, or `plan/...` refer to the task snapshot metadata root listed above, not to this role workspace current directory.",
            "- When hydration or the relevant-path list provides explicit absolute `*_path` values, use those exact paths directly instead of reconstructing task paths relative to the current directory.",
            "- For terminal outcomes, call `bash \"$SDD_FACTORY_REPO_ROOT/scripts/write-result.sh\" --work-item-id <work_item_id> ...` instead of hand-writing JSON or managing terminal files directly.",
            "- For markdown payloads that contain backticks, parentheses, or paths with spaces, write the markdown to a file first and pass it with helper file flags such as `--issues-markdown-file <path>` instead of inline shell arguments.",
            "- Do not call `scripts/write-result.py` directly, do not choose terminal output paths yourself, and do not try to recreate fallback files manually.",
            "- Do not override `SDD_FACTORY_BACKEND_URL`, `SDD_FACTORY_BACKEND_HOST`, or `SDD_FACTORY_BACKEND_PORT`, and do not debug transport or fallback behavior from inside the role.",
            "- When the routed hydration payload includes `work_item_id`, pass that same `work_item_id` into the helper unchanged. When it also includes `subtask_key`, pass that same `subtask_key` unchanged too.",
            "- After the helper exits successfully, stop immediately and do not submit the same work item again.",
            "- If the helper exits non-zero or the routed stage has already moved on, stop and wait for fresh routed work; do not retry through alternate scripts, alternate environment variables, or manual files.",
            "- You may emit `SDD_PROGRESS` for intermediate updates.",
            "- For implementer/bug-fixer live escalations that need an operator decision before the current work item can continue, emit `SDD_ERROR` with `summary`, `details`, and `needs_operator_input: true` instead of forcing a terminal completion/error result.",
            "- When that escalation is a reasoned disagreement with a correction or review request, also include `conflict_point`, `reviewer_premise`, `preferred_direction`, `requested_decision`, and optional `supporting_evidence` when they are grounded.",
            "- If you also emit terminal completion text directly, use the exact `SDD_OUTPUT: {...}` format described here.",
            "",
            "## Operating Rules",
            "",
            *operating_rules,
            "",
            "## Terminal Result Contract",
            "",
            *terminal_result_contract,
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
