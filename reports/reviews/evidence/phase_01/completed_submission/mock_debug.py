import io
import json
from pathlib import Path
import runpy
import sys
import traceback
import urllib.error
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

root = Path(__file__).resolve().parents[5]
out = Path(__file__).resolve().parent
stdout, stderr = io.StringIO(), io.StringIO()
def deny(request, **kwargs):
    raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {}, io.BytesIO(b'reviewer error body'))
with patch.object(sys, 'argv', ['scripts/literature_sources.py', 'fetch', '--config',
        str(out / 'mock_sources.json'), '--output', str(out / 'mock_pdf_failure_debug')]), \
        patch('urllib.request.urlopen', deny), redirect_stdout(stdout), redirect_stderr(stderr):
    try:
        runpy.run_path(str(root / 'scripts/literature_sources.py'), run_name='__main__')
        code, error = 0, None
    except SystemExit as exc:
        code, error = exc.code, None
    except Exception:
        code, error = 1, traceback.format_exc()
record = {'exit_code': code, 'error': error, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}
with (out / 'mock_debug.json').open('x', encoding='utf-8') as handle:
    json.dump(record, handle, indent=2)
print(json.dumps(record))
