# QA mobile e2e workflow

QA Jira keys and URLs start work in the configured e2e project through the existing oneshot or story_full coordinator.
All QA tasks submitted to this factory are mobile tasks. A separate classification gate is not needed.
The main e2e checkout stays on master; snapshot prepares a feature/QA-KEY or bugfix/QA-KEY worktree.
Implementation, convention review, requirements review, verification, correction and delivery use the
normal role lifecycle. The factory never merges the resulting MR.

## Configuration ownership

Operator policy lives in the UI Runtime Defaults panel and `.sdd-factory/settings.local.json`, under
`runtime_defaults.e2e_defaults`: include_smoke, fresh_install, max_tests, run_timeout_seconds,
test_timeout_seconds, failure_reruns. Each verification strategy snapshots these settings.
The time limit covers the complete verification gate, including collection, retries and comparisons.
Fresh-run retries select failed, skipped and unfinished checks; successful checks retain their original
receipts. The full fresh-install pass still selects every required check. Timeout diagnostics name the
exhausted total gate budget, rather than implying that the reserved device was busy.

Machine paths, device identifiers and local ports live in ENV, configured in the operator's ~/.zshrc:

| Variable | Meaning |
|---|---|
| E2E_DIR | Main e2e project checkout |
| E2E_PYTHON | Required verification Python executable; configure its local path in ~/.zshrc |
| E2E_BUILD_ROOT | App artifact store; platform/artifacts/master-SHA.app or .apk and JSON sidecars |
| E2E_IOS_SIMULATOR_UDID | Reserved Appium simulator, separate from TESTING_DEVICE_ID and IOS_RUN_DEVICE_ID |
| SDD_E2E_IOS_SIMULATOR_UDIDS | Dedicated factory pool, comma-separated UUIDs; takes precedence over the shared workspace simulator |
| SDD_E2E_IOS_WDA_PORT_BASE | First WDA port reserved for the pool; slot ports are base plus index |
| SDD_E2E_IOS_MJPEG_PORT_BASE | First MJPEG port reserved for the pool; use a separate non-overlapping range |
| SDD_E2E_IOS_WDA_ROOT | Local WDA cache root; each simulator gets its own subdirectory |
| E2E_ANDROID_AVD | Reserved Appium AVD name |
| E2E_ANDROID_SERIAL | Reserved adb serial; default emulator-5584 |
| ANDROID_HOME | Installed Android SDK path |
| E2E_APPIUM_BIN | Installed Appium executable; otherwise resolved from PATH |
| E2E_APPIUM_PORT | Shared local Appium port; default 4743; iOS pool WDA/MJPEG ports are assigned separately |
| E2E_DEVICE_LOCK_ROOT | Shared Appium device lock directory; default SDD_WORKDIR/.locks/e2e |
| SDD_GITLAB_E2E_PROJECT_PATH | URL-encoded GitLab project path for MR review previews |

Use the same device lock directory as any other local Appium runner using these reserved devices.
Create the dedicated factory simulators on the same installed iOS runtime. SDK versions remain in
dependency manifests; simulator runtime versions are discovered. The pool does not use the shared
workspace simulator. Each slot has its own ios-UUID.lock, WDA/MJPEG ports and derived-data cache.
Concurrent gates select free slots; a full pool waits within the complete gate time limit, rather
than immediately asking the operator to retry. Legacy single-device mode retains its existing lock.
QA launch scripts bind the backend's current pool ENV explicitly and clear removed values, avoiding
stale settings inherited from a reused tmux server. Source ~/.zshrc and restart the backend and idle
QA verifier runtimes after changing machine configuration; never interrupt a running gate to apply it.
Only the leased pool simulator is shut down before unlocking it, after retries and baseline comparisons,
including test failures, timeouts, partial boots and SIGINT/SIGTERM. Collection-only checks do not
boot or stop a simulator. Cleanup outcomes are recorded in ios_simulator_cleanup and the report;
errors preserve evidence and remain in cleanup_warnings. Unit-test and manual inspection
devices are not used. The Android emulator runtime and iOS runtime version are discovered locally.
After an Android runtime gate, the reserved emulator is shut down before releasing its device lock,
including failed runs, timeouts and partially failed boots. Retries and baseline comparisons finish
before shutdown. Collection-only checks do not boot or stop the emulator. Cleanup errors remain in
the verdict and report without discarding test evidence.
Dependency versions belong to `factory/e2e/toolchain.json`, not ENV. Check them with:

