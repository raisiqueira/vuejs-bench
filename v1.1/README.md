# VueBench v1.1 PoC: real Vue fixes on Harbor

This folder is a proof of concept for VueBench v1.1. It is separate from v1: the
v1 CLI, the `tasks/` fixtures and the Seatbelt/SBX pipeline do not change.

v1.1 uses [Harbor](https://github.com/harbor-framework/harbor) as the harness.
Each task comes from a real GitHub issue that has a merged fix PR with tests. The
agent gets the issue text. The hidden tests are the tests from the fix PR.

## Tasks

| Task | Source | Fix PR | FAIL_TO_PASS | PASS_TO_PASS |
|---|---|---|---|---|
| `reka-ui-2954-select-space` | [unovue/reka-ui#2954](https://github.com/unovue/reka-ui/issues/2954) | [#2955](https://github.com/unovue/reka-ui/pull/2955) | 3 | 31 |
| `reka-ui-2988-autocomplete-cancel` | [unovue/reka-ui#2988](https://github.com/unovue/reka-ui/issues/2988) | [#2989](https://github.com/unovue/reka-ui/pull/2989) | 2 | 25 |
| `reka-ui-2963-tagsinput-enter` | [unovue/reka-ui#2963](https://github.com/unovue/reka-ui/issues/2963) | [#2966](https://github.com/unovue/reka-ui/pull/2966) | 1 | 30 |
| `vueuse-5571-usefetch-stale-response` | [vueuse/vueuse#5571](https://github.com/vueuse/vueuse/issues/5571) | [#5574](https://github.com/vueuse/vueuse/pull/5574) | 1 | 53 |
| `pinia-3161-hydration-set-map` | [vuejs/pinia#3161](https://github.com/vuejs/pinia/issues/3161) | [#3162](https://github.com/vuejs/pinia/pull/3162) | 1 | 25 |

All five use Vitest with jsdom or happy-dom. No task needs Vitest browser mode.

## Layout

```
v1.1/
  sources/<id>/source.toml   # repo, issue, PR, commits, dates, test settings
  sources/<id>/instruction.md # issue text, without cause or fix hints
  sources/<id>/tests.json     # discovered FAIL_TO_PASS / PASS_TO_PASS lists
  scripts/vb11.py             # builds tasks/ from sources/
  scripts/grade.mjs           # grader, copied into each task
  scripts/validate.sh         # base = 0 and oracle = 1 gate
  tasks/<id>/                 # generated Harbor tasks (do not edit by hand)
```

Each generated task has the standard Harbor layout:

- `task.toml`: metadata (issue and PR URLs, base and fix commits, dates), timeouts and network policy.
- `instruction.md`: the issue text.
- `environment/Dockerfile`: `node:24.22.1` (pinned by digest), pnpm through Corepack, the repo
  at the base commit, and `pnpm install --frozen-lockfile --ignore-scripts`. The Git
  history is removed and replaced by one "Base snapshot" commit with no remote.
- `solution/solve.sh` + `fix.patch`: the oracle. It applies the non-test part of the fix PR.
- `tests/test.sh`: copies the PR test files (at the fix commit) and the trusted test
  configuration (at the base commit) over the workspace. Then it runs Vitest on the
  changed test files and writes `/logs/verifier/reward.txt`.

The base commit is the only parent of the squash-merged fix commit. `vb11.py` checks this.

## Network

| Phase | Policy | Why |
|---|---|---|
| Image build, agent install | `public` | npm registry and the agent CLI install |
| Agent | `allowlist` | model API hosts only: `api.anthropic.com`, `api.openai.com`, `openrouter.ai`, `opencode.ai`, `models.dev` |
| Verifier | `no-network` | dependencies are already in the image |

A probe task confirmed this with the local Docker environment. In the agent phase,
`github.com` and `registry.npmjs.org` were blocked and `api.anthropic.com` answered.
In the verifier phase, all three were blocked. Add a provider host with
`--allow-agent-host <host>`.

## Requirements

- Docker (tested with OrbStack, Docker 29.9.1)
- Harbor 0.24.0: `uv tool install harbor==0.24.0`
- `jq` (only for `validate.sh`)
- Python 3.11+ for `vb11.py`. The commands below use `uv` to get one.

## Commands

Run from the repository root.

Run one task with the oracle (expect reward 1) and with the base commit (expect reward 0):

```bash
harbor run -p v1.1/tasks/reka-ui-2954-select-space -a oracle
harbor run -p v1.1/tasks/reka-ui-2954-select-space -a nop
```

Run all tasks:

```bash
harbor run -p v1.1/tasks -a oracle
```

Run the validation gate (base = 0, oracle = 1 on 5 attempts) for all tasks or for some:

```bash
v1.1/scripts/validate.sh
v1.1/scripts/validate.sh -k 5 pinia-3161-hydration-set-map
```

Results go to `v1.1/jobs/validate-<timestamp>/summary.tsv`.

## Agents

Every agent uses the same pattern:

- one task: `-p v1.1/tasks/<task-id>`
- all tasks: `-p v1.1/tasks`
- effort: `--effort <level>` for Codex, Claude Code and Grok Build. OpenCode has no
  effort option and fails with `--effort`. Use `--ak variant=<variant>` for it.
- attempts: `-k 3` runs three attempts per task (pass@3).
- agent version: pin it with `--ak version=<version>` for comparable runs.

The examples use these variables:

```bash
TASK=reka-ui-2954-select-space
EFFORT=high
```

| Agent | `-a` | Auth | Effort | Extra hosts |
|---|---|---|---|---|
| Codex | `codex` | ChatGPT login (`~/.codex/auth.json`) or `OPENAI_API_KEY` | `--effort none\|minimal\|low\|medium\|high\|xhigh\|max` | `chatgpt.com`, `auth.openai.com` with the ChatGPT login |
| Claude Code | `claude-code` | `CLAUDE_CODE_OAUTH_TOKEN` (subscription) or `ANTHROPIC_API_KEY` | `--effort low\|medium\|high\|xhigh\|max` | none |
| Grok Build | `grok-build` | `XAI_API_KEY` | `--effort none\|minimal\|low\|medium\|high\|xhigh\|max` | `api.x.ai` |
| OpenCode | `opencode` | provider API key env var | `--ak variant=<variant>` | the provider host, if not in the allowlist |
| OpenCode, host login | `opencode_auth:OpenCodeAuth` | `opencode auth login` on the host | `--ak variant=<variant>` | the provider host, if not in the allowlist |

Not every model accepts every effort level. An agent does not read your local CLI
config, so it uses the model default when you do not give `--effort`.

### Codex

Harbor copies `~/.codex/auth.json` into the container, outside `/logs`, and deletes
it after the run. Use `CODEX_AUTH_JSON_PATH=<path>` for a different file.

```bash
# One task
CODEX_FORCE_AUTH_JSON=1 harbor run -p v1.1/tasks/$TASK \
  -a codex -m openai/gpt-6.1-sol --ak version=0.164.0 --effort $EFFORT \
  --allow-agent-host chatgpt.com --allow-agent-host auth.openai.com

# All tasks
CODEX_FORCE_AUTH_JSON=1 harbor run -p v1.1/tasks -n 1 \
  -a codex -m openai/gpt-6.1-sol --ak version=0.164.0 --effort $EFFORT \
  --allow-agent-host chatgpt.com --allow-agent-host auth.openai.com
```

`-n 1` runs one trial at a time. Codex can refresh the token in the container, and
parallel refreshes make it more likely that your host login stops working. If it
stops, run `codex login` again. With `OPENAI_API_KEY`, remove `CODEX_FORCE_AUTH_JSON`
and the two `--allow-agent-host` options.

### Claude Code

Get a subscription token with `claude setup-token`.

```bash
export CLAUDE_CODE_OAUTH_TOKEN=... CLAUDE_FORCE_OAUTH=1

# One task
harbor run -p v1.1/tasks/$TASK -a claude-code -m anthropic/claude-sonnet-5-5 --effort $EFFORT

# All tasks
harbor run -p v1.1/tasks -a claude-code -m anthropic/claude-sonnet-5-5 --effort $EFFORT
```

With an API key, export `ANTHROPIC_API_KEY` and do not set the two OAuth variables.

### Grok Build

```bash
export XAI_API_KEY=...

# One task
harbor run -p v1.1/tasks/$TASK -a grok-build -m xai/grok-4.7 --effort $EFFORT \
  --allow-agent-host api.x.ai

# All tasks
harbor run -p v1.1/tasks -a grok-build -m xai/grok-4.7 --effort $EFFORT \
  --allow-agent-host api.x.ai
```

### OpenCode

Harbor installs `opencode-ai` in the task container and runs
`opencode run --format=json`. Give the model as `provider/model` and export the API
key of that provider. The variant names depend on the model (for example `high`).

```bash
export OPENROUTER_API_KEY=...

# One task
harbor run -p v1.1/tasks/$TASK -a opencode -m openrouter/moonshotai/kimi-k3 \
  --ak version=1.19.3 --ak variant=$EFFORT

# All tasks
harbor run -p v1.1/tasks -a opencode -m openrouter/moonshotai/kimi-k3 \
  --ak version=1.19.3 --ak variant=$EFFORT
```

### OpenCode with the host login

`v1.1/agents/opencode_auth.py` reuses the credentials from `opencode auth login`
(`~/.local/share/opencode/auth.json`, or `OPENCODE_AUTH_JSON_PATH`). No env var is
needed. It copies only the entry of the model's provider into the container, outside
`/logs`, and removes it after the run.

```bash
# One task
PYTHONPATH=v1.1/agents harbor run -p v1.1/tasks/$TASK \
  -a opencode_auth:OpenCodeAuth -m opencode-go/kimi-k3 \
  --ak version=1.19.3 --ak variant=$EFFORT

# All tasks
PYTHONPATH=v1.1/agents harbor run -p v1.1/tasks \
  -a opencode_auth:OpenCodeAuth -m opencode-go/kimi-k3 \
  --ak version=1.19.3 --ak variant=$EFFORT
```

Tested with API-key logins (OpenCode Go, OpenRouter). OAuth logins (OpenAI) also need
their auth hosts in `--allow-agent-host`, and a token refresh in the container can
invalidate the host login. Do not use a Claude subscription login through OpenCode.
Use the `claude-code` agent for it.

### Test status

All commands above pass `harbor run --dry-run`. Only the OpenCode agents were run
against a real model. The runs authenticated, but they stopped on account problems
(an expired OpenCode Go key, no OpenRouter credit), so no agent result is recorded yet.

### Results

Each job goes to `jobs/<timestamp>/`, or to the folder given with `-o`. In each trial:

- `verifier/reward.txt`: 1 = solved, 0 = not solved.
- `verifier/report.json`: which FAIL_TO_PASS and PASS_TO_PASS tests passed.
- `result.json`: `exception_info` shows agent errors, such as a failed login.

`harbor view jobs` opens a web view of the trials.

## Rebuild the tasks

```bash
uv run --no-project --python 3.12 python -I v1.1/scripts/vb11.py build
uv run --no-project --python 3.12 python -I v1.1/scripts/vb11.py discover <task-id>
```

`build` renders `tasks/` from `sources/`. It clones the source repos into
`v1.1/.cache/repos`. `discover` builds the image and runs the PR tests twice
without network: at the base commit and with the fix. A test that fails at the
base and passes with the fix is FAIL_TO_PASS. A test that passes in both runs is
PASS_TO_PASS. A test that does not pass with the fix (for example `it.skip`) is
left out. The lists go to `sources/<id>/tests.json`.

To add a task, create `sources/<id>/source.toml` and `instruction.md`, then run
`discover` and `validate.sh`.

## Differences from the v1.1 plan

- Harbor 0.24.0 has no `sbx` environment. The local `docker` environment works and
  supports per-phase network policies through an egress-control sidecar.
- The agent needs internet during install, so `[environment]` stays `public` and
  only the agent and verifier phases are restricted.
- The verifier does not use `git apply` for the test patch. It copies whole test
  files, so it does not depend on the Git state that the agent leaves.
- The verifier runs `node_modules/.bin/vitest --config <trusted config>` directly.
  A new `vitest.config.*` written by the agent does not change the run.
- Ori Code is not part of this PoC. OpenCode is the agent.

## Open issues

- No `vue-tsc` check yet. v1 needs it to pass, and v1.1 grades on Vitest only.
- The agent can still change `node_modules` or source files that the tests import
  (other than the restored files). A static check on the diff should flag this.
- The Harbor OpenCode adapter installs Node 22 with nvm for the agent. The verifier
  uses the image Node 24.
- The images are large (2.1 GB for reka-ui and pinia, 5 GB for vueuse). For many
  runs, push them to a registry and set `docker_image` in `task.toml`.
- No agent run has finished yet. See [Test status](#test-status).
- Contamination: there is no future Git history, and the PR host is blocked for the
  agent. Agent logs are not yet scanned for the PR URL or for parts of the fix.
