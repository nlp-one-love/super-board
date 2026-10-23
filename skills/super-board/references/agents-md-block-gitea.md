## Super Board: Gitea + Codex

Provider: Gitea REST. Agent: Codex CLI. Authoritative lifecycle:
`.agents/skills/super-board/references/gitea-run.md`.
GitHub onboard/run instructions and Claude workflows do not apply to this project.

Run from the project root using the selected JSON config:

```bash
python3 .agents/bin/super-board-gitea.py --config CONFIG doctor
python3 .agents/bin/super-board-gitea.py --config CONFIG status
python3 .agents/bin/super-board-gitea.py --config CONFIG plan
```

- Board: Backlog, Ready, Building, QA, Review, Blocked, Done.
- Build/QA/Review use Codex, one task per branch/worktree under `.claude/worktrees/`.
- Start `run --allow-write --allow-agent-run` only after explicit project/write/usage approval.
- Never launch Claude Code or gh for this project. Use the provider CLI for Gitea.
- Never merge automatically or run migrations/production changes. Human performs merge.
- `finish NUMBER --allow-write` verifies a recorded review, merged PR, CI and ancestry before Done.
- Never force push, rebase shared history, delete branches or recursively clean worktrees.
- Run configured project verification; missing evidence or unknown CI halts.
- `stop` preserves branch/worktree/PR/receipts; inspect them before explicit resume.
- Tokens only through the configured environment variable; never commit or print secrets.
- Human-only blockers never auto-clear. Unknown write outcome requires reconciliation.
- Claude hooks are not Codex guards; validate permissions and server branch protections.
