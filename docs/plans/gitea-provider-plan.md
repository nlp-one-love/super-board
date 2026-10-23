# Super Board + Gitea 28.2 + Codex: аудит и план

Дата: 2026-10-24. Ниже сохранён первоначальный отчёт контрольной точки этапа 3.
Пользователь впоследствии разрешил реализацию и ограничил push своим форком;
результаты реализации описаны в конце документа.

## 1. Состояние workspace и доказательства

- Отдельный checkout: `/home/pzemlyanoy/work/repositories/my/super-board`.
- `origin`: `https://github.com/nlp-one-love/super-board.git` — URL предоставлен пользователем; GitHub API подтверждает fork и parent `EricTechPro/super-board`.
- `upstream`: `https://github.com/EricTechPro/super-board.git`.
- HEAD: `a2809b6a771113d07b5bfaeb7d38033a35245b8b`, ветка `main`, VERSION `3.1.2`. На момент клонирования рабочее дерево чистое. Единственное добавление после аудита — этот отчёт.
- Feature-ветка пока не создана: предложено `feature/gitea-provider`, название требует подтверждения. Merge/rebase/fetch tags/push/commit/PR/release не выполнялись.
- Доступны: Git 2.43.0, Codex CLI 0.164.0, Python 3.12.3, Bash 5.2.21. `gh` и `jq` отсутствуют; `gh auth status` выполнить невозможно. При необходимости пользователь может установить пакеты штатным менеджером ОС, например `sudo apt install gh jq`, затем самостоятельно выполнить `gh auth login`. Эти команды не выполнялись. Для будущего режима Gitea `gh` обязательным не будет.
- `codex login status`: `Logged in using ChatGPT`. Проверено без чтения credential-файлов и без запуска агентской задачи. Предупреждение CLI о невозможности создать PATH aliases в read-only области не мешает проверке входа; глобальная конфигурация не менялась.
- `git rev-parse --show-toplevel` подтвердил отдельный checkout; Git-операции выполнялись после проверки абсолютного пути. Родительская папка и соседние проекты не менялись.
- Upstream сначала прочитан из архива в `/tmp/super-board-audit`, затем проверен checkout форка с тем же SHA. Скачанные install/get скрипты не исполнялись. В checkout не обнаружено `AGENTS.md`.

### Проверенный API пользователя

Базовый адрес: `https://git.pzemlyanoy.ru`, предоставлен пользователем.

| Read-only запрос без токена | Результат |
|---|---|
| `GET /swagger.v1.json` | 200, JSON, `info.version = 28.2.0`, `basePath = /api/v1` |
| `GET /api/swagger` | 200, HTML интерфейс документации |
| `GET /api/v1/version` | 403; причина отказа без авторизации не установлена |

SHA-256 полученной спецификации: `5f173148cfcc8a88ef24220272f9f228e77e97daf1691088730ce0a3f905f44f`.
`paths` и `definitions` структурно совпадают с официальной Swagger-спецификацией тега Gitea `v28.2.0`. Это подтверждает опубликованный контракт, но **не подтверждает** доступ к конкретному репозиторию, включение Projects, права токена и работоспособность мутаций. Пользователь дополнительно подтвердил версию 28.2.

Основные источники:

