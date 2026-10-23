"""Resolve token credentials without putting values in arguments or diagnostics."""
import os
import re
import stat
import hashlib
from pathlib import Path
import subprocess

from .base import ProviderError


def env_name(config, key, default):
    name = config.get(key, default)
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ProviderError('config', 'Invalid ' + key, 66)
    return name


def read_token_file(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                     | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                    or (hasattr(os, 'geteuid') and info.st_uid != os.geteuid())):
                raise ValueError()
            token = stream.read(4097)
            if len(token) > 4096:
                raise ValueError()
            token = token.strip()
            if not token or not token.isascii() or any(c.isspace() for c in token):
                raise ValueError()
        return token
    except (OSError, ValueError, UnicodeError):
        raise ProviderError('config', 'Token file must be a readable owner-only regular file containing only the token', 66)


def git_key(scope):
    # Bind references to the exact server AND repo, never another configured host.
    identity = hashlib.sha256(scope.encode()).hexdigest()
    return 'superboard.gitea.' + identity + '.tokenFile'


def bind_token_file(scope, path, cwd=None):
    path = Path(path).absolute()
    read_token_file(path)  # Validate first; never write the token to Git config.
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd, text=True, capture_output=True)
    if top.returncode:
        raise ProviderError('config', 'Configure credentials from the selected project repository', 66)
    root = Path(top.stdout.strip()).resolve()
    if path.resolve().is_relative_to(root):
        raise ProviderError('config', 'Keep the token file outside the project repository', 66)
    result = subprocess.run(['git', 'config', '--local', git_key(scope), str(path)],
                            cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise ProviderError('config', 'Could not save the local credential-file reference', 66)


def token_for(config, scope=None, required=True):
    name = env_name(config, 'token_env', 'GITEA_TOKEN')
    file_name = env_name(config, 'token_file_env', 'GITEA_TOKEN_FILE')
    token = os.environ.get(name, '')
    source = 'environment' if token else 'none'
    path = os.environ.get(file_name)
    if not token and path:
        token, source = read_token_file(path), 'file'
    if not token and scope:
        local = subprocess.run(['git', 'config', '--local', '--get', git_key(scope)],
                               capture_output=True, text=True)
        if local.returncode == 0 and local.stdout.strip():
            token, source = read_token_file(local.stdout.strip()), 'git-config-file'
    if token and (not token.isascii() or any(c.isspace() for c in token)):
        raise ProviderError('config', 'Invalid token credential format', 66)
    if not token and required:
        raise ProviderError('auth', 'No Gitea credentials configured: set ' + name + ' or ' + file_name
                            + ', or configure a project-local token-file reference with provider auth', 66)
    return token, source
