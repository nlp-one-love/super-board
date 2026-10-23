"""Compatibility backend: reuse the original GitHub helpers and payloads."""
import json
import os
from pathlib import Path
import subprocess

from .base import Provider, ProviderError


class GitHub(Provider):
    def __init__(self, config, path, **options):
        self.config_path = str(Path(path).resolve())

    def card(self, *args):
        helper = Path(__file__).resolve().parents[1] / 'super-board-card.sh'
        proc = subprocess.run(['bash', str(helper), '--config', self.config_path, *map(str, args)],
                              env=dict(os.environ, SB_PROVIDER_BYPASS='1'), text=True, capture_output=True)
        if proc.returncode:
            raise ProviderError('github', 'GitHub board helper failed', proc.returncode)
        return proc.stdout.strip()

    def items(self):
        return json.loads(self.card('items'))

    def move(self, number, status):
        return self.card('move', number, status)

    def ids(self):
        return json.loads(self.card('ids'))

    def status(self, number):
        return self.card('status', number)

    def item_id(self, number):
        return self.card('item-id', number)
