# Codex + Gitea quickstart

Keep this fork checkout separate from working projects. The target must be an
existing sandbox Git project root, never the common repositories folder.

## Install

From the reviewed checkout:

```bash
bash install.sh --safe install --target /absolute/path/to/sandbox --dry-run
bash install.sh --safe install --target /absolute/path/to/sandbox
```

Files land in `.agents/`; internal aliases preserve legacy `.claude/` paths.
AGENTS.md gets one managed block. No Git checkout, external skills, system tools,
Claude Code or global configuration are installed. Conflicts stop before writes.
Codex discovers `.agents/skills` directly. Manifest/backups remain local and ignored.

After the specific fork release is published (it has not been published by this
implementation), the reviewed local downloader supports pinned assets:

```bash
bash get.sh --safe --tag v3.1.2-gitea.1 --target /absolute/path/to/sandbox --dry-run
bash get.sh --safe --tag v3.1.2-gitea.1 --target /absolute/path/to/sandbox
```

It verifies checksum/provenance, extracts only plain files and runs the **local**
reviewed installer, never downloaded scripts. No latest/main fallback or npx step.

## Configure and inspect

Use [the JSON example](gitea-provider.md); configure real verify_commands, base
branch, CI contexts and seven board columns. Supply GITEA_URL, GITEA_OWNER,
GITEA_REPO, GITEA_PROJECT_ID and GITEA_TOKEN through local environment/secret store.
Never paste secrets into chat or commit them. The origin must match that repo.

For file-based credentials, export GITEA_TOKEN_FILE before starting Codex. Direct
Python provider/runner commands also read that file; it must be owner-only (600).
Do not leave an obsolete GITEA_TOKEN set: a nonempty token env overrides the file.

Alternatively bind the file once, locally, to survive sessions that do not inherit
your terminal's environment (no remote write, no token copied):

```bash
python3 .agents/bin/super-board-provider.py --config .claude/super-board/configs/demo.json auth --token-file /absolute/private/token-file
```

At the sandbox root:

```bash
codex login status
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json doctor
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json status
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json runner-status
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json plan
```

These start no agents and perform no remote writes. Doctor reports missing columns;
create them in the UI. Missing technical skills must be installed/reviewed separately.
`$super-board` routes Gitea to its own lifecycle, bypassing GitHub onboarding.

`status` reads the board; `runner-status` is offline and needs no credentials. It
reports the live local lock (busy/idle), the most recently dispatched task, stop
request and saved lane receipt paths. A persisted active.json with an unlocked
runner is shown as lastTask, never activeTask. busy can also mean finish/resume
currently owns the lock. Gitea Issue/PR comments hold remote results. There is no
separate web dashboard. On Linux, `watch -n 2 './factory runner-status'` can monitor
a project that supplies the factory launcher.

## Run only after sandbox and usage approval

```bash
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json --allow-write --allow-agent-run run
```

Build/QA/Review run sequentially, bounded by max_dispatches. Repeat approved runs to
continue; no scheduler/daemon is installed. Review leaves a human merge request.
Merge it yourself after inspection, then reconcile one Issue:

```bash
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json --allow-write finish 11
```

Finish performs no merge: it verifies the receipt, exact PR/head/base, green CI,
merged state and merge SHA ancestry before closing/moving Done.

## Stop/recover

```bash
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json stop
```

The runner terminates the active Codex process group and preserves worktrees,
branches, PRs and `.claude/super-board/gitea/` receipts. Outside a lane it observes
stop at the next bounded HTTP/checkpoint boundary. Inspect everything before:

```bash
python3 .agents/bin/super-board-gitea.py --config .claude/super-board/configs/demo.json --reconciled resume
```

If a mutation has unknown outcome, inspect that remote resource, then separately:

```bash
python3 .agents/bin/super-board-provider.py --config .claude/super-board/configs/demo.json --reconciled resume
```

Neither resume starts agents or retries writes. There is no automatic cleanup/rebase.
