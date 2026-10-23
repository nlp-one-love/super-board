#!/usr/bin/env python3
"""Real HTTP tests against a contract-derived local Gitea stand-in, never live Gitea."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from super_board_providers.gitea import Gitea
from super_board_providers.base import ProviderError
from super_board_providers.http import HTTP
from super_board_providers import load

spec = importlib.util.spec_from_file_location('gitea_runner', ROOT / 'scripts/super-board-gitea.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.answer('GET')

    def do_POST(self):
        self.answer('POST')

    def do_PATCH(self):
        self.answer('PATCH')

    def answer(self, method):
        server = self.server
        url = urlsplit(self.path); page = int(parse_qs(url.query).get('page', ['1'])[0])
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or 'null')
        server.calls.append((method, url.path, page, body))
        if server.delay:
            time.sleep(server.delay)
        if self.headers.get('Authorization') != 'token ' + server.token:
            self.send(401, {'message': 'wrong token'}); return
        if server.error:
            self.send(server.error, {'message': server.token}); return
        if url.path == '/api/v1/redirect':
            self.send_response(302); self.send_header('Location', 'http://127.0.0.1:1/secret'); self.end_headers(); return
        if url.path == '/swagger.v1.json':
            prefix = '/repos/{owner}/{repo}/projects/{id}'
            self.send(200, {'info': {'version': '28.2.0'}, 'paths': {
                prefix + '/columns': {'get': {}}, prefix + '/issues/{issue_id}/move': {'post': {}},
                prefix + '/columns/{column_id}/issues': {'get': {}},
                '/repos/{owner}/{repo}/issues/{index}/dependencies': {'get': {}}}}); return
        path = url.path.removeprefix('/api/v1/repos/acme/demo')
        if method == 'POST' and path == '/projects/7/issues/9001/move':
            if not body or body.get('column_id') not in range(1, 8):
                self.send(422, {}); return
            server.column = body['column_id']; self.send(204, None); return
        if method == 'POST' and path in ('/issues/11/comments', '/issues/31/comments'):
            server.comments.append(dict(id=len(server.comments) + 1, **body))
            self.send(201, server.comments[-1]); return
        if method == 'PATCH' and path == '/issues/11':
            server.issue.update(body); self.send(200, server.issue); return
        if method != 'GET':
            self.send(501, {'message': 'Unmodelled mutation'}); return
        if path == '':
            self.send(200, {'id': 1, 'full_name': 'acme/demo', 'archived': False}); return
        if path == '/projects/7':
            self.send(200, {'id': 7, 'state': 'open'}); return
        if path == '/projects/7/columns':
            rows = [{'id': n, 'project_id': 7, 'title': name} for n, name in enumerate(
                ['Backlog', 'Ready', 'Building', 'QA', 'Review', 'Blocked', 'Done'], 1)]
            if server.duplicate:
                rows[1]['title'] = rows[0]['title']
            self.send(200, rows if page == 1 or server.repeat else []); return
        if path.startswith('/projects/7/columns/') and path.endswith('/issues'):
            self.send(200, [server.issue] if int(path.split('/')[4]) == server.column and page == 1 else []); return
        if path == '/issues/11':
            self.send(200, server.issue); return
        if path == '/pulls/31':
            self.send(200, {'number': 31, 'head': {'sha': server.head, 'ref': 'issue-11-test'},
                           'base': {'ref': 'main'}, 'state': 'closed' if server.merged else 'open',
                           'merged': server.merged, 'merge_commit_sha': server.head if server.merged else None}); return
        if path == '/issues/11/comments':
            self.send(200, server.comments if page == 1 else []); return
        if path == '/issues/11/dependencies':
            self.send(200, server.dependencies if page == 1 else []); return
        if path == '/statuses/' + server.head or path == '/statuses/' + 'a' * 40:
            self.send(200, server.statuses if page == 1 else []); return
        self.send(501, {'message': 'Unmodelled endpoint'})

    def send(self, code, value):
        payload = b'' if value is None else json.dumps(value).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload))); self.end_headers()
        try:
            self.wfile.write(payload)
        except BrokenPipeError:
            pass


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        s = self.server
        s.token = 'unit-test-placeholder'; s.calls = []; s.error = None; s.column = 2
        s.repeat = False; s.duplicate = False; s.comments = []; s.dependencies = []; s.statuses = []
        s.head = 'a' * 40; s.merged = False
        s.delay = 0
        s.issue = {'id': 9001, 'number': 11, 'title': 'Task', 'body': '## Blocked by\n- None\n',
                   'state': 'open', 'labels': [], 'assignees': [], 'html_url': 'https://example.invalid/11'}
        self.env = __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {'GITEA_TOKEN': s.token})
        self.env.start(); self.addCleanup(self.env.stop)
        self.config = {'provider': 'gitea', 'host': 'codex', 'gitea': {'url': self.url, 'owner': 'acme', 'repo': 'demo',
                       'allow_insecure_localhost': True}, 'project': {'id': 7}, 'required_status_contexts': ['test']}
        self.state = Path(tempfile.mkdtemp(prefix='super-board-provider-test-'))

    def provider(self, write=False):
        return Gitea(self.config, allow_write=write, state_dir=self.state)

    def test_doctor_checks_contract_and_project(self):
        self.assertTrue(self.provider().doctor()['ready'])

    def test_direct_cli_reads_token_file_without_wrapper(self):
        token = self.state / 'private-token'; token.write_text(self.server.token + '\n'); token.chmod(0o600)
        config = self.state / 'config.json'; config.write_text(json.dumps(self.config))
        env = dict(os.environ, GITEA_TOKEN='', GITEA_TOKEN_FILE=str(token))
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/super-board-gitea.py'),
                            '--config', str(config), 'doctor'], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertTrue(result['authenticated']); self.assertEqual(result['credentialSource'], 'file')
        self.assertNotIn(self.server.token, p.stdout + p.stderr)

    def test_environment_token_has_explicit_precedence(self):
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        with patch.dict(os.environ, {'GITEA_TOKEN_FILE': str(self.state / 'absent')}):
            self.assertEqual(self.provider().token_source, 'environment')

    def test_no_credentials_fails_before_any_network_request(self):
        config = self.state / 'no-auth.json'; config.write_text(json.dumps(self.config))
        env = dict(os.environ, GITEA_TOKEN='', GITEA_TOKEN_FILE='')
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/super-board-gitea.py'),
                            '--config', str(config), 'doctor'], env=env, cwd=self.state,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 66, p.stderr)
        self.assertIn('No Gitea credentials configured', p.stderr)
        self.assertEqual(self.server.calls, [])

    def test_local_file_binding_survives_new_process_without_environment(self):
        project = self.state / 'credential-project'; project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        token = self.state / 'private-token'; token.write_text(self.server.token); token.chmod(0o600)
        config = self.state / 'config.json'; config.write_text(json.dumps(self.config))
        env = dict(os.environ, GITEA_TOKEN='', GITEA_TOKEN_FILE='')
        base = [sys.executable, str(ROOT / 'scripts/super-board-provider.py'), '--config', str(config)]
        bound = subprocess.run(base + ['auth', '--token-file', str(token)], cwd=project, env=env,
                               capture_output=True, text=True)
        self.assertEqual(bound.returncode, 0, bound.stderr)
        stored = (project / '.git/config').read_text()
        self.assertIn(str(token), stored); self.assertNotIn(self.server.token, stored)
        checked = subprocess.run(base + ['doctor'], cwd=project, env=env, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['credentialSource'], 'git-config-file')
        self.assertNotIn(self.server.token, bound.stdout + bound.stderr + checked.stdout + checked.stderr)
        replacement = self.state / 'replacement-token'
        replacement.write_text(self.server.token); replacement.chmod(0o600); token.unlink()
        repaired = subprocess.run(base + ['auth', '--token-file', str(replacement)], cwd=project,
                                  env=env, capture_output=True, text=True)
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.server.calls.clear()
        foreign = json.loads(config.read_text()); foreign['gitea']['repo'] = 'other'
        config.write_text(json.dumps(foreign))
        checked = subprocess.run(base + ['doctor'], cwd=project, env=env, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 66)
        self.assertEqual(self.server.calls, [])

    def test_project_local_binding_rejects_token_file_inside_git(self):
        from super_board_providers.credentials import bind_token_file
        project = self.state / 'bad-credential-project'; project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        token = project / 'private-token'; token.write_text(self.server.token); token.chmod(0o600)
        with self.assertRaises(ProviderError):
            bind_token_file(self.url + '/acme/demo', token, cwd=project)
        self.assertNotIn('tokenFile', (project / '.git/config').read_text())

    def test_unsafe_missing_and_symlink_token_files_fail_before_http(self):
        token = self.state / 'token'; token.write_text(self.server.token); token.chmod(0o644)
        linked = self.state / 'linked'; linked.symlink_to(token)
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        for path in (token, linked, self.state / 'missing'):
            with patch.dict(os.environ, {'GITEA_TOKEN': '', 'GITEA_TOKEN_FILE': str(path)}):
                with self.assertRaises(ProviderError) as caught:
                    self.provider()
                self.assertEqual(caught.exception.code, 66)
                self.assertNotIn(self.server.token, str(caught.exception))
        self.assertEqual(self.server.calls, [])

    def test_snapshot_uses_global_id_and_local_number(self):
        row = self.provider().items()['items'][0]
        self.assertEqual(row['id'], 9001); self.assertEqual(row['content']['number'], 11)
        self.assertEqual(row['status'], 'Ready')

    def test_write_requires_grant(self):
        with self.assertRaises(ProviderError) as caught:
            self.provider().move(11, 'QA')
        self.assertEqual(caught.exception.code, 7)
        self.assertFalse(any(c[0] != 'GET' for c in self.server.calls))

    def test_move_sends_native_id_and_reads_back(self):
        p = self.provider(True); result = p.move(11, 'QA')
        posts = [c for c in self.server.calls if c[0] == 'POST']
        self.assertEqual(posts, [('POST', '/api/v1/repos/acme/demo/projects/7/issues/9001/move', 1, {'column_id': 4})])
        self.assertEqual(result['status'], 'QA')
        p.move(11, 'QA')
        self.assertEqual(len([c for c in self.server.calls if c[0] == 'POST']), 1)

    def test_done_and_merge_denied(self):
        p = self.provider(True)
        for action in (lambda: p.move(11, 'Done'), lambda: p.attach(11, 'Done'),
                       lambda: p.write('POST', p.r + '/pulls/31/merge', {'do': 'squash'}), p.merge):
            with self.assertRaises(ProviderError) as caught:
                action()
            self.assertEqual(caught.exception.code, 7)
        self.assertFalse(any(c[0] == 'POST' for c in self.server.calls))

    def test_short_page_does_not_truncate(self):
        p = self.provider(); data = p.http.pages(p.p + '/columns')
        self.assertEqual(len(data), 7)
        self.assertEqual([c[2] for c in self.server.calls], [1, 2])

    def test_repeated_page_fails_closed(self):
        self.server.repeat = True
        with self.assertRaises(ProviderError):
            self.provider().columns()

    def test_duplicate_columns_fail_closed(self):
        self.server.duplicate = True
        with self.assertRaises(ProviderError):
            self.provider().columns()

    def test_auth_error_no_retry_or_secret_echo(self):
        self.server.error = 403
        with self.assertRaises(ProviderError) as caught:
            self.provider().issue(11)
        self.assertEqual(len(self.server.calls), 1)
        self.assertNotIn(self.server.token, str(caught.exception))

    def test_read_retries_5xx(self):
        self.server.error = 503
        with self.assertRaises(ProviderError):
            self.provider().issue(11)
        self.assertEqual(len(self.server.calls), 3)

    def test_429_read_is_bounded(self):
        self.server.error = 429
        with self.assertRaises(ProviderError) as caught:
            self.provider().issue(11)
        self.assertEqual(caught.exception.kind, 'rate-limit')
        self.assertEqual(len(self.server.calls), 3)

    def test_timeout_write_is_not_retried(self):
        self.server.delay = .3
        p = self.provider(True); p.http.timeout = .05
        with self.assertRaises(ProviderError) as caught:
            p.write('POST', p.r + '/issues/11/comments', {'body': 'test'})
        self.assertEqual(caught.exception.kind, 'uncertain-write')
        self.assertEqual(len(self.server.calls), 1)
        self.assertTrue((p.state / 'uncertain-write.json').exists())
        time.sleep(.35)

    def test_write_5xx_journal_blocks_replay(self):
        self.server.error = 503; p = self.provider(True)
        with self.assertRaises(ProviderError) as caught:
            p.write('POST', p.r + '/issues/11/comments', {'body': 'hello'})
        self.assertEqual(caught.exception.kind, 'uncertain-write')
        self.assertEqual(len(self.server.calls), 1)
        marker = p.state / 'uncertain-write.json'
        self.assertTrue(marker.exists()); self.assertNotIn('hello', marker.read_text())
        with self.assertRaises(ProviderError):
            self.provider(True).write('POST', p.r + '/issues/11/comments', {'body': 'hello'})
        self.assertEqual(len(self.server.calls), 1)
        self.assertTrue(p.reconcile(True)['reconciled'])
        self.assertFalse(marker.exists())

    def test_redirect_not_followed(self):
        with self.assertRaises(ProviderError) as caught:
            self.provider().http.request('GET', '/redirect')
        self.assertIn('302', str(caught.exception))

    def test_empty_checks_never_green(self):
        self.assertFalse(self.provider().checks('a' * 40)['green'])

    def test_latest_failure_wins(self):
        self.server.statuses = [{'id': 2, 'sha': 'a' * 40, 'context': 'test', 'status': 'failure'},
                                {'id': 1, 'sha': 'a' * 40, 'context': 'test', 'status': 'success'}]
        self.assertFalse(self.provider().checks('a' * 40)['green'])

    def test_green_requires_exact_sha_and_required_contexts(self):
        self.server.statuses = [{'id': 1, 'sha': 'a' * 40, 'context': 'test', 'status': 'success'}]
        self.assertTrue(self.provider().checks('a' * 40)['green'])
        self.config['required_status_contexts'] = []
        self.assertFalse(self.provider().checks('a' * 40)['green'])

    def test_plan_retains_human_gate(self):
        self.server.comments = [{'body': 'blocked-by: -'}]
        result = runner.plan(self.provider())
        self.assertFalse(result['cards']); self.assertTrue(result['blocked'][0]['humanGated'])

    def test_plan_unions_native_dependencies(self):
        self.server.dependencies = [{'id': 8, 'state': 'open'}]
        self.assertFalse(runner.plan(self.provider())['cards'])

    def test_missing_dependency_section_not_runnable(self):
        self.server.issue['body'] = 'No dependency evidence'
        self.assertFalse(runner.plan(self.provider())['cards'])

    def test_plan_never_reconciles_closed_to_done(self):
        self.server.issue['state'] = 'closed'
        result = runner.plan(self.provider())
        self.assertEqual(result['closed'], [11]); self.assertFalse(result['cards'])

    def test_nonhuman_cleared_blockers_are_swept(self):
        self.server.column = 6
        self.assertEqual(runner.plan(self.provider())['sweep'][0]['number'], 11)

    def test_runtime_state_symlink_cannot_escape(self):
        p = self.provider(True); outside = self.state / 'outside'; outside.mkdir()
        self.state.joinpath(p.identity).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ProviderError):
            p.write('POST', p.r + '/issues/11/comments', {'body': 'test'})
        self.assertFalse(list(outside.iterdir()))

    @unittest.skipUnless(shutil.which('jq'), 'GitHub helper requires jq')
    def test_missing_provider_keeps_original_github_board_shape(self):
        bin_path = self.state / 'github-bin'; bin_path.mkdir()
        fixture = [{'data': {'repositoryOwner': {'projectV2': {'items': {'totalCount': 1,
                    'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': [{
                    'id': 'PVTI_1', 'fieldValueByName': {'name': 'Ready'},
                    'content': {'__typename': 'Issue', 'number': 11, 'title': 'Task',
                                'url': 'https://github.com/acme/demo/issues/11',
                                'repository': {'nameWithOwner': 'acme/demo'}, 'labels': {'nodes': []}}}]}}}}}]
        fake = bin_path / 'gh'
        fake.write_text('#!/usr/bin/env python3\nprint(' + repr(json.dumps(fixture)) + ')\n'); fake.chmod(0o755)
        config = self.state / 'github.json'; config.write_text(json.dumps({
            'project': {'owner': 'acme', 'number': 7}, 'repo': {'remote': 'https://github.com/acme/demo'}}))
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        with patch.dict(os.environ, {'PATH': str(bin_path) + os.pathsep + os.environ['PATH']}):
            result = load(config).items()
        self.assertEqual(result, {'items': [{'id': 'PVTI_1', 'title': 'Task', 'status': 'Ready',
                'content': {'type': 'Issue', 'title': 'Task', 'number': 11,
                'url': 'https://github.com/acme/demo/issues/11', 'repository': 'acme/demo'}}], 'totalCount': 1})

    def test_invalid_url_or_provider_config_has_no_network(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/?token=x'):
            self.config['gitea']['url'] = url
            with self.assertRaises(ProviderError):
                self.provider()
        self.assertEqual(self.server.calls, [])

    def test_merge_gate_rejects_gitea_before_gh_or_jq(self):
        config = self.state / 'config.json'; config.write_text(json.dumps(self.config))
        p = subprocess.run(['bash', str(ROOT / 'scripts/super-board-merge-gate.sh'), '--config', str(config)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 7, p.stderr)

    def test_card_entrypoint_routes_without_jq(self):
        config = self.state / 'config.json'; config.write_text(json.dumps(self.config))
        p = subprocess.run(['bash', str(ROOT / 'scripts/super-board-card.sh'), '--config', str(config), 'items'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['items'][0]['id'], 9001)

    def test_parallel_run_lock_is_exclusive(self):
        with runner.run_lock(self.state / 'one'):
            with self.assertRaises(ProviderError):
                with runner.run_lock(self.state / 'two'):
                    pass

    def test_runner_status_is_read_only_and_does_not_invent_active_worker(self):
        state = self.state / 'run/board'
        self.assertEqual(runner.run_state(state)['lockState'], 'idle')
        self.assertFalse(state.exists())
        runner.save(state / 'active.json', {'number': 11, 'lane': 'build', 'status': 'Ready', 'body': 'private task data'})
        info = runner.run_state(state)
        self.assertIsNone(info['activeTask']); self.assertEqual(info['lastTask']['number'], 11)
        self.assertNotIn('private task data', json.dumps(info))
        with runner.run_lock(state):
            info = runner.run_state(state)
            self.assertEqual(info['lockState'], 'busy'); self.assertEqual(info['activeTask']['number'], 11)
        self.assertEqual(runner.run_state(state)['lockState'], 'idle')

    def test_runner_status_reports_stop_and_saved_receipts(self):
        state = self.state / 'run/board'
        runner.save(state / 'stop-request.json', {'stop': True})
        runner.save(state / 'lane-11-build.json', {'status': 'passed', 'pr': 31, 'detail': 'hidden command output'})
        info = runner.run_state(state)
        self.assertTrue(info['stopRequested']); self.assertEqual(info['reports'][0]['pr'], 31)
        self.assertNotIn('hidden command output', json.dumps(info))

    def setup_fake_runtime(self):
        root = self.state / 'project'; root.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
        git('init', '-q', '-b', 'main')
        (root / '.gitignore').write_text('.claude/\n')
        (root / 'README').write_text('fixture project\n')
        git('add', '.gitignore', 'README')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        wt = root / '.claude/worktrees/issue-11'
        git('worktree', 'add', '-q', '-b', 'issue-11-test', str(wt))
        self.server.head = git('rev-parse', 'HEAD')
        self.server.statuses = [{'id': 1, 'sha': self.server.head, 'context': 'test', 'status': 'success'}]
        self.config.update(repo={'path': str(root)}, base_branch='main', verify_commands=['python3 -c "assert 2 + 2 == 4"'],
                           max_dispatches=3, human_approves_merge=True, merge_policy={'auto_merge': False})
        config = self.state / 'runtime.json'; config.write_text(json.dumps(self.config))
        bin_path = self.state / 'bin'; bin_path.mkdir()
        fake = bin_path / 'codex'
        fake.write_text('#!/usr/bin/env python3\nimport sys,json,os,time\nfrom pathlib import Path\n'
                        'prompt=sys.stdin.read()\nphase=prompt.split("worker",1)[0]\n'
                        'time.sleep(10 if os.environ.get("FIXTURE_SLEEP") else 0)\n'
                        'data={"status":"human-gate" if "review" in phase else "passed", "detail":"fixture verification",'
                        '"pr":31,"head":os.environ["FIXTURE_HEAD"],"worktree":os.environ["FIXTURE_WORKTREE"]}\n'
                        'Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps(data))\n')
        fake.chmod(0o755)
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        env = patch.dict(os.environ, {'PATH': str(bin_path) + os.pathsep + os.environ['PATH'],
                                     'FIXTURE_HEAD': self.server.head, 'FIXTURE_WORKTREE': str(wt)})
        env.start(); self.addCleanup(env.stop)
        skills = patch.object(runner, 'skills_ready', return_value={'ready': True, 'entries': []})
        skills.start(); self.addCleanup(skills.stop)
        return root, config, git

    def test_mock_codex_full_cycle_and_human_gate(self):
        root, config, _ = self.setup_fake_runtime()
        provider = self.provider(True)
        state = self.state / 'runs/board'; state.mkdir(parents=True)
        result = runner.run(provider, config, root, state, True)
        self.assertEqual([c['lane'] for c in result['cards']], ['build', 'qa', 'review'])
        self.assertEqual(self.server.column, 5)
        self.assertTrue((state / 'review-11.json').exists())
        self.assertFalse(any('/merge' in call[1] for call in self.server.calls))
        second = runner.run(provider, config, root, state, True)
        self.assertEqual(second['cards'], [])
        self.server.head = 'b' * 40
        self.assertNotEqual(json.loads((state / 'review-11.json').read_text())['head'], self.server.head)

    def test_finish_requires_manual_merge_and_proven_ancestry(self):
        root, config, original_git = self.setup_fake_runtime()
        provider = self.provider(True); state = self.state / 'runs/board'; state.mkdir(parents=True)
        runner.run(provider, config, root, state, True)
        with self.assertRaises(ProviderError):
            runner.finish(provider, root, state, 11)
        self.server.merged = True
        original_git('update-ref', 'refs/remotes/origin/main', self.server.head)
        # A local origin fixture avoids contacting any Git server. Only fetch is
        # skipped; merge-base --is-ancestor still executes against the real repo.
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        real_git = runner.git
        def offline_git(*args, **kwargs):
            return '' if args[0] == 'fetch' else real_git(*args, **kwargs)
        with patch.object(runner, 'git', side_effect=offline_git):
            result = runner.finish(provider, root, state, 11)
        self.assertEqual(result['status'], 'Done'); self.assertFalse(result['performedMerge'])
        self.assertEqual(self.server.issue['state'], 'closed')

    def test_stop_preserves_worktree_and_ends_child(self):
        root, config, _ = self.setup_fake_runtime()
        provider = self.provider(True); state = self.state / 'runs/board'; state.mkdir(parents=True)
        patch = __import__('unittest.mock', fromlist=['patch']).patch
        card = {'number': 11, 'lane': 'build', 'status': 'Building', 'labels': [], 'body': self.server.issue['body']}
        timer = threading.Timer(.3, lambda: runner.save(state / 'stop-request.json', {'stop': True}))
        timer.start()
        try:
            with patch.dict(os.environ, {'FIXTURE_SLEEP': '1'}):
                with self.assertRaises(ProviderError) as caught:
                    runner.lane(provider, config, root, card, state, True)
            self.assertEqual(caught.exception.kind, 'stopped')
            self.assertTrue((root / '.claude/worktrees/issue-11/README').exists())
        finally:
            timer.join()


if __name__ == '__main__':
    unittest.main()
