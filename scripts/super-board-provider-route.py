#!/usr/bin/env python3
"""Read only the provider selection before legacy helpers can call jq/gh."""
import json
import os
from pathlib import Path
import sys


def provider(argv):
    path = os.environ.get('SB_CONFIG')
    for i, arg in enumerate(argv):
        if arg == '--config' and i + 1 < len(argv):
            path = argv[i + 1]
        elif arg.startswith('--config='):
            path = arg.split('=', 1)[1]
    if not path:
        return 'github'
    # Legacy helpers support FIFOs; don't consume a stream just to probe it.
    if not Path(path).is_file():
        return 'github'
    value = json.loads(Path(path).read_text()).get('provider', 'github')
    if value not in ('github', 'gitea'):
        raise ValueError()
    return value


if __name__ == '__main__':
    try:
        print(provider(sys.argv[1:]))
    except (OSError, ValueError, TypeError, AttributeError):
        print('Invalid provider configuration', file=sys.stderr)
        sys.exit(66)
