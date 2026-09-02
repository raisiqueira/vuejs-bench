# VueBench

VueBench is a small benchmark for evaluating coding agents on Vue.js engineering tasks. It
currently focuses on three deliberately small Vue 3 reactivity bugs and uses deterministic
Vitest and `vue-tsc` checks as the correctness authority.

## Current scope

The MVP covers Vue 3 reactivity only: reactive destructuring, watcher sources, and choosing
`shallowRef` for a root-reactive immutable catalog. Codex CLI is the implemented agent adapter.
The adapter boundary leaves room for Claude Code, OpenCode, or skills-injection experiments later;
those integrations are not part of this MVP.

## Architecture

Each case flows through these boundaries:

1. A benchmark task is loaded from `task.yaml` and its GitHub-issue-style instruction.
2. A fresh temporary copy of `starter/` is initialized as a Git repository and dependencies are
   installed.
3. An `AgentRunner` (currently `CodexRunner`) receives only that workspace and instruction.
4. After the agent exits, the hidden verifier reconstructs a trusted disposable staging Git repo
   from candidate source plus pristine starter configuration. The hidden verifier is injected
   afterward through `sbx exec` stdin, so it never appears in host staging.
5. The verifier creates a uniquely named Docker Sandbox (SBX) microVM with `--clone`. Its private
   Docker daemon runs the explicit `node:<runtime.node>-bookworm` runtime tag against the cloned
   workspace, while the host staging tree remains isolated from VM edits.
6. A Docker named volume owned by that private daemon holds an explicitly installed Corepack
   0.33.0 and cached pnpm 11.1.1. Dependencies install in a networked setup container; hidden
   `vue-tsc --noEmit` and Vitest run first and second in separate `--network none` containers,
   mounting tooling read-only. Their results become a structured `VerificationResult`.
7. Pydantic Evals orchestrates the cases and deterministic evaluator report; it does not judge
   whether Vue code is correct.

The hidden verifier is absent from the starter copy and is removed after verification. On the
current macOS MVP, Codex is additionally wrapped in `/usr/bin/sandbox-exec` (Seatbelt), with
`file-read*` denied for the entire benchmark Git checkout. This whole-checkout boundary protects
the verifier files and Git objects; if Seatbelt is unavailable, VueBench fails closed instead of
running Codex unisolated. Linux and other non-macOS hosts are not supported by this MVP yet.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 24+ (task runtimes below 24 are rejected)
- pnpm 11+
- Docker Sandboxes CLI 0.39+ (`sbx`), required for production verification runs
- An authenticated [Codex CLI](https://developers.openai.com/codex/cli/)

## Running

```bash
uv sync
uv run vuebench list
uv run vuebench run
uv run vuebench run --task reactive-destructure
uv run python -m vuebench
uv run vuebench --task reactive-destructure
```

Omitting the command defaults to `run`, including when using the Python module entry point.
`run` creates and cleans up one temporary workspace per task, invokes Codex non-interactively,
captures its Git diff (including changes committed by the agent), and prints a readable report.
After Codex exits, verification is fail-closed if SBX cannot create, execute, or clean up its
microVM; there is no host-grading fallback. Production verification requires SBX 0.39+. The
remaining solving boundary is macOS Seatbelt around Codex; SBX supplies the clean-room grading
boundary. Each trial has a 15-minute Codex timeout by default; use `--timeout` to override it and
`--model` to pass an optional Codex model override.

## Adding a task

Create a directory under `tasks/<category>/<task-id>/` containing:

```text
task.yaml
instruction.md
starter/       # package.json, pnpm-lock.yaml, Vue/TypeScript source and visible tests
verifier/      # hidden *.spec.ts files, never copied before agent execution
```

`task.yaml` must provide `id`, `title`, `category`, and `difficulty`. It may also define `runtime`
(`node`, `package_manager`) and `checks`. Keep the starter's `pnpm-lock.yaml` committed so
dependency installation remains reproducible. Hidden tests should assert observable behavior,
not a particular implementation; a narrow structural assertion is acceptable only where behavior
cannot establish the stated performance intent.

## Benchmark philosophy

- Evaluate behavior wherever possible.
- Keep hidden tests invisible to the agent while it solves the task.
- Prefer deterministic verification over an LLM judge.
- Benchmark the coding-agent harness and workflow, not only raw model knowledge.
- Start every trial from a pristine workspace and never mutate source fixtures.
- Keep the agent adapter replaceable so future Codex-with/without-skills comparisons and other
  coding CLIs can use the same task and verification layers.
