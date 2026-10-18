import json
import urllib.request
import urllib.error
from pathlib import Path
import sys

# Mock urlopen to raise 403
original_urlopen = urllib.request.urlopen

def mock_urlopen(req, *args, **kwargs):
    if req.full_url == 'http://example.com/fail':
        raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
    return original_urlopen(req, *args, **kwargs)

urllib.request.urlopen = mock_urlopen

config = {
    "sources": [
        {"id": "test-success", "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"},
        {"id": "test-fail", "url": "http://example.com/fail"}
    ]
}

Path('test_config.json').write_text(json.dumps(config))

import subprocess
res = subprocess.run([sys.executable, 'scripts/literature_sources.py', 'fetch', '--config', 'test_config.json', '--output', 'test_out'])
print(res.returncode)

