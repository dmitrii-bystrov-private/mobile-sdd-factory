# Proposal: Spec‑Driven Workflow on Claude Code (Current State & Improvements)

## Current state of the project

I already have a working spec‑driven workflow built on Claude Code that takes a Jira ticket all the way to a ready‑for‑review MR.  
Agents read the Jira issue, prepare a working environment (branch/worktree), explore the codebase, write a spec, implement the changes, prepare the MR, post to Slack, and move the ticket into testing.

This is already decomposed into Claude Code sub‑agents and skills: dedicated sub‑agents handle code exploration, spec writing, implementation, and review, while skills encapsulate the knowledge and commands for Jira, git, Slack, and project‑specific conventions.  
The system works end‑to‑end, but it’s still expensive in tokens and somewhat fuzzy in responsibilities: agents are doing too much mechanical work and carrying too much context.

---

## Core Claude Code concepts (sub‑agents and skills)

**Sub‑agents** are separate specialized assistants with their own system prompt, tool set, and fully isolated context.  
They are a good fit for complex, multi‑step tasks (codebase exploration, spec and plan generation, advanced debugging), because they can run their whole process in their own context without dragging along the entire history of the main conversation.

**Skills** are folders with instructions, scripts, and resources that give an agent domain expertise and ready‑made ways of acting.  
Skills are loaded via progressive disclosure: Claude decides which skills are relevant for a given task and only pulls in the instructions and scripts it needs, instead of bloating the prompt with everything up front.

In combination: MCP tools define **what** can be done, skills describe **how** to do it (processes, domain knowledge), and sub‑agents define **where** context boundaries are (separate workspaces for separate stages of the flow).  

My current prototype already uses both sub‑agents and skills, but it doesn’t fully exploit their strengths yet: a lot of logic and routine still lives in prompts and agent “thoughts” rather than in scripts and structured artifacts.

---

## What I want to improve

### 1. Move routine work from agents into scripts and skills

Right now, sub‑agents themselves go to Jira, create worktrees, unpack subtasks, aggregate context, and track statuses.  
The plan is to introduce a preparatory skill/script that will:

- read the Jira issue and subtasks via the API  
- create the worktree/branch  
- persist the issue and subtasks into files in the workspace  
- build structured data (for example, a `task.json` with the full hierarchy and statuses)

In terms of skills, this is the classic pattern: `SKILL.md` defines **when** and **how** to use these scripts, and the scripts themselves perform the mechanical steps without burning tokens.  
After this, sub‑agents enter an already‑prepared workspace with structured files and don’t need to spend context and reasoning on basic setup.

### 2. Clarify the roles of sub‑agents and skills

Target state:

- **Skills** describe project conventions (spec format, MR templates, Jira workflow), wrap external APIs and scripts, and store reference materials and examples.  
- **Sub‑agents** each own a single expert task in their own context (code exploration, spec generation, implementation from spec, self‑review, final MR packaging).

This better leverages the strengths of sub‑agents: separate contexts, automatic delegation based on task descriptions, and reduced context bloat, instead of one “giant” agent trying to do everything.

### 3. Two‑phase context building with a cheaper model

The first phase — searching the codebase, grepping, and collecting relevant files and signals — can be offloaded to a lightweight sub‑agent/skill running on a cheaper model.  
It will return a compact index/summary: lists of relevant files, entry points, existing implementations, and pointers to key project areas.

The main, more expensive sub‑agents (spec, implementation) will then operate on those artifacts: instead of raw MCP logs and huge code chunks in context, they will see neat file lists, excerpts, and structured JSON/Markdown descriptions.

---

## Goal of this evolution

Evolve the current working SDD pipeline into a lighter and more predictable system that:

- uses sub‑agents as separate specialists with isolated context for each key stage of the flow  
- relies on skills as the single layer for expertise and infrastructure logic (Jira, git, Slack, spec format, MR templates)  
- moves deterministic, repeatable mechanics into scripts inside skills  
- separates cheap context gathering from expensive reasoning and generation  

The end result is that agents focus on what they’re good at — understanding the task, designing solutions, writing code, and reviewing — while the surrounding automation takes care of the setup, plumbing, and state management.

---

## Links

- Sub‑agents (Claude Code docs): https://code.claude.com/docs/en/sub-agents  
- Skills (Claude Code docs): https://code.claude.com/docs/en/skills