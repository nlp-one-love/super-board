# Gitea provider (28.x)

An explicit REST provider and Codex-only runner. Missing `provider` retains the
original GitHub path. Gitea requires Python 3.9+, Git, Bash and signed-in Codex;
no gh or Claude Code. Codex technical helper skills must pass readiness separately.

## Per-project JSON

Save as `.claude/super-board/configs/demo.json`:

```json
{
  "version": 2,
  "provider": "gitea",
  "host": "codex",
  "gitea": {
    "url_env": "GITEA_URL",
    "owner_env": "GITEA_OWNER",
    "repo_env": "GITEA_REPO",
    "token_env": "GITEA_TOKEN",
    "timeout_seconds": 15
  },
  "project": {"scope": "repository", "id_env": "GITEA_PROJECT_ID"},
  "repo": {"path": "."},
  "base_branch": "develop",
  "columns": ["Backlog", "Ready", "Building", "QA", "Review", "Blocked", "Done"],
  "verify_commands": [],
  "required_status_contexts": ["test"],
  "max_dispatches": 3,
  "max_workers": 1,
  "human_approves_merge": true,
  "merge_policy": {"auto_merge": false, "default": "human"},
  "migrations": {"allowed_envs": []}
}
```

Replace empty verify_commands with real, trusted, project-owned commands before
run. Commands must not deploy, migrate or touch production. Required CI contexts
must match the project's actual commit statuses; empty/unknown checks are not green.
Use environment variables/secret manager for the token; never values in JSON, argv,
Git or chat. url/owner/repo/id can instead use explicit literal nonsecret fields.
Environment references are schema fields, never shell interpolation.

Project scopes: repository, organization (`project.owner` optional), individual
(authenticated user's board). Owner boards are filtered to one configured repo;
missing repository identity fails closed. A run must start at the matching origin's
root. Native Issue ID and repository-local number are distinct types.

## Commands and HTTP

`super-board-provider.py --config CONFIG` reads doctor/items/ids/status/item-id,
issue/comments/dependencies, pulls/pull/files/diff/checks/reviews. The existing card
wrapper routes Gitea before jq/gh. GitHub commands reuse the original board helper.

Explicitly approved `--allow-write` enables move/attach, create/update issue/PR and
comments. Create/update use JSON `--body-file`; comments use literal UTF-8 files.
Before editing a comment verify its owned marker/author. Reuse the exact issue PR.
The CLI exposes no generic HTTP mutation, merge, migration, provisioning or branch
rule edits. Generic Done moves are denied. Set up board/labels manually in v1.

TLS is required for real hosts, redirects are refused. Test-only
`allow_insecure_localhost: true` permits loopback HTTP. GET retries connection,
429/5xx failures at most three times; 401/403/404/422/423 do not retry. Long
Retry-After pauses. Pagination goes to an empty page and detects repeats, with
page/record/byte limits. API error bodies are not echoed.

Before a mutation, persist method/path/body-hash intent. Timeout/5xx/malformed
success/interruption leaves an uncertain-write journal; another write is refused.
Inspect the actual remote resource before `--reconciled resume`. Recovery never
replays a mutation. Bodies/tokens are absent from journals; state/backups are ignored.

## Contract and permissions

Source: actual Gitea 28.2.0 Swagger, structurally matched to the official tag.
[Contract](https://github.com/go-gitea/gitea/blob/v28.2.0/templates/swagger/v1-swagger.generated.json),
[route permissions](https://github.com/go-gitea/gitea/blob/v28.2.0/routers/api/v1/api.go).
An attributed subset is saved in `tests/fixtures/gitea-28.2-contract.json`.
Instance Swagger/UI returned 200; anonymous version returned 403. Doctor therefore
checks Swagger version/capabilities and reads configured repo/project/columns.

Repo Projects needs Projects unit/read and issue token scope; writes additionally
need Projects write/authentication and non-archived repo. Org boards involve org
access. PR/check/diff may require repository scopes. Exact minimum scopes across
the full cycle remain subject to sandbox validation; no admin/sudo is required.
Restrict the bot's protected-branch merge/push rights. Token scope does not override
repository/unit permissions.

## Runtime boundaries

Build → QA → Review uses Codex exec; the runner verifies a clean reported worktree,
exact committed head, issue branch/base and reruns project verification. It posts
lane results to the Issue, stores receipts and requires green CI for Review.
Successful Review stays at a head-bound human gate; an unchanged PR is not reviewed
again automatically. Changed head invalidates the receipt. A human merges outside
the runner. Finish proves merged state, current checks and merge ancestry before Done.

Sequential POSIX-only runs have one lock across checkout configs and bounded
max_dispatches (default 3, range 1..100). Multi-machine claims/Windows runs are not
supported. Assigned/ambiguous tasks require inspection. Native dependencies union
with upstream Markdown; human-only blockers never auto-clear. Closed non-human
dependencies are swept back to Ready during approved runs. Worktrees remain intact.

Existing Claude hooks are not active Codex guards. CLI denials/prompts do not remove
raw Git/HTTP capability from an agent with network and credentials. Validate Codex
permissions and server branch protections before live runs. No live Gitea mutation
or paid Codex cycle was executed during development. Optional GitHub collectors,
legacy workflows and draft-PR semantics are outside the certified Gitea path.
