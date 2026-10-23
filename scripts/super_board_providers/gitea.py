"""Gitea 28.2 REST implementation, derived from swagger.v1.json.

No network call happens in the constructor. Mutations require an explicit grant;
automatic merge and migrations have no execution path in this provider.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse

from .base import Provider, ProviderError, local_path
from .http import HTTP
from .models import IssueRef, positive
from .credentials import token_for


def value(mapping, key, default=None):
    env = mapping.get(key + '_env')
    if env is not None:
        if not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env):
            raise ProviderError('config', 'Invalid environment variable name', 66)
        return os.environ.get(env, default)
    return mapping.get(key, default)


class Gitea(Provider):
    def __init__(self, config, allow_write=False, state_dir=None, **options):
        self.config, self.allow_write = config, allow_write
        g = config.get('gitea', {})
        if not isinstance(g, dict):
            raise ProviderError('config', 'gitea configuration must be an object', 66)
        self.url = value(g, 'url', '').rstrip('/')
        u = urllib.parse.urlsplit(self.url)
        local = u.hostname in ('127.0.0.1', 'localhost', '::1')
        if (u.scheme != 'https' and not (u.scheme == 'http' and local and g.get('allow_insecure_localhost') is True)
                or not u.hostname or u.username or u.password or u.query or u.fragment
                or '..' in u.path.split('/')):
            raise ProviderError('config', 'Gitea URL must be HTTPS without credentials, query or fragment', 66)
        self.owner, self.repo = value(g, 'owner', ''), value(g, 'repo', '')
        for name in (self.owner, self.repo):
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name) or name in ('.', '..'):
                raise ProviderError('config', 'Set valid Gitea owner and repo', 66)
        self.repository = self.owner + '/' + self.repo
        self.r = '/repos/' + self.repository
        project = config.get('project', {})
        self.scope = project.get('scope', 'repository')
        if self.scope not in ('repository', 'organization', 'individual'):
            raise ProviderError('config', 'Unsupported project scope', 66)
        pid = value(project, 'id')
        if isinstance(pid, str) and pid.isdigit():
            pid = int(pid)
        self.project_id = positive(pid, 'project.id')
        board_owner = project.get('owner', self.owner)
        if not isinstance(board_owner, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', board_owner):
            raise ProviderError('config', 'Invalid project owner', 66)
        self.projects = self.r + '/projects' if self.scope == 'repository' else (
            '/orgs/' + board_owner + '/projects' if self.scope == 'organization' else '/user/projects')
        self.p = self.projects + '/' + str(pid)
        self.token, self.token_source = token_for(g)
        timeout = g.get('timeout_seconds', 15)
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise ProviderError('config', 'timeout_seconds must be between 0 and 60', 66)
        self.http = HTTP(self.url + '/api/v1', self.token, timeout=timeout)
        self.identity = hashlib.sha256((self.url + '/' + self.repository + self.p).encode()).hexdigest()[:24]
        self.state = Path(state_dir) / self.identity if state_dir else None

    def checkpoint(self):
        if self.state and (self.state / 'uncertain-write.json').exists():
            raise ProviderError('uncertain-write', 'An earlier write needs reconciliation; inspect saved intent before resuming')

    def write(self, method, path, body=None):
        if 'merge' in path.split('?')[0].split('/'):
            raise ProviderError('forbidden', 'Merge and scheduled auto-merge are disabled', 7)
        if not (path.startswith(self.r + '/') or path.startswith(self.p + '/')):
            raise ProviderError('forbidden', 'Write targets another repository/project', 7)
        self.checkpoint()
        if not self.allow_write:
            raise ProviderError('forbidden', 'Write requires explicit --allow-write for the selected sandbox/project', 7)
        if not self.state:
            raise ProviderError('config', 'Writes require a persistent state directory', 66)
        local_path(self.state)
        # Journal BEFORE sending: even SIGKILL or malformed successful replies
        # must leave evidence that a mutation may have happened. Do not store bodies.
        self.state.mkdir(parents=True, exist_ok=True)
        ignore = local_path(self.state.parent / '.gitignore')
        if not ignore.exists():
            ignore.write_text('*\n')
        marker = local_path(self.state / 'uncertain-write.json')
        with marker.open('x') as stream:
            json.dump({'method': method, 'path': path, 'body_sha256': hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()).hexdigest()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            result, _ = self.http.request(method, path, body)
        except ProviderError as error:
            if error.kind not in ('uncertain-write', 'invalid-response', 'unavailable'):
                marker.unlink()
            raise
        marker.unlink()
        return result

    def reconcile(self, confirmed):
        if not confirmed:
            raise ProviderError('forbidden', 'Inspect remote outcome first; then pass --reconciled explicitly', 7)
        if self.state and (self.state / 'uncertain-write.json').exists():
            source = self.state / 'uncertain-write.json'
            target = self.state / ('reconciled-' + str(__import__('time').time_ns()) + '.json')
            source.rename(target)
        return {'reconciled': True, 'replayed': False}

    @staticmethod
    def obj(data, required):
        if not isinstance(data, dict) or any(key not in data for key in required):
            raise ProviderError('invalid-response', 'API object is missing required evidence')
        return data

    def read(self, path, required=()):
        data, _ = self.http.request('GET', path)
        return self.obj(data, required)

    def doctor(self):
        # The instance can reject /version anonymously but expose its contract.
        schema, _ = HTTP(self.url, self.token).request('GET', '/swagger.v1.json')
        self.obj(schema, ['info', 'paths'])
        version = schema.get('info', {}).get('version', '')
        if not isinstance(version, str) or not re.fullmatch(r'28\.\d+\.\d+(?:[-+].*)?', version):
            raise ProviderError('capability', 'Gitea 28.x is required')
        prefix = {'repository': '/repos/{owner}/{repo}', 'organization': '/orgs/{org}', 'individual': '/user'}[self.scope]
        required = {prefix + '/projects/{id}/columns': 'get',
                    prefix + '/projects/{id}/issues/{issue_id}/move': 'post',
                    prefix + '/projects/{id}/columns/{column_id}/issues': 'get'}
        required['/repos/{owner}/{repo}/issues/{index}/dependencies'] = 'get'
        if any(method not in schema['paths'].get(path, {}) for path, method in required.items()):
            raise ProviderError('capability', 'Instance contract lacks required Projects/dependencies methods')
        repo = self.read(self.r, ['id', 'full_name'])
        if repo['full_name'].lower() != self.repository.lower() or repo.get('archived'):
            raise ProviderError('capability', 'Repository identity mismatch or archived repository')
        project = self.read(self.p, ['id', 'state'])
        if project['id'] != self.project_id or project['state'] != 'open':
            raise ProviderError('capability', 'Project identity mismatch or closed project')
        columns = self.columns()
        needed = self.config.get('columns', ['Backlog', 'Ready', 'Building', 'QA', 'Review', 'Blocked', 'Done'])
        missing = sorted(set(needed) - {c['title'] for c in columns})
        return {'provider': 'gitea', 'version': version, 'repository': self.repository,
                'projectId': self.project_id, 'scope': self.scope, 'missingColumns': missing,
                'ready': not missing, 'merge': 'manual-only', 'authenticated': bool(self.token),
                'credentialSource': self.token_source}

    def columns(self):
        data = self.http.pages(self.p + '/columns')
        names, ids = set(), set()
        for c in data:
            self.obj(c, ['id', 'project_id', 'title'])
            positive(c['id'], 'column.id')
            if (c['project_id'] != self.project_id or not isinstance(c['title'], str) or not c['title']
                    or c['title'] in names or c['id'] in ids):
                raise ProviderError('invalid-response', 'Ambiguous column names/IDs or wrong project')
            names.add(c['title']); ids.add(c['id'])
        return data

    def ids(self):
        return {'projectId': self.project_id, 'fieldId': None,
                'options': {c['title']: c['id'] for c in self.columns()}}

    def issue(self, number):
        positive(number, 'issue number')
        row = self.read(self.r + '/issues/' + str(number), ['id', 'number', 'title', 'body', 'state'])
        positive(row['id'], 'issue.id')
        if row['number'] != number or row['state'] not in ('open', 'closed') or not isinstance(row['body'], str):
            raise ProviderError('invalid-response', 'Issue identity/state/body is invalid')
        return row

    def issue_ref(self, row):
        return IssueRef(self.repository, positive(row['number'], 'issue number'), positive(row['id'], 'issue.id'))

    def items(self):
        items, seen = [], set()
        for column in self.columns():
            for row in self.http.pages(self.p + '/columns/%s/issues' % column['id']):
                self.obj(row, ['id', 'number', 'title', 'state'])
                repo = row.get('repository', {})
                full = repo.get('full_name')
                if self.scope != 'repository' and not full:
                    raise ProviderError('invalid-response', 'Owner board task lacks repository identity')
                if full and full.lower() != self.repository.lower():
                    continue  # Never dispatch another repository's card.
                ref = self.issue_ref(row)
                if ref.native_id in seen:
                    raise ProviderError('invalid-response', 'Task appeared in multiple columns/pages')
                if row['state'] not in ('open', 'closed') or not isinstance(row['title'], str):
                    raise ProviderError('invalid-response', 'Task has invalid title/state')
                seen.add(ref.native_id)
                items.append({'id': ref.native_id, 'title': row['title'], 'status': column['title'],
                              'state': row['state'].upper(), 'assignees': row.get('assignees') or [],
                              'labels': [x['name'] for x in row.get('labels', [])],
                              'content': {'type': 'PullRequest' if row.get('pull_request') else 'Issue',
                                          'number': ref.number, 'title': row['title'],
                                          'url': row.get('html_url'), 'repository': self.repository}})
        return {'items': items, 'totalCount': len(items)}

    def card(self, number):
        rows = [x for x in self.items()['items'] if x['content']['number'] == number and x['content']['type'] == 'Issue']
        if len(rows) != 1:
            raise ProviderError('missing', 'Issue is not uniquely present on this board', 3)
        return rows[0]

    def status(self, number):
        return self.card(number)['status']

    def item_id(self, number):
        return self.card(number)['id']

    def move(self, number, status):
        columns = {c['title']: c['id'] for c in self.columns()}
        if status not in columns:
            raise ProviderError('missing', 'Target column is absent', 3)
        card = self.card(number)
        if card['status'] == status:
            return {'number': number, 'status': status, 'changed': False}
        # Done is an external-merge reconciliation operation, not an agent move.
        if status == 'Done':
            raise ProviderError('forbidden', 'Use finish after a manually merged PR', 7)
        self.write('POST', self.p + '/issues/%s/move' % card['id'], {'column_id': columns[status]})
        if self.status(number) != status:
            raise ProviderError('conflict', 'Board changed during move; reconcile before continuing')
        return {'number': number, 'status': status, 'changed': True}

    def attach(self, number, status):
        if status == 'Done':
            raise ProviderError('forbidden', 'Done requires an externally merged reviewed PR', 7)
        col = self.ids()['options'].get(status)
        if col is None:
            raise ProviderError('missing', 'Target column is absent', 3)
        row = self.issue(number)
        self.write('POST', self.p + '/columns/%s/issues/%s' % (col, row['id']))
        return {'number': number, 'status': self.status(number)}

    def comments(self, number):
        return self.http.pages(self.r + '/issues/%d/comments' % positive(number, 'issue number'))

    def dependencies(self, number):
        return self.http.pages(self.r + '/issues/%d/dependencies' % positive(number, 'issue number'))

    def pulls(self, state='open'):
        if state not in ('open', 'closed', 'all'):
            raise ProviderError('config', 'Invalid pull request state', 64)
        return self.http.pages(self.r + '/pulls', {'state': state})

    def pull(self, number):
        row = self.read(self.r + '/pulls/%d' % positive(number, 'PR number'), ['number', 'head', 'base', 'state', 'merged'])
        if row['number'] != number or not re.fullmatch(r'[0-9a-f]{40,64}', row['head'].get('sha', '')):
            raise ProviderError('invalid-response', 'PR identity or head SHA is invalid')
        return row

    def checks(self, sha):
        if not re.fullmatch(r'[0-9a-f]{40,64}', sha):
            raise ProviderError('config', 'A full commit SHA is required', 64)
        statuses = self.http.pages(self.r + '/statuses/' + sha)
        required = self.config.get('required_status_contexts', [])
        if not isinstance(required, list) or any(not isinstance(x, str) or not x.strip() for x in required):
            raise ProviderError('config', 'required_status_contexts must be a list of nonempty context names', 66)
        latest = {}
        for s in sorted(statuses, key=lambda s: s.get('id', 0), reverse=True):
            self.obj(s, ['context', 'status', 'sha'])
            if s['sha'] != sha:
                raise ProviderError('invalid-response', 'CI status belongs to another SHA')
            latest.setdefault(s['context'], s['status'])
        return {'sha': sha, 'contexts': latest, 'green': bool(required) and
                all(latest.get(context) == 'success' for context in required)}

    def reviews(self, number):
        return self.http.pages(self.r + '/pulls/%d/reviews' % positive(number, 'PR number'))