```bash
./.venv/bin/python -m factory.e2e.runner doctor
```

Use the dependency versions declared in the manifest and the shared local Appium installation.
Set its executable path in E2E_APPIUM_BIN in ~/.zshrc. Stop the old server
on E2E_APPIUM_PORT before switching versions. The runner rejects a ready server whose version differs
from the manifest rather than reusing an incompatible process.
The shared server must be launched with `--allow-insecure uiautomator2:chromedriver_autodownload`.
The factory adds this scoped permission when starting Appium; `--relaxed-security` is unnecessary.
Appium 3 requires the driver prefix. Android suite capabilities request automatic Chromedriver
downloads, but capabilities alone cannot enable this server permission. Native tests can pass while
WebView tests fail when it is missing. See [Appium server security](https://appium.io/docs/en/3.0/guides/security/).
Doctor checks installed pins and, when a ready server exists, its version and explicit launch flags
using local `lsof`/`ps`. Verification makes the same checks before reusing or accepting a newly started
server. A missing/unscoped permission, a matching `--deny-insecure`, or unavailable process inspection
blocks the gate with an actionable environment error. Restart an incompatible shared server only after
other runs finish; the factory leaves a ready incompatible shared server running.

Run the real gate acceptance in isolated master test worktrees with
`PYTHONPATH=. ./.venv/bin/python factory/acceptance/run-e2e-acceptance.py --platform both --strategy /path/to/task/spec/verification-strategy.json`.
It copies the task-provided execution recipe and support files into an isolated master worktree,
runs the selected checks twice on each platform, validates receipts and retains the report.
It does not mutate Jira or publish MRs. The default regression rail covers lifecycle and failure handling.

The factory executes task-provided commands and verifies their evidence. Its optional pytest evidence
plugin has no project imports. It does not load external workspace docs, skills, configuration or helper
scripts at runtime. Repository layout, smoke identifiers, imports and project configuration are task data.

## Implementation contract

Follow the current project's AGENTS.md/CLAUDE.md, README and nearby tests for code structure,
helpers, locators, waits and fixtures. The task checkout is authoritative for implementation
conventions. This contract defines the factory workflow and verification evidence; task-specific
selectors and application workarounds belong in the task requirements and test code.

Case identifiers, framework conventions and fixture rules come from the project. Local verification
does not authorize external test reporting, CI launches or MR merges. Choose local commands and
disable external reporting using the project's own supported options or task-local integration.

The verification coordinator completes the existing `spec/verification-strategy.json` after reviewing
the current task scope and checkout. Keep the routed work item, baseline SHA, command and snapshotted
policy. Add an `e2e.platforms` execution recipe; there is no separate e2e plan artifact:

```json
{
  "e2e": {
    "platforms": {
      "ios": {
        "collection": ["checks"],
        "tests": ["checks/test_feature.py::test_retained_scenario"],
        "smoke_tests": ["checks/test_smoke.py::test_basic_flow"],
        "removed_tests": ["checks/test_feature.py::test_removed_scenario"],
        "commands": {
          "collect": ["{python}", "-m", "pytest", "-p", "pytest_evidence", "--collect-only", "-q", "{selectors}"],
          "run": ["{python}", "-m", "pytest", "-p", "pytest_evidence", "--junitxml={junit}", "--timeout={test_timeout_seconds}", "{selectors}"]
        },
        "environment": {"PYTHONPATH": "{factory_plugin_dir}"},
        "unset_environment": ["PYTEST_ADDOPTS"]
      }
    },
    "support_files": []
  }
}
```

This fragment illustrates the protocol, not a project layout or default command. Preserve the other
existing fields when adding it. Use the actual project's local commands, collection scope, smoke and
check identifiers. The runner treats identifiers as opaque; it does not scan source decorators or
assume test directories. Android runtime recipes also provide `application_id` from the app/project.

Commands are argv arrays, executed in the current task or pinned baseline checkout without a shell.
Exit code 0 means successful checks, 1 means actual check failures, and other codes mean a runner or
environment failure. A project wrapper may normalize its framework's exit codes to this protocol.
One whole `{selectors}` argument expands into the current check list. Other supported tokens are
`{python}`, `{repo}`, `{task_root}`, `{platform}`, `{device_id}`, `{platform_version}`, `{application_id}`,
`{app_path}`, `{appium_port}`, `{android_sdk}`, `{adb}`, `{factory_plugin_dir}`, `{test_timeout_seconds}`,
`{junit}`, `{collected}` and `{results}`. Environment values use the same tokens. Machine paths and
device/port values come from configured ENV; runtime-discovered versions come from the device.
Map these values to the project's own device/server inputs. Confirm that its client uses the supplied
Appium endpoint instead of a framework default. The generic runtime also publishes
FACTORY_E2E_APPIUM_PORT, FACTORY_E2E_APPIUM_URL and FACTORY_E2E_PLATFORM_VERSION to task adapters.
For dedicated iOS pool sessions, FACTORY_E2E_APPIUM_CAPABILITIES contains a JSON capability object
with the assigned UDID, WDA/MJPEG ports and derived-data path; shutdownOtherSimulators is disabled.
The optional pytest_evidence plugin applies the assigned endpoint and capabilities before creating
the session, overriding framework defaults without importing project configuration. A session connection
failure exits with environment code 2, stopping retries and baseline comparisons. Appium preflight runs
before app installation. Other adapters must consume the assigned endpoint and capabilities explicitly.
The pytest adapter rejects an Appium platformName that differs from the selected platform before any
session request. This requires execution-recipe preparation, with native diagnostic evidence in
FACTORY_E2E_DIAGNOSTIC; fix the project's platform input rather than comparing baseline tests.
Execution tokens {wda_local_port}, {mjpeg_server_port} and
{derived_data_path} are also available for recipes. Never stop another simulator or share a WDA port.

Collection commands write a JSON array of collected identifiers to `{collected}`. Run commands write
JUnit XML to `{junit}` and JSON outcome objects (`nodeid`, `outcome`, optional `stage`/`details`) to
`{results}`. The optional `pytest_evidence` plugin produces these files through pytest hooks and
performs fresh installation with factory-provided device/app metadata. Other runners can implement
the same evidence protocol. Factory-generated `FACTORY_E2E_*` variables carry those runtime values;
they are per-run data, not operator settings for ~/.zshrc.
The runner itself performs uninstall/install before fresh run commands and records the app/device
receipt. Fresh-install evidence does not depend on the chosen command loading the pytest plugin.
Invalid or incomplete execution recipes request verification preparation recovery. They do not
establish a test regression or authorize implementation changes in the project.

If the project needs runtime setup, prepare a helper in the task snapshot, reference it through the
recipe's command/environment, and list its relative path in `e2e.support_files`. The worker derives
that integration from the current project. The factory records its content digest and validates it
before accepting evidence or reusing an operator decision. Repository source is bound separately.

Select changed/new tests and neighbours; deletion tasks select retained scenarios and smoke, and list
every removed test. Shared page-object changes require collection/import checks on both platforms.
collection_only is appropriate for a platform whose runtime behavior is preserved by a bounded change,
with the rationale captured in the task/report. At least one platform must run actual tests.

Master app builds are the default. Related app issue links alone do not change this default. Only an
explicit task/operator build selection adds `app: {"path": "absolute artifact path", "sha": "source SHA"}`
to a platform. Master artifacts have a JSON sidecar with platform, label=master, branch=master, sha,
dirty=false and built_at; their filenames use the same stem. A missing app build blocks the gate.
Do not silently substitute an installed app with an unknown source version.
Before execution, the runner copies the chosen artifact into the task's tmp/e2e/app-artifacts store
and verifies its content digest. Preserve the original filename for digest stability. All retries,
baseline comparisons and accepted continuations use that copy; shared build-store cleanup cannot
remove the artifact of an active gate. These files follow the task snapshot's cleanup lifecycle.

## Verification contract

The routed strategy invokes `bash scripts/e2e-verify.sh QA-KEY`. The verifier runs this command and
inspects spec/e2e-verdict.json, its report and individual receipts before submitting through
scripts/write-result.sh. The coordinator validates receipts against the current work item and test
source; an agent's claim of success is insufficient.
Submit `--output-type passed --result passed` for a passed or accepted_with_warnings native verdict; submit
`--output-type failed --result failed` for a failed or blocked native verdict. The native result routes
blocked gates to environment recovery. A worker's `blocked_verification_cycle` submission cannot bypass
the native verdict or turn an environment failure into a generic cycle-resolution question. Retry of a
legacy QA cycle-resolution item creates a fresh verification item and strategy.
The blocked-run card includes "Retry verification" beside spaced recovery guidance. It displays readable
scenario and error descriptions; legacy serialized classifications are summarized for existing sessions.
The baseline error can differ from the task error. Preserve that distinction rather than diagnosing an
SDK problem from the baseline/environment classification alone.

For evidenced failures of a specific scenario on both revisions, the card provides checkboxes, an
optional comment and "Continue with findings", "Request corrections" and "Retry verification".
Acceptance creates e2e_baseline_accepted_by_operator and an immutable evidence snapshot, recorded
in spec/e2e-operator-decisions.json. It applies only to the current work item, source, execution strategy,
support-file digests and app artifact. The runner recollects the selected scope and verifies every scenario outside those explicit
exceptions, including fresh-install checks and platforms not reached before the blocker.
If those checks pass, the result is accepted_with_warnings; original failures, distinct error
messages and operator comments remain in the report and MR. A new unaccepted failure still blocks
or routes to correction. Infrastructure preflight failures and missing/invalid baseline evidence
cannot be accepted. Changing the bound inputs or starting a fresh retry requires a new decision.
Only failures during actual check execution qualify for baseline acceptance. Setup/teardown failures
on both revisions, such as inability to connect to a server, are environment recovery findings.
Continuation resolves the original accepted app artifact and checks its digest, even if a newer
master build appears in the shared store. "Retry continuation" resumes the same work item after
environment recovery and retains valid decisions; "Retry verification" creates a new gate. Prior
tmux output is archived before continuation, and fresh native verdicts govern QA runtime errors.
Operator accept/resume/retry transitions and runtime collection are serialized per session. Acceptance
restores the verifier as owner and records drained runtime-error signatures, so replaying a historical
worker message cannot reopen the accepted gate even if its wording differs from the native summary.

The runner executes the supplied collection command, checks removed identifiers against collection,
collects selected scenarios and enforces max_tests, then installs the selected app on the reserved device
and executes the supplied run command. With include_smoke enabled, the worker must provide smoke_tests;
the factory adds those identifiers to the selection. Successful selected tests run
again after fresh installation. Zero executed/passing tests cannot produce a passed verdict. An
operator may explicitly accept all selected baseline failures only when actual failed task/baseline
runs provide their evidence. The execution recipe must use local verification without external reporting.

Failures are retried, then compared with the pinned origin/master version of the tests on the same
app artifact. A passing baseline and failing task test means a test regression and enters the normal
implementation correction loop. A failing baseline, unavailable baseline case or environment failure
requires recovery or an operator decision; it does not cause speculative test edits. A flaky pass is recorded
with its earlier failure and still needs the subsequent fresh-install run to pass.

Evidence lives in QA-KEY/tmp/e2e/RUN/: per-phase JSON receipts, command logs, JUnit XML, a Markdown report
and verdict.json. spec/e2e-verdict.json points at the latest gate. Receipts include test SHA, app SHA and
artifact digest, device, selection, outcomes, exit code and log/JUnit/collection/outcome digests. The
strategy and task support files are bound to the result. Keep old evidence; repeat a new gate after
changing code, strategy or integration helpers. Contract-version-1 gates require a fresh version-2 gate;
old operator decisions remain historical evidence and cannot authorize the new execution contract.
Use logs for individual failure evidence; do not publish whole logs containing stage data.

Delivery creates or updates an MR to the configured e2e project master with Jira and a run table generated from the
receipts. The Jira handoff is IN PROGRESS QA -> CODE REVIEW QA, without the mobile project's resolution
fallback or fix-version fields.

Committed documentation corrections after verification do not require another E2E run for MR handoff.
Delivery requires a clean worktree and the verified commit as an ancestor of HEAD. Every changed path
between those commits must be a regular, non-executable `.md`, `.markdown`, `.rst` or `.adoc` file;
additions, deletions and moves within those formats are allowed. Other files, executable modes and
symlinks require fresh verification. This rule uses Git evidence and generic formats, not project paths
or a worker's description of its changes. Bound strategy/support files and all receipt/app checks still
apply, including when a support file has a documentation extension. Verification submissions and
baseline acceptance/continuation keep their exact source binding.
The MR retains the actual verified SHA, original evidence and accepted_with_warnings, and identifies
the delivery SHA and subsequent documentation changes. It does not claim another test run occurred.
MR-description failures are written to stderr so the Recovery card shows their cause before any push.
