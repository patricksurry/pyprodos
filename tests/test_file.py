import pytest
from prodos.file import legal_path

@pytest.mark.parametrize('path,expected', [
    ('abc', 'ABC'),
    ('DEF', 'DEF'),
    ('0123_/7ab-,z', 'A0123./A7AB..Z')
])
def test_legal_path(path: str, expected: str):
    assert legal_path(path) == expected
