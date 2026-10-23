"""Resolve token credentials without putting values in arguments or diagnostics."""
import os
import re
import stat

from .base import ProviderError


def env_name(config, key, default):
    name = config.get(key, default)
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ProviderError('config', 'Invalid ' + key, 66)
    return name


def token_for(config):
    name = env_name(config, 'token_env', 'GITEA_TOKEN')
    file_name = env_name(config, 'token_file_env', 'GITEA_TOKEN_FILE')
    token = os.environ.get(name, '')
    source = 'environment' if token else 'none'
    if not token and os.environ.get(file_name):
        try:
            # Reject symlinks atomically on platforms that support O_NOFOLLOW.
            fd = os.open(os.environ[file_name], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
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
                if not token:
                    raise ValueError()
            source = 'file'
        except (OSError, ValueError, UnicodeError):
            raise ProviderError('config', 'Token file must be a readable owner-only regular file containing only the token', 66)
    if token and (not token.isascii() or any(c.isspace() for c in token)):
        raise ProviderError('config', 'Invalid token credential format', 66)
    return token, source
