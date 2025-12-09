import pytest
from prodos.file import legal_path

@pytest.mark.parametrize('path,expected', [
    ('abc', 'ABC'),
    ('DEF', 'DEF'),
    ('0123_.f/7ab-,z', 'A01230.F/A7AB00Z')
])
def test_legal_path(path: str, expected: str):
    assert legal_path(path) == expected
