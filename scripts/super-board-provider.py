#!/usr/bin/env python3
"""SCM/board commands. Reads by default; merge is always denied."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from super_board_providers import load
from super_board_providers.base import ProviderError
SAFE_TOKEN = ''


def main(argv=None):
    global SAFE_TOKEN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--allow-write', action='store_true')
    parser.add_argument('--reconciled', action='store_true')
    parser.add_argument('command', choices=['doctor', 'items', 'ids', 'status', 'item-id', 'move', 'attach',
        'issue', 'comments', 'dependencies', 'pulls', 'pull', 'files', 'diff', 'checks', 'reviews',
        'create-issue', 'update-issue', 'comment', 'edit-comment', 'create-pr', 'update-pr', 'merge', 'resume', 'auth'])
    parser.add_argument('args', nargs='*')
    parser.add_argument('--body-file', help='JSON payload for create/update; literal UTF-8 for comments')
    parser.add_argument('--token-file', help='auth only: register the path of an existing private file outside the repo')
    args = parser.parse_args(argv)
    git = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                         text=True, capture_output=True)
    state = Path(git.stdout.strip()).parent / '.claude/super-board/provider-state' if git.returncode == 0 else None
    provider = load(args.config, allow_write=args.allow_write, state_dir=state,
                    credentials_required=args.command != 'auth')
    SAFE_TOKEN = getattr(provider, 'token', '')
    command, values = args.command, args.args
    arity = {'move': 2, 'attach': 2, 'items': 0, 'ids': 0, 'doctor': 0, 'merge': 0,
             'pulls': 0, 'create-issue': 0, 'create-pr': 0, 'resume': 0, 'auth': 0}
    if len(values) != arity.get(command, 1):
        parser.error('wrong number of arguments for ' + command)
    if command == 'auth':
        if not args.token_file or not hasattr(provider, 'credential_scope'):
            parser.error('auth requires a Gitea config and --token-file pointing outside the repo')
        from super_board_providers.credentials import bind_token_file
        bind_token_file(provider.credential_scope, args.token_file)
        return {'configured': True, 'repository': provider.repository, 'credentialSource': 'git-config-file',
                'stored': 'file reference only; token is not copied'}
    if command == 'merge':
        return provider.merge()
    if command == 'resume':
        return provider.reconcile(args.reconciled)
    if command in ('items', 'ids', 'doctor', 'pulls'):
        return getattr(provider, command)()
    if command in ('move', 'attach'):
        return getattr(provider, command)(int(values[0]), values[1])
    if command in ('issue', 'comments', 'dependencies', 'pull', 'reviews', 'status', 'item-id'):
        return getattr(provider, command.replace('-', '_'))(int(values[0]))
    if command == 'checks':
        return provider.checks(values[0])
    if command in ('files', 'diff'):
        number = int(values[0]); provider.pull(number)
        if command == 'files':
            return provider.http.pages(provider.r + '/pulls/%d/files' % number)
        return provider.http.request('GET', provider.r + '/pulls/%d.diff' % number, raw=True)[0]
    if not args.body_file:
        parser.error('--body-file is required for writes')
    text = Path(args.body_file).read_text()
    body = {'body': text} if command in ('comment', 'edit-comment') else json.loads(text)
    if not isinstance(body, dict):
        parser.error('payload must be a JSON object')
    paths = {'create-issue': ('POST', '/issues'), 'create-pr': ('POST', '/pulls'),
             'update-issue': ('PATCH', '/issues/%s'), 'update-pr': ('PATCH', '/pulls/%s'),
             'comment': ('POST', '/issues/%s/comments'), 'edit-comment': ('PATCH', '/issues/comments/%s')}
    method, path = paths[command]
    if values:
        from super_board_providers.models import positive
        path %= positive(int(values[0]), 'resource number')
    allowed = {'create-issue': {'title', 'body', 'labels'}, 'update-issue': {'title', 'body', 'labels'},
               'create-pr': {'title', 'body', 'head', 'base'}, 'update-pr': {'title', 'body'},
               'comment': {'body'}, 'edit-comment': {'body'}}[command]
    if set(body) - allowed:
        parser.error('unsupported payload fields (state/merge/dependency edits need separate reviewed operations)')
    return provider.write(method, provider.r + path, body)


if __name__ == '__main__':
    try:
        result = main()
        output = str(result) if isinstance(result, (str, int)) else json.dumps(result)
        print(output.replace(SAFE_TOKEN, '[REDACTED]') if SAFE_TOKEN else output)
        if isinstance(result, dict) and result.get('ready') is False:
            sys.exit(1)
    except ProviderError as error:
        print(json.dumps({'error': error.kind, 'detail': str(error)}), file=sys.stderr)
        sys.exit(error.code)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print('Invalid configuration, arguments or API response; no credentials are shown', file=sys.stderr)
        sys.exit(64)
