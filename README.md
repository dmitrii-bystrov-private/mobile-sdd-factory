# Constellation: Agent Runtime

Constellation is a local orchestration platform that moves Jira tasks through planning,
implementation, review, verification and GitLab MR handoff. It supports iOS, Android and mobile E2E work.

The backend owns session state and routes work to specialized agents. Operators use a web console;
Claude Code and Codex agents run in persistent tmux windows and work in task-local Git worktrees.
Correction rounds, recovery and delivery use the same session.

The workflow assumes configured Jira/GitLab projects and local repositories. Integrations and
repository helpers may need adaptation when using it for another workflow.

## Quick Start

Configure the tools, local paths and credentials using the [setup guide](docs/setup.md).
From the repository root, start the stack and open the operator console:

```bash
bash factory/open-local-ui.sh
```

Default local URLs:

- Operator UI: `http://127.0.0.1:4173`
- Backend API: `http://127.0.0.1:8000`

To start without opening a browser:

```bash
bash factory/run-local-stack.sh
```

Both processes stay attached until `Ctrl+C`. Use the [operator guide](docs/operator-guide.md)
for session creation, runtime settings and recovery.

## Workflow

Enter a Jira key or link in the UI and choose a profile:

| Profile | Use for |
| --- | --- |
| `oneshot` | Small, self-contained tasks with direct implementation. |
| `story_full` | Stories that need context, requirements, acceptance criteria and decomposition before subtask execution. |

The backend prepares the task snapshot and worktree, routes implementation and review, runs
verification, and performs documentation review when configured. Successful work proceeds to MR
handoff and the Jira code-review status. Follow-up work can re-enter the same session.
Completed tasks release idle agent processes after saving their conversations and factory state.
Follow-up work wakes the required role with its saved context.

Operators resolve requirements questions, review disagreements and recovery blockers through the UI.
See the [runtime model](docs/runtime-model.md) for roles, stages, policies and lifecycle behavior.

QA tasks use the same workflow with real local Appium runs. Master app builds are the default unless
another build is explicitly selected. The [E2E workflow](docs/e2e-workflow.md) covers configuration,
verification evidence and operator decisions.

## Project Layout

```text
backend/    API, coordinator, session state and role contracts
ui/         operator console
factory/    doctor, cleanup, acceptance and local stack tooling
scripts/    shell helpers and workflow automation
tests/      backend regression tests
docs/       setup, operator and runtime documentation
```

## Development

Run the supported platform checks from the repository root:

```bash
bash scripts/run-supported-tests.sh
```

The [developers guide](DEVELOPERS_GUIDE.md) covers development commands and validation.
Read the [repository guidelines](AGENTS.md) before contributing.

## Documentation

| Document | Use for |
| --- | --- |
| [Setup](docs/setup.md) | Prerequisites, machine ENV and local configuration. |
| [Operator guide](docs/operator-guide.md) | Starting tasks, runtime visibility, operator replies and recovery. |
| [Runtime model](docs/runtime-model.md) | Sessions, roles, workflow policies and delivery. |
| [E2E workflow](docs/e2e-workflow.md) | Mobile autotest execution and evidence. |
| [Terminal result contract](docs/terminal-result-contract.md) | Role outputs and coordinator ingress. |
| [Developers guide](DEVELOPERS_GUIDE.md) | Development and testing the factory. |
| [Script reference](scripts/README.md) | Direct CLI helpers. |
| [Repository guidelines](AGENTS.md) | Contributor and agent conventions. |

## Support

This repository is published as-is. It is not a supported product or a general-purpose framework.

Issues, pull requests, and feature requests may not be reviewed or answered. You are free to fork
and adapt the project under the terms of the license.

## License

MIT. See [LICENSE](LICENSE).
