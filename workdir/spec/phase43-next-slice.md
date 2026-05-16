# Phase 43 Next Slice

## Question

What should be the next concrete slice inside `Phase 43` after the doctor baseline and the first operator-facing doctor surface?

## Candidate Slices

### Option 1. Bootstrap Guidance Baseline

Generate a prioritized setup guide from the current doctor report:

- what is missing
- what is optional
- what exact commands or edits should happen next

### Option 2. Richer Doctor Semantics

Expand the doctor with more checks:

- `.venv`
- Node/npm
- backend config
- launcher/runtime host subtleties

### Option 3. Permanent Documentation Baseline

Start writing the first permanent docs package outside `workdir/spec/`.

## Decision

Choose `Bootstrap Guidance Baseline`.

## Why

### 1. It complements the doctor immediately

The doctor now tells the operator what is green and what is red.

The next most useful thing is to turn that into:

- concrete next steps
- ordered remediation
- setup guidance instead of just diagnostics

### 2. It keeps the slice bounded

This does **not** require a full installer yet.

A first baseline can simply read the doctor result and produce:

- required fixes first
- optional improvements second

### 3. It prepares later documentation

The future permanent setup docs should describe a setup flow that already exists in working tooling.
