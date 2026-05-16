# Phase 43 Next Slice 3

## Question

What should be the next concrete slice inside `Phase 43` after:

- doctor baseline
- bootstrap guidance baseline
- doctor and guidance product surfaces

## Candidate Slices

### Option 1. Local Toolchain Doctor Expansion

Expand the doctor with the next most useful local setup checks:

- `.venv`
- `node`
- `npm`

### Option 2. Setup Automation Baseline

Begin real setup helpers or repair scripts.

### Option 3. Permanent Documentation Baseline

Start the first reconciled permanent docs package.

## Decision

Choose `Local Toolchain Doctor Expansion`.

## Why

### 1. It strengthens the existing doctor/guidance loop

The current surfaces already exist.

The best next step is to make them more complete before adding automation.

### 2. It stays bounded

Checking local toolchain prerequisites is narrow and low-risk.

### 3. It gives immediate operator value

The project already depends on Python and frontend toolchains in daily work, so surfacing them is directly useful.
