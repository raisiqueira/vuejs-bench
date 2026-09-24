# VueBench

VueBench is a benchmark for evaluating coding agents on Vue.js engineering tasks. It
contains 17 Vue 3 cases and uses deterministic Vitest and `vue-tsc` checks as the
correctness authority.

## Current scope

The cases cover reactivity, component contracts, list identity, slots, directives,
accessibility, shared state across Vue Router pages, and component caching. Dedicated
cases measure adoption of newer Vue APIs. All tasks use Vue 3 and
Vite; none requires Nuxt. VueBench can run Codex, Claude Code, OpenCode, Ori Code
(with OpenRouter models), or Grok Build as host-native agents while using one deterministic grading
pipeline for all of them.

## Architecture

Each case flows through these boundaries:

1. A benchmark task is loaded from `task.yaml` and its GitHub-issue-style instruction.
2. A fresh temporary copy of `starter/` is initialized as a Git repository and dependencies are
   installed.
3. The selected host-native `AgentRunner` receives only that workspace and instruction. Every
   adapter is wrapped in macOS Seatbelt: reads from the benchmark checkout are denied, and writes
   are limited to the disposable trial workspace plus runner-owned temporary state outside it.
4. Before the paid agent phase begins, VueBench checks a persistent, mountless Docker Sandbox
   named `vuebench-verifier` by default. It creates the sandbox once when absent and probes it.
5. After the agent exits, the hidden verifier reconstructs trusted staging from candidate source
   plus pristine starter configuration, copies it into a unique VM-private run directory, then
   injects hidden tests through `sbx exec` stdin. Hidden tests never appear in agent or host staging.
6. The persistent microVM's private Docker daemon runs disposable containers using the explicit
   `node:<runtime.node>-bookworm` tag. Unique Docker volumes hold an explicitly installed Corepack
   0.33.0, pnpm 11.1.1, its store, and `node_modules`. Dependencies install in a networked setup
   container; hidden `vue-tsc --noEmit` and Vitest run first and second in separate `--network none`
   containers with tooling and dependencies read-only. Their results become a structured
   `VerificationResult`.
7. VueBench removes the per-case VM directory and Docker volumes, but retains the verifier sandbox
   for the next case. SBX may suspend and restart its VM between runs, without the unreliable
   create/delete lifecycle on every task.
8. Pydantic Evals orchestrates the cases and deterministic evaluator report; it does not judge
   whether Vue code is correct.

The hidden verifier is absent from the starter copy and removed from the VM after verification.
The whole-checkout Seatbelt boundary protects verifier files and Git objects; if Seatbelt is
unavailable, VueBench fails closed instead of running an agent unisolated. Linux and other
non-macOS hosts are not supported by this host-native runner architecture yet.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 24+ (task runtimes below 24 are rejected)
- pnpm 11+
- Docker Sandboxes CLI 0.39+ (`sbx`), required for production verification runs
- At least one authenticated host CLI: Codex, Claude Code, OpenCode, Ori, or Grok Build

## Running

```bash
uv sync
uv run vuebench list
uv run vuebench verifier init
uv run vuebench --task reactive-destructure --agent codex --model gpt-6-luna --effort high
uv run vuebench run --task reactive-destructure --agent claude --model sonnet --effort high
uv run vuebench run --task reactive-destructure --agent opencode --model openai/gpt-5 --effort high
uv run vuebench run --task reactive-destructure --agent ori --model z-ai/glm-5.3-flash --effort high
uv run vuebench run --task reactive-destructure --agent grok --model grok-4.7-build-fast --effort high
```

Omitting the command defaults to `run`, including when using the Python module entry point.
`run` checks SBX first, prints progress for each phase, invokes the selected agent
non-interactively, captures its Git diff (including committed changes), and prints a report.
There is no host-grading fallback. Each trial has a 15-minute agent timeout by default; use
`--timeout` to override it, `--model` to pass an optional model override, and `--effort` to pin
reasoning effort. VueBench translates `--effort` to each agent's native interface:

| Agent | Native setting | Supported values |
| --- | --- | --- |
| Codex | `model_reasoning_effort` | Model-dependent |
| Claude Code | `--effort` | `low`, `medium`, `high`, `xhigh`, `max` |
| OpenCode | `--variant` | Provider/model-dependent |
| Ori Code | `--reasoning-effort` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; model/harness-dependent |
| Grok Build | `--reasoning-effort` | Model-dependent |

VueBench forwards the requested value without substituting another level. The selected agent exits
with an execution error when its model or provider does not support that value.

The Grok adapter uses the official headless mode, isolates writable state from the user's Grok
home, and copies only the existing `grok login` credential into disposable runner scratch. An
`XAI_API_KEY` environment variable also works without a saved login.

Every run writes structured JSON to `results/<timestamp>-<scope>-<agent>.json`. Use `--output`
to choose a path or `--no-save` to disable persistence. The JSON includes timestamps, agent,
model, effort, process output/diff, deterministic check output, and infrastructure errors.

Manage the persistent verifier explicitly:

```bash
uv run vuebench verifier status
uv run vuebench verifier init
uv run vuebench verifier remove
```

`init` is optional because `run` performs the same preflight before starting the agent. Keeping it
as a separate command is useful for diagnosing SBX once, before spending time or API credits.

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
