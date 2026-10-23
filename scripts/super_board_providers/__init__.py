"""Explicit board/SCM backends. Importing this package performs no I/O."""
import json
from pathlib import Path

from .base import ProviderError


def load(path, **options):
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ProviderError('config', 'Cannot read project JSON configuration', 66)
    if not isinstance(config, dict):
        raise ProviderError('config', 'Project configuration must be an object', 66)
    name = config.get('provider', 'github')
    if name == 'gitea':
        from .gitea import Gitea
        return Gitea(config, **options)
    if name == 'github':
        from .github import GitHub
        return GitHub(config, path, **options)
    raise ProviderError('config', 'Unknown provider; choose github or gitea', 66)
