"""Provider boundary and stable error vocabulary for shell callers."""
from abc import ABC, abstractmethod
from pathlib import Path


class ProviderError(Exception):
    def __init__(self, kind, message, code=79):
        super().__init__(message)
        self.kind, self.code = kind, code


def local_path(path):
    """Reject symlinked runtime-state parents and leaf files before any write."""
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ProviderError('config', 'Runtime state cannot follow a symlink', 66)
    return path


class Provider(ABC):
    @abstractmethod
    def items(self):
        """Return the established {items, totalCount} board snapshot."""

    @abstractmethod
    def move(self, number, status):
        """Move one repository-local issue to a named column."""

    def merge(self, *args, **kwargs):
        raise ProviderError('forbidden', 'Automatic merge is disabled; merge manually after review', 7)
