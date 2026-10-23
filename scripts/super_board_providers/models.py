"""Keep repository-local numbers separate from server-wide IDs."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IssueRef:
    repository: str
    number: int
    native_id: int


@dataclass(frozen=True)
class ColumnRef:
    project_id: int
    native_id: int
    name: str


def positive(value, label):
    from .base import ProviderError
    if type(value) is not int or value < 1:
        raise ProviderError('invalid-response', label + ' must be a positive integer')
    return value
