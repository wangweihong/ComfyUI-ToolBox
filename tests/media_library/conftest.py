import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pytest
from support import Library

@pytest.fixture
def lib(tmp_path):
    root = tmp_path / 'media'
    root.mkdir()
    store = Library(tmp_path / 'data' / 'prompts.sqlite3', tmp_path / 'cache', {'input': str(root)})
    yield store
    store.close()
