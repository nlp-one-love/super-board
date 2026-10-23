# Fork maintenance and package lifecycle

Adaptation: nlp-one-love/super-board; upstream: EricTechPro/super-board. Feature
branches push only to the fork. Do not create upstream issues/PRs or contact its author.
Keep main close to upstream; inspect diffs and agree on merge/rebase before sync.
Do not force push, delete branches or rewrite history without separate permission.

## Verification/release

New offline suites (real local HTTP, executable fake Codex, isolated Git sandboxes):

```bash
python3 tests/test_gitea_provider.py
python3 tests/test_package_lifecycle.py
```

These retain their `/tmp` sandboxes and do not consume paid Codex usage. They prove
mocked behavior, not live integration. The upstream `bash tests/run-safety.sh`
requires jq/Node/curl/tar in addition to Python/Git/Bash. Its shell tests and legacy
installer contain recursive cleanup: obtain permission before running them under a
no-recursive-deletion constraint. Readiness and pure parser regression tests can
be run independently.

Postman local mock/simulation files live in `postman/`. They derive from the saved
instance contract subset. Owner mock discovery was skipped: no Postman workspace
binding was established and the server contract was directly available. CLI simulation
in this environment fails in its dataset backend. The handler also runs directly
with `node postman/mocks/gitea/default.js`; it has process-local state and must not
be deployed as a shared hosted mock. It models only snapshot/move; others return 501.

Versions: upstream base plus fork iteration, e.g. 3.1.2-gitea.1 / v3.1.2-gitea.1.
Build without publishing:

```bash
python3 scripts/super-board-package.py build --tag v3.1.2-gitea.1 --output /tmp/super-board-v3.1.2-gitea.1.tar.gz
```

The allowlisted archive excludes Git/bytecode, includes PACKAGE-SOURCE.json and has
a .sha256 sidecar. Publishing needs separate approval. Release CI checks tag/HEAD,
VERSION and tests; fork tags additionally validate origin and attach assets. No tag,
release or PR is created by a build. Live sandbox smoke/full Codex cycle remain
release prerequisites after explicit separate authorization.

## Upgrade/rollback/uninstall

```bash
bash install.sh --safe version --target /absolute/path/to/project
bash install.sh --safe doctor --target /absolute/path/to/project
bash install.sh --safe update --target /absolute/path/to/project --dry-run
bash install.sh --safe update --target /absolute/path/to/project
```

For published assets use `get.sh --safe --tag EXACT_TAG --update --target ...`, first
with --dry-run. No overwrite/force flag: resolve local edits yourself. Custom skills,
config/state and AGENTS.md outside its managed block are preserved. Unmanaged legacy
installs require an explicit manual migration; they are not silently adopted.

Each transaction returns its backup path:

```bash
bash install.sh --safe rollback --target /absolute/path/to/project --transaction .agents/super-board/backups/TRANSACTION/transaction.json --dry-run
bash install.sh --safe rollback --target /absolute/path/to/project --transaction .agents/super-board/backups/TRANSACTION/transaction.json
bash install.sh --safe uninstall --target /absolute/path/to/project --dry-run
bash install.sh --safe uninstall --target /absolute/path/to/project
```

Rollback refuses newer user edits. Interrupted operations retain before/after
journals; handled failures restore touched files automatically. Uninstall only
unlinks unchanged manifest-owned files/aliases and removes its AGENTS block.
No recursive directory removal. Backups/empty directories remain. Backups may hold
old user instructions: keep them private, local and ignored.
