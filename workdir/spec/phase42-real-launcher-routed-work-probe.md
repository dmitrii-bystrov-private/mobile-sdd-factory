# Phase 42 Real Launcher Routed Work Probe

## Scope

Check whether a real launcher-backed role process can do more than bootstrap: specifically, whether it can participate in the current routed work loop once the backend hosts it through a real interactive driver.

## What Was Probed

A real `implementer` role was launched through the normal role-local `launch-role.sh` path under:

- `TmuxSessionBackend(mode="pty")`
- default launcher resolution (`claude` first)
- normal role workspace and prompt hydration
- buffered routed input after launcher bootstrap

The probe then:

1. prepared a real `oneshot` session
2. let the backend dispatch the normal implementer handoff
3. observed that the original multi-line handoff was rendered as a terminal paste block
4. switched routed transport to a file-backed handoff via `ROUTED_WORK.md`
5. re-polled role output repeatedly through `collect_role_output`
6. inspected the resulting runtime output artifact and role workspace

## Result

The launcher-backed process bootstrapped successfully, and the routed handoff transport was partially improved.

Observed runtime behavior:

```text
SDD_FACTORY_ROLE_LAUNCHER_READY role=implementer task=IOS-REAL-LAUNCHER-TEST-002 lifecycle=persistent
SDD_FACTORY_AGENT_BOOTSTRAP launcher=claude role=implementer task=IOS-REAL-LAUNCHER-TEST-002 lifecycle=persistent
```

Before the transport fix, the live UI showed a pasted multi-line block such as:

```text
❯ [Pasted text #1 +19 lines]
paste again to expand
```

After the transport fix:

- the routed multi-line handoff was materialized into `ROUTED_WORK.md`
- the live runner no longer showed the old paste-block UI
- the role workspace contained the full routed handoff as a durable file

The session still remained at:

- `current_stage = implementation_requested`

No terminal `SDD_PROGRESS` or `SDD_OUTPUT` markers came back from the real launched agent during the probe window.

## What This Proves

- the launcher path is healthy enough to start a real `claude` process from the role workspace
- the PTY driver can pass trust/bootstrap and reach the live interactive surface
- the backend can now avoid the old multi-line paste transport by routing durable work through `ROUTED_WORK.md`
- the next blocker is no longer handoff transport

## Actual Remaining Gap

The current backend still lacks a durable continuation contract for true launched roles after the file-backed handoff has been delivered.

Today we have:

- launcher bootstrap
- live PTY hosting
- trust/bootstrap handling
- file-backed routed work delivery through `ROUTED_WORK.md`
- routed work dispatch for fixtures and controlled subprocesses

What we do **not** yet have is:

- a real `claude`/`codex` role process that proceeds from file-backed routed work to reliable terminal `SDD_*` output
- a deeper live continuation driver for interactive runner states that still appear after routed work is delivered

## Immediate Conclusion

The next concrete work item should now be framed as:

- `Live continuation after file-backed routed work`

That layer must bridge:

1. factory role dispatch
2. file-backed routed handoff delivery
3. real launcher-backed agent continuation inside the live interactive session
4. structured `SDD_*` marker collection