- [Swagger экземпляра](https://git.pzemlyanoy.ru/swagger.v1.json), [интерфейс](https://git.pzemlyanoy.ru/api/swagger).
- [Официальный контракт v28.2.0](https://github.com/go-gitea/gitea/blob/v28.2.0/templates/swagger/v1-swagger.generated.json).
- [Маршрутизация и проверки прав](https://github.com/go-gitea/gitea/blob/v28.2.0/routers/api/v1/api.go), [реализация Projects](https://github.com/go-gitea/gitea/blob/v28.2.0/routers/api/v1/shared/project.go).
- [Аудируемая версия Super Board](https://github.com/EricTechPro/super-board/tree/a2809b6a771113d07b5bfaeb7d38033a35245b8b).
- [Официальная документация входа Codex](https://learn.chatgpt.com/docs/auth).

Для дополнительного discovery использован навык Postman api-discovery. Orbit search вернул HTTP 403; результаты и IDs не получены, импортов и изменений Postman нет. Выводы об API основаны на контракте экземпляра и исходниках фиксированного официального тега.

## 2. Фактическая архитектура

Super Board — набор Bash/Python helpers, Markdown skills и JS workflows; отдельного сервера и БД нет. Значительная часть orchestration задаётся инструкциями агенту, поэтому замены только сетевого клиента недостаточно.

1. `skills/super-board/SKILL.md` маршрутизирует onboard/lint/status/run/stop. Для Codex используется `$super-board <verb>`, skills обнаруживаются в `.agents/skills/`.
2. `references/onboard.md` и `scripts/super-board-setup.py` проверяют среду, создают конфигурацию, labels/колонки, подключают skills и guards. Onboard способен сам чинить конфигурацию и выполнять внешние записи; запускать его сейчас нельзя.
3. Конфиги — обычный JSON в `.claude/super-board/configs/<slug>.json`; active pointer локальный. `references/config-schema.json` — документ с комментариями JSON5, а не исполняемая JSON Schema. Есть `host`, `worker_backend`, `codex.model`, `verify_commands`, merge policy и migrations.
4. `super-board-card.sh` читает GitHub Projects v2 GraphQL и перемещает карточки через Status field/option IDs. Кэш IDs общий для worktrees; предусмотрен сброс устаревших IDs.
5. `super-board-deps.sh` объединяет `## Blocked by` в body и последнюю `blocked-by:` строку комментариев. Неоднозначный текст блокирует запуск. `blocked-by: -` означает человеческий gate, а не отсутствие зависимостей.
6. `super-board-wave-plan.sh` выбирает доступные Ready и уже начатые QA/Review задачи. `run-workflow.md` описывает wave loop; `workflows/super-board-wave.js` — Claude Workflow backend. `super-board-run.sh` — отдельный legacy `claude-p` dispatcher, не основной путь Codex.
7. `super-board-host.sh` определяет хост, отдавая приоритет среде живой сессии. В Codex запуск переключается на `--codex`. `super-board-codex-wave.sh` запускает карточки параллельно, внутри карточки lanes последовательны; `super-board-codex-lane.sh` вызывает `codex exec` с output schema и project-scoped permissions. В этом пути Claude-подагенты не нужны.
8. Локальные состояния: `.claude/super-board/{inflight,cache,...}`, `.claude/worktrees/`, run reports в `docs/super-board/runs/`. Восстановление опирается на доску, PR/комментарии и сохранённые локальные claims; stop также пишет комментарии и снимает assignees/labels через GitHub.
9. Verifier разделён: `super-board-verification-ready.py` требует непустые `verify_commands`; `super-board-project-verifier.py` проверяет project-owned evidence/maps. Preflight проверяет AC, дубликаты и пересечения работ.
10. `super-board-merge-gate.sh`: mutex → head/state → policy/approval → временный worktree и merge base → verify → migrations → повторная проверка approval → `gh pr merge --match-head-commit`. `super-board-approval.py` связывает доверенный запрос и человеческий `done` с head и hash scope; label не является разрешением.
11. `super-board-github-read.py` валидирует формы ответов, ограничивает read retries, сохраняет halt при недостоверных данных (79). `gh-guard`/throttle используют GitHub REST/GraphQL квоты; напрямую перенести их на Gitea нельзя.

### Установка и обновления

`install.sh` копирует skills/bin/workflows/hooks в `.agents/`, связывает их с `.claude/`, при выборе хоста — с `.codex/`/`.opencode/`. `.claude/` остаётся совместимым путём данных, это не означает обязательный запуск Claude Code.

Существующий installer уже переносит артефакты без `.git`, но **не удовлетворяет** требованиям безопасного update:

- `install_skill` очищает содержимое skill через `rm -rf`, затем копирует исходники; хеши локальных изменений не проверяются.
- Пользовательские symlinks могут вести наружу: installer разрешает запись по их физическим адресам. Для требуемой изоляции это необходимо изменить.
- `link_entry` удаляет прежний файл/каталог перед созданием ссылки. Нужны manifest ownership и проверка конфликта до первой записи.
- Settings merge сохраняет посторонние keys/hooks и делает backup; `super-board-agents-md.py` обновляет managed block, сохраняя текст вне маркеров. Общей транзакции обновления всех файлов нет.
- `upgrade.json` хранит from/to/added_skills и помогает onboard продолжить upgrade. Это не manifest всех файлов, не контрольные суммы и не полноценный rollback.
- `get.sh` умеет `--ref`, `SUPER_BOARD_REPO`, `SUPER_BOARD_TARBALL`, но допускает branch, latest и fallback на main; может запускать `npx ...@latest` для внешних skills. Для закреплённого Codex/Gitea пакета это поведение нужно ограничить.
- Release CI запускает offline suites, проверяет тег/HEAD/VERSION и публикует release. Собственного asset tarball + SHA256SUMS скрипт пока не создаёт. Regex тега в `.github/scripts/publish-release.sh` допускает только `vMAJOR.MINOR.PATCH`.

## 3. Карта операций и Gitea API

Все пути ниже относительно `/api/v1`. Сокращения: `R = /repos/{owner}/{repo}`, `P = R/projects/{id}`. Методы подтверждены Swagger экземпляра; записи в экземпляр не выполнялись.

| Операция | Сейчас в Super Board | Gitea 28.2 API | Нужное изменение | Риск |
|---|---|---|---|---|
| Выбор проекта | `gh project list/view`, GraphQL owner/node | `GET R/projects`, `GET P`; также `/orgs/{org}/projects`, `/user/projects`, `/users/{username}/projects` | Явный scope проекта и отдельные owner/repo/project ID | Org board может включать несколько repo |
| Создание проекта | onboard/setup, `gh project create` | `POST R/projects`, `CreateProjectOption` | Только явное onboard действие после разрешения | Не создавать в настоящем repo при doctor |
| Колонки | Projects v2 Status single-select options | `GET/POST P/columns`, `GET/PATCH/DELETE P/columns/{column_id}` | Колонка становится реальной сущностью, mapping по ID | Дубликаты названий; rename; закрытый проект |
| Порядок колонок | порядок Status options | `POST P/columns/move`, `{column_ids:[...]}`; `POST .../{column_id}/default` | Перестановка полного списка отдельно от задач | Нужен каждый ID ровно один раз |
| Список карточек | `card.sh items`, GraphQL с cursor | `GET P/columns/{column_id}/issues?page=&limit=` | Собрать все страницы всех колонок, нормализовать Issue/PR | Неполная выборка не означает пустую доску |
| Добавить Issue | `gh project item-add` | `POST P/columns/{column_id}/issues/{issue_id}` → 201 | Из Issue получить глобальный `id`; сохранить связь с локальным `number` | `issue_id` — не repo-local index |
| Сменить статус | `gh project item-edit`/GraphQL | `POST P/issues/{issue_id}/move`, `{column_id,sorting?}` → 204 | Отдельная команда provider board move; readback | Нет общего CAS по старой колонке |
| Issue и labels | `gh issue list/view/create/edit/close`, `gh label` | `GET/POST R/issues`, `GET/PATCH R/issues/{index}`, `R/labels`, `R/issues/{index}/labels` | Сохранить open/closed, title/body, assignees, label IDs | List issues включает PR: фильтровать по типу |
| Комментарии | `gh issue/pr comment`, REST/GraphQL histories | `GET/POST R/issues/{index}/comments`, `PATCH R/issues/comments/{id}`, `GET R/issues/{index}/timeline` | Маркеры owned blocks, нормализованные author/time/id | Не дублировать POST при неизвестном исходе |
| Зависимости | Markdown parser + последние block comments | `GET/POST/DELETE R/issues/{index}/dependencies` и `/blocks`; body `IssueMeta{owner,repo,index}` | Native dependencies + совместимая текстовая семантика | Human gate нельзя автоматически снять |
| Claims/stop/resume | local inflight + assignee edits, stop comments | `PATCH R/issues/{index}` + comments | Локальный атомарный lock, затем проверка актуального состояния | Assignee update не доказывает эксклюзивный distributed lock |
| PR создать/прочитать | `gh pr create/list/view` | `GET/POST R/pulls`, `GET/PATCH R/pulls/{index}`; `CreatePullRequestOption{head,base,title,body,...}` | REST provider, явный repo/base/head | В create schema нет поля draft; поведение draft нужно проверить |
| PR diff/files | `gh pr diff`, `gh pr view --json files` | `GET R/pulls/{index}.diff`, `GET R/pulls/{index}/files` | Нормализованные metadata и diff | Ограничения diff и pagination файлов |
| CI | GitHub PR checks/status fields | `GET R/commits/{ref}/status`, `/statuses`; `GET R/statuses/{sha}`; Actions runs/jobs из спецификации | Проверять required contexts для точного head | Пустые checks не означают green; нет прямой эквивалентности GitHub Checks |
| Review | GitHub review/history | `GET/POST R/pulls/{index}/reviews`, `POST .../reviews/{id}` | `commit_id`, states, stale/dismissed, owned report | Обязательные reviewers и права различаются |
| Доверенный approval | GraphQL comments + GitHub permission lookup | `GET R/collaborators/{collaborator}/permission` + comments | Отдельные normalized permissions, allowlist человека, scope включает host/provider/repo | Нельзя доверять login/label/любой фразе done |
| Branch policy | GitHub metadata/rules | `GET R/branch_protections`, `GET .../{name}` | Read-only диагностика, не ослаблять правила | Чтение правил может требовать дополнительных прав |
| Merge | gate → `gh pr merge` | `GET/POST R/pulls/{index}/merge`; `head_commit_id` в MergePullRequestOption | В v1 mutation merge недоступна автоматическому run; ручной merge владельцем | Оригинальный gate умеет merge и migrations |
| Квоты и ошибки | GitHub cost/rateLimit + guard | HTTP + APIError `{message,url}`; конкретная политика экземпляра не проверена | Общий retry/backoff/таймаут и provider-specific telemetry | Нельзя переносить 5000 GraphQL points/hour |

### Контракт, права и ограничения

- `Project`: `id`, `type` (`repository`, `organization`, `individual`), `state`, title, owner/repo IDs. Standalone note cards контрактом не поддерживаются; работаем с Issues/PR.
- `ProjectColumn`: `id`, `project_id`, `title`, `sorting`, `default`. В edit sorting ограничен -128..127. `MoveProjectIssueOption` требует `column_id`, sorting опционален; неизвестный/чужой column ID — ошибка.
- Native move не требует удалить и заново добавить карточку; использовать именно move. Добавление в колонку при необходимости связывает Issue с проектом.
- Repo Projects routes в исходниках требуют Projects unit read, для мутаций — authenticated token + Projects write, repo не archived. Внешняя группа использует token category `issue`; org routes также под organization scope. Значит обычного доступа к Git недостаточно.
- Для repo sandbox исходная гипотеза scopes: read/write issue для задач/доски, read repository для metadata/status/diff, write repository для нужных PR операций, read user только если нужен `/user`. Точные минимальные scopes для всего рабочего цикла **ещё не проверены**. Подтвердить отдельными read-only запросами под ограниченным токеном и разрешёнными sandbox mutations; admin/sudo не нужны. Scope не отменяет права пользователя на unit/репозиторий.
- Authentication: `Authorization: token <env value>`; не query token, не URL credentials. Имя env можно хранить в конфиге, значение нельзя. Не передавать токен в argv. Редактировать логи до вывода; не печатать headers/raw exception, если они содержат секрет.
- Pagination для Projects/columns/issues/comments/dependencies/reviews — `page` (1-based) + `limit`. Проверять следующую страницу/Link, ограничивать число страниц и обнаруживать циклы; не считать `len < requested_limit` универсальным концом, сервер может урезать limit. Конкретные runtime headers/default/max limit экземпляра **не проверены**.
- 401/403 — остановка с диагностикой авторизации; 404 может скрывать отсутствие права/выключенный Projects, это не всегда отсутствие сущности. 422 — validation; 423 — archived/locked; merge также 405/409. 429/5xx и timeout: bounded read retries с backoff/jitter, учитывать Retry-After при наличии. Универсальный rate-limit endpoint и фактические proxy limits **не проверены**.
- Не повторять create/comment/PR/move вслепую после timeout. Сохранить intent и reconciliation-required, затем readback; повторить только при доказанном невыполнении или документированной идемпотентности.
- Native dependencies не заменяют human-only блокировки. Предложение v1: union native blockers с явно указанными Markdown blockers; последний block comment сохраняет upstream precedence для текстового источника, `blocked-by: -` всегда держит human gate. Ошибка чтения/конфликт источников — halt или Blocked, не runnable. Межрепозиторные ссылки хранятся как полные IssueRef.
- Контракт не обещает distributed CAS claims. v1 ограничить одним владельцем run на общий checkout с атомарной блокировкой; второй run отказывает. Несколько независимых машин требуют отдельного решения и не объявляются поддержанными.

## 4. Минимальный дизайн провайдера

Два независимых выбора: `provider = github|gitea` и `host = codex|claude|opencode`. Основная комбинация пользователя — **gitea + codex**. Не делать поддельный gh и не устанавливать Claude Code для этого режима.

Сохранить Bash entry points, добавить stdlib Python CLI `scripts/super-board-provider.py` и пакет `scripts/super_board_providers/` (`__init__.py`, `models.py`, `base.py`, `github.py`, `gitea.py`, `http.py`). GitHub реализация сначала делегирует существующему bounded gh reader и сохраняет регрессионное поведение. Общие вызовы получают `--config`; bare gh остаётся только в github backend и в инструментах публикации GitHub release.

Минимальные типы/контракты:

- `RepoRef(provider, host, owner, name)`, `IssueRef(repo, number, native_id)`; `native_id` opaque, не подменяет `number`.
- `ProjectRef(scope, owner, repo?, native_id)`, `ColumnRef(project, native_id, name, order)`, `Task(issue, project, column, state, labels, assignees, body)`.
- `Comment(id, author_id, author_login, created_at, updated_at, body)`, `Dependency(issue, blocker, source)`.
- `PullRequest(number, head_sha, head_branch, base_branch, state, merge_sha, url)`, `Check(context, sha, state)`, `Review(author, sha, state, stale)`.
- `list_projects/get_project/list_columns/list_tasks/move_task/attach_issue`; `get/list/create/update_issue`, labels, comments; dependencies; PR list/get/create/update/files/diff; checks/reviews/permissions; `capabilities/doctor`.
- `merge` существует в контракте как отдельная опасная операция, по умолчанию denied. У GitHub прежнее поведение сохраняется для прежних конфигов; у нового gitea run его вызов запрещён независимо от агентского текста. V1 заканчивает Review человеческим gate; Done только после подтверждённого внешнего merge и присутствия merge SHA на base, либо явно допустимого upstream завершения без PR.
- Нормализованные ошибки: auth, forbidden, missing, conflict, validation, rate-limit, unavailable, uncertain-write. Неизвестные/неполные evidence останавливают dispatch; сохранить смысл exit 9/10/79 для callers.

Рекомендуемый конфиг — расширение имеющегося JSON, без YAML и универсальной env-интерполяции:

```json
{
  "version": 2,
  "provider": "gitea",
  "host": "codex",
  "gitea": {
    "url_env": "GITEA_URL",
    "owner_env": "GITEA_OWNER",
    "repo_env": "GITEA_REPO",
    "token_env": "GITEA_TOKEN"
  },
  "project": {"scope": "repository", "id_env": "GITEA_PROJECT_ID"},
  "repo": {"path": ".", "remote": "https://git.example.invalid/OWNER/REPO.git"},
  "base_branch": "develop",
  "columns": ["Backlog", "Ready", "Building", "QA", "Review", "Blocked", "Done"],
  "verify_commands": ["REPLACE_WITH_PROJECT_CHECK_COMMAND"],
  "max_workers": 1,
  "max_dispatches": 3,
  "human_approves_merge": true,
  "merge_policy": {"default": "human", "auto_merge": false},
  "migrations": {"allowed_envs": []}
}
```

Это проект формата, **не готовый конфиг для запуска**: placeholder verify command должен отклоняться doctor до замены. Поля env явно разрешены схемой; не выполнять shell expansion. Существующий конфиг без provider трактовать как github. Не менять его host/backend и merge policy молча. Сохранить текущее расположение state под `.claude/`, чтобы не объединять provider-патч с миграцией всей файловой структуры.

### Конкретные затрагиваемые файлы

Добавить:

- `scripts/super-board-provider.py`, `scripts/super_board_providers/{__init__,models,base,github,gitea,http}.py`.
- `scripts/super-board-package.py` — небольшой helper существующего installer для manifest/plan/apply/rollback/uninstall/version/doctor.
- `tests/test_provider_contract.py`, `tests/test_gitea_provider.py`, `tests/test_provider_consumers.py`, `tests/test_package_lifecycle.py`, минимизированные фикстуры без секретов.
- `docs/gitea-provider.md`, `docs/codex-gitea-quickstart.md`, `docs/upgrading-fork.md`; текущий план сохраняется.

Изменить по группам:

- Board/core: `scripts/super-board-{card.sh,deps.sh,wave-plan.sh,status.py,preflight.sh,setup.py,stop.sh,pr-body.sh,approval.py,skills-ready.py,collect-state.py}`. Hydrate skills и approval вызывают reader динамически и должны войти в аудит независимо от простого поиска `gh`.
- Codex path: `scripts/super-board-codex-{lane,wave}.sh`; заменить GitHub-only prechecks и prompts, запретить автоматический merge, добавить run lock до запуска ребёнка. Текущий wave lock записывается после Popen и защищён mutex только внутри процесса; это недостаточно против двух отдельных запусков.
- Gates/guards: `scripts/super-board-{merge-gate.sh,merge-policy.py,github-read.py,gh-guard.sh,throttle.sh}`; generic halt/read dispatch отделить от gh-specific квот. `github-read.py` оставить совместимым GitHub entry point. `hooks/cleanup-wt.py` получает provider state; guards не считать активными в Codex только потому, что установлены Claude hooks.
- Writes из lanes: `scripts/super-qa-file-bug.sh`, `scripts/super-review-file-refactor.sh`, `skills/super-collect/scripts/{super-collect-file.sh,collect_prs.py}`, `skills/super-build/scripts/super-build-dispatch.sh`; для optional GitHub-specific collector источников в Gitea выдавать unsupported явно, а не обращаться к gh.
- Agent инструкции: `skills/super-board/SKILL.md`, `references/{config-schema.json,onboard.md,run.md,run-workflow.md,stop.md,status.md,lint.md,block-template.md,agents-md-block.md,rate-limit-etiquette.md,pr-author-notes.md}`, `skills/super-{build,qa,review,collect}/SKILL.md`, worker/iteration preambles. Git-sync должен учитывать запреты push/force/rebase и отдельно не становится разрешением на них.
- Compatibility: `workflows/super-board-wave.js`, `scripts/super-board-run.sh` — GitHub по умолчанию, явный отказ неподдерживаемой gitea/legacy комбинации; не переписывать Claude workflow в первой итерации.
- Packaging/CI: `install.sh`, `get.sh`, `.github/scripts/publish-release.sh`, `.github/workflows/{release,cross-platform}.yml`, `VERSION`, `RELEASING.md`, README и `docs/hosts.md`. Новые Python package files должны попасть в явный allowlist installer.

## 5. Что сохраняем и что требует адаптации

| Подсистема | Сохраняем | Обязательная граница изменения |
|---|---|---|
| Codex runtime | `codex exec`, output schema, последовательность lanes, остановка дочерних процессов | Provider prechecks/prompts; проверить flags на 0.164.0 позже без платного run |
| Git/worktree | стандартный git, отдельные ветки, общий state, evidence | Remote parsing любого Gitea host; разрешённые пути; никаких force/deletion без разрешения |
| Build/QA/Review | AC, независимая проверка, bounce, rebuild cap, human Blocked | PR/board/comment transport и завершение Review без auto merge |
| Verifier | project-owned карты и `verify_commands`, halt при missing/stale | Команды только из доверенного локального config, не из Issue; без production side effects |
| Guards | детектирование секретов, опасных путей, защищённых веток | Claude hook wiring не доказывает исполнение в Codex. Поддержку проверять отдельно; ключевые ограничения выполнять в CLI/provider/install |
| Merge gate | актуальный SHA, зелёные проверки, policy, trust, mutex | Нельзя оставить файл побайтно: есть gh, миграции, merge и опасная cleanup. Для Gitea v1 migrations и merge mutation выключены |

## 6. Риски и решения

1. **GitHub зависимость находится также в prompts.** Агент, прочитав старый run.md, может вызвать gh напрямую. Provider consumer tests должны охватывать rendered prompts/skill references и запрет gh в gitea path.
2. **Сохранение GitHub без регрессий.** Вначале characterization tests существующих payload/exit contracts, затем extraction. Не менять весь JSON shape и все Bash scripts за один шаг.
3. **Кроссрепозиторная неоднозначность.** Repo, host, project scope и Issue ID входят в кэш/claims/approval scope; board другого repo не запускает изменение в текущем checkout.
4. **Изменения на сервере человеком.** Перед mutation читать актуальные head/колонку; readback после результата; при rename/duplicate column не угадывать. Native API не гарантирует atomic compare-and-swap для move.
5. **Неполные данные и повторные записи.** Halt с сохранением worktree/approval/claims; read retry отдельно от mutation reconciliation. Не превращать 403/пустой truncated ответ в Done или no blockers.
6. **Безопасность Codex.** Текущий launcher даёт project/git-dir/common-dir write и сеть при `approval_policy=never`; этого недостаточно для жёсткой защиты от произвольного push/merge агентом. V1 не запускать платные lanes до проверки permissions и credential surface; по возможности bot без merge/protected push rights. В instruction layer запретить merge; в собственном CLI fail closed; серверные branch protections — независимый барьер. Нельзя обещать защиту только prompt-правилом.
7. **Hooks и cleanup.** Upstream protected-push guard разрешает force на feature branches, что расходится с данным ТЗ. Upstream cleanup удаляет worktrees/ветки; installer использует recursive deletion. В текущем исследовании это не запускалось. Будущие сценарии обязаны соблюдать отдельное разрешение на destructive действия и сохранять пользовательские данные.
8. **Production/migrations.** Штатный gate исполняет migrate commands; отключить этот путь в первом Gitea режиме и не считать dry-run существующего gate гарантированно безвредным: он всё равно работает с git/worktree/verification.
9. **Installer.** Manifest должен проверять path traversal, symlink parents/targets, hardlinks и фактический git root; refuse install в общей папке репозиториев. Без молчаливого follow-symlink наружу. Все конфликты обнаружить до первого изменения.
10. **Стоимость.** Wave включает router плюс до трёх Codex lanes на карточку и повторные QA/Review/build bounce; отсутствие Claude не делает вызовы бесплатными или безлимитными. Начать с `max_workers=1`, ограниченного dispatch/rebuild, без автоматического повышения модели и без paid evals. Конкретные лимиты подписки/доступные модели не проверены. Уже выполнен только read-only login status.
11. **Обновления upstream.** Существенное поведение задано Markdown, shell и fixtures; конфликты вероятны. Сохранять небольшой provider seam и отдельные commits по группам; не обещать бесконфликтный sync.

## 7. Этапы реализации и приёмка после разрешения

| Этап | Работа | Проверка и условие приёмки |
|---|---|---|
| 0 | Подтвердить ветку и разрешение; согласовать jq/gh setup при необходимости | Изолированный clean checkout; без установки в рабочие проекты |
| 1 | Contracts/models и GitHub extraction | Characterization fixtures совпадают; старые config и exit codes сохранены |
| 2 | Gitea HTTP + read-only doctor/board/issues/deps/PR/checks | Локальный HTTP mock: auth/errors, page caps, malformed/truncated data, no leaked token; ни одного реального write |
| 3 | Mock-only mutation commands и Codex consumer wiring | Issue attach/move, comments, PR, uncertainty reconciliation; запрет merge/migrations даже при неверном config; no gh/Claude executable в gitea+codex |
| 4 | Stop/resume/claims/review gate | Два процесса не запускают одну карточку; interruption сохраняет состояние; old head approval не действует; изменившиеся checks/права блокируют |
| 5 | Packaging | Чистая/repeat install, update dry-run, conflict до записи, backup/rollback, uninstall только owned unchanged; path/symlink/hardlink/traversal cases; `.git` никогда не поставляется |
| 6 | CI и документация | Upstream `bash tests/run-safety.sh` + новые offline tests; linux/macOS и существующая smoke matrix; release assets/checksum/tag constraints |
| 7 | Отдельно разрешённый sandbox smoke | Сначала authenticated GET; затем одна test Issue/card/PR, движения и отказ merge; без production, автоматического merge и неожиданной очистки |
| 8 | Отдельно разрешённый Codex full cycle | Build → QA → Review, bounce/resume, human gate; Done после вручную подтверждённого merge. Фиксировать число запусков и лимиты |

Тесты HTTP использовать изолированными локальными fixtures/mock server; не создавать настоящие Issues/PR для unit tests. Regression охватывает `test-card`, `test-deps`, `test-preflight`, `test-merge-gate`, approval, `test-codex-*`, `test-stop`, installer/get/settings/upgrade и весь CI runner после подготовки зависимостей. Точные имена некоторых suite: `test-codex-stop.sh`, `test_upgrade_recovery.py`, `test_approval.py`.

## 8. Поставка и обновление форка

Минимально расширить install/get, вынести файловые операции в один stdlib helper; не создавать daemon/package manager. Пакет — allowlist skills/scripts/workflows/hooks + VERSION + file manifest. Release asset содержит source/tag/commit и SHA256SUMS; не использовать fallback main и не выполнять `npx @latest` автоматически. Хеш с той же страницы защищает от повреждения, но сам по себе не доказывает происхождение; закреплённый источник/тег обязателен.

Установленный manifest: relative path, kind/file-or-link, expected SHA-256 или target ссылки, package version/tag/commit/source. Пользовательские config/state и текст AGENTS вне блока не становятся owned. Перед apply — полный plan add/change/remove/conflict, backup изменяемых файлов и journal; прерванная транзакция явно восстанавливается. Update/uninstall не удаляет локально изменённые и посторонние файлы; rollback также проверяет конфликт с новыми пользовательскими правками.

Команды: install/update (`--dry-run`)/doctor/version/uninstall/rollback. Пока релизов форка с такой поставкой нет, временный сценарий — после одобрения протестировать reviewed `./install.sh /absolute/path/to/isolated-sandbox` из checkout, без выполнения сейчас и без реального рабочего проекта.

Политика веток: main близко к upstream; feature/integration branch содержит Gitea изменения. Upstream fetch/diff → отдельное согласование merge/rebase → tests → разрешённый push/PR → ручное review/merge → отдельно разрешённый релиз. Предложение тегов форка: `v3.1.2-gitea.1` (upstream base + fork iteration); текущий release regex потребуется изменить и протестировать. Не выпускать этот тег до реализации и приёмки.

## 9. Проверено, ограничения, нужные данные

**Сделано:** отдельный clone форка, добавлен upstream remote, прочитаны реальные scripts/skills/workflows/install/get/config/CI/test runner, изучен контракт и Projects routes Gitea 28.2.0. Создан только этот отчёт, код не изменён.

**Проверено:** версии инструментов; GitHub fork metadata; absolute checkout root/remotes/HEAD/clean status; 200 Swagger/UI и 403 version; равенство paths/definitions официальному тегу; `codex login status`; статический `ast.parse` 19 Python файлов scripts/hooks и `bash -n` 19 Bash файлов scripts/install/get — PASS. Это синтаксические проверки, не функциональные тесты.

**Не проверено:** полный upstream suite (нет jq; tests не запускались), фактическая авторизация Gitea, конкретный repo/project/columns, scopes и branch rules, runtime pagination/rate limits, draft PR, мутации, end-to-end Codex, installer lifecycle, macOS/Windows. Платные agent runs и evals не запускались.

**Риски другим репозиториям/Gitea:** выполненные действия ограничены новой директорией форка и `/tmp`; на Gitea только три GET без авторизации. Ни Issues, ни карточки, ни комментарии, ни PR, ни настройки сервера не менялись. Отчёт не содержит секретов.

**Нужно сейчас:** решение об архитектуре, разрешение реализации и подтверждение имени `feature/gitea-provider`.

**Нужно позднее:** точные sandbox owner/repo, scope и project ID, base branch, реальные project-owned verify commands; `GITEA_URL`, `GITEA_OWNER`, `GITEA_REPO`, `GITEA_PROJECT_ID`, `GITEA_TOKEN` через локальную среду/секрет-хранилище, без секретов в чате. Для первого соединения достаточно read-only доступа. Отдельно согласовать sandbox writes и отдельно полный лимитируемый Codex цикл. Создание sandbox, push/PR/release и destructive cleanup не разрешены этим отчётом.

**Следующий минимальный шаг:** после решения пользователя создать согласованную feature-ветку и реализовать контракты + GitHub characterization; до этого остановиться на данной контрольной точке.

## 10. Реализация после одобрения

Разрешение пользователя: «начни реализовывать. Автора не беспокоим (пушим только в форк)».
Ветка: `feature/gitea-provider`; версия рабочего пакета `3.1.2-gitea.1`.

Добавлены provider contracts/models, GitHub board compatibility wrapper и Gitea
REST backend, отдельные CLI provider/runner/package/download, Gitea lifecycle и
три документа настройки/установки/обновления. Старый GitHub путь остаётся default;
Gitea card wrapper маршрутизируется до jq/gh, legacy Codex/merge helpers явно
отказывают Gitea. Выбран отдельный последовательный Gitea runner, чтобы не смешать
извлечение провайдера с переписыванием legacy Claude workflows.

Реализованы чтение Projects/колонок/карточек/Issues/PR/CI/reviews, native moves,
ограниченные issue/PR/comment mutations, bounded retries/pagination, redaction,
журнал неизвестного исхода записи и ручное reconciliation. Done через обычный move
или attach запрещён; merge запрещён в CLI/backend/старом gate. Run использует
Codex exec, readiness, отдельный worktree, проверку exact head/base/branch, повтор
project verification, сохранение результатов в Issue и head/policy-bound human gate.
Finish только подтверждает внешний ручной merge и ancestry. Stop останавливает
дочернюю process group, сохраняя работу; один POSIX lock действует на checkout.

Safe install/update поддерживают manifest с per-file SHA-256, dry-run/conflicts,
backup journal, автоматический откат обработанного сбоя, ручной rollback и uninstall
только owned файлов/ссылок. Recursive deletion нет. Конфиг/state не перезаписываются;
AGENTS вне блока сохраняется. Downloader закреплён на release assets форка, сверяет
checksum/source/tag и не запускает скачанные scripts. Release publisher расширен
fork tags/assets; тег/релиз/PR этой реализацией не создаются.

Проверки: 31 новый provider/runtime HTTP test + 13 package/download lifecycle tests
прошли. Включены native ID, pagination, 403/429/503/timeout/redirect, неопределённая
запись без повтора, запрет merge/Done, human dependencies, exclusive locks, symlink
state, GitHub board payload, fake Codex Build/QA/Review, остановка процесса и
завершение только после ручного merge. Package tests покрывают локальные конфликты,
rollback после ошибки/upgrade, новые пользовательские правки, uninstall, block-level
AGENTS ownership, symlink/hardlink/traversal и вредоносный архив.

Выбранные upstream regressions: status parser 25/25, verification readiness 5/5,
approval 30/30, Codex schema contract и hosts doc — PASS. Bash syntax/Python AST
и `git diff --check` — PASS. Полная safe-install smoke из checkout: 185 paths,
повторный dry-run без изменений, doctor и импорт установленного provider — PASS.
Отдельный Node mock принял реальные GET → POST(global ID 9001) → GET клиента;
43 запроса записаны локально без headers/secrets.

Postman CLI 1.75.0 не запустил simulation из-за ошибки dataset backend. Сохранён
локальный mock + sim и исходный subset Swagger 28.2.0; доказательства исполнения
получены через stdlib HTTP tests и прямой Node запуск. Облачные mock/workspace
не создавались. jq получен из пакетов штатного apt-репозитория и только распакован
в `/tmp` для тестов; установка/maintainer scripts/global config не выполнялись.

Ограничения: полный upstream shell suite не выполнялся, поскольку в нём есть
recursive cleanup, для которого ТЗ требует отдельного разрешения. Live sandbox
scopes/права/CI/draft semantics, реальные Gitea mutations и платный Codex цикл
не проверены и остаются отдельной контрольной точкой. Gitea runtime пока POSIX-only,
одна машина/один worker; provisioning и optional GitHub collectors в этот путь не
включены. Перед релизом нужны согласованная тестовая Gitea песочница и smoke.
