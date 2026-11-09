"""Public text hygiene and the proxy fallback contract."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'helianthus/rootfs/etc/services.d/helianthus-gateway/run'
CHANGELOG = ROOT / 'helianthus/CHANGELOG.md'
PATTERNS = (r'_work_[\w/-]+', r'(?i)\b(?:verification|audit)[-_][\w.-]+\.md\b', r'/(?:Users|home)/[^\s`]+')


def violations(text):
    text = re.sub(r'https?://[^\s<>"`()]+', '', text, flags=re.IGNORECASE)
    return [pattern for pattern in PATTERNS if re.search(pattern, text)]


def test_public_paths_have_no_private_references():
    for path in (RUN, CHANGELOG):
        assert not violations(path.read_text()), path


def test_hygiene_negative_controls():
    for text in ('_work_example/report.md', 'verification-example.md', '/Users/example/report.md'):
        assert violations(text)


def test_hygiene_allows_public_document_urls():
    for filename in ('verification-example.md', 'audit-example.md', 'EBUSD-VERIFICATION-2026.md'):
        url = f'https://github.com/example/project/blob/main/{filename}'
        for text in (url, f'[public document]({url})', f'<{url}>'):
            assert not violations(text)


def test_hygiene_rejects_local_references_alongside_public_urls():
    url = 'https://github.com/example/project/blob/main/audit-example.md'
    for reference in ('verification-example.md', 'audit-example.md', '_work_example/report.md', '/Users/example/report.md'):
        assert violations(f'[{reference}]({url})')
        assert violations(f'{url} and `{reference}`')
        assert violations(f'[public document]({url}){reference}')


def test_proxy_fallback_warning_and_value(tmp_path):
    source = RUN.read_text()
    start = source.index('if [ -z "${proxy_listen_addr}" ]')
    end = source.index('\nobserve_first_enabled=', start)
    options = tmp_path / 'options.json'
    options.write_text('{}')
    jq = tmp_path / 'jq'
    jq.write_text('#!/bin/sh\nprintf "synthetic-value\\n"\n')
    jq.chmod(0o755)
    script = '''set -eu
bashio::log.warning() { printf 'WARNING:%s\\n' "$1"; }
proxy_listen_addr=''
addon_options_path="$1"
''' + source[start:end] + '''
printf 'RESULT:%s\\n' "$proxy_listen_addr"
'''
    import os
    env = dict(os.environ, PATH=str(tmp_path) + ':' + os.environ['PATH'])
    result = subprocess.run(['bash', '-c', script, 'test', str(options)], text=True, capture_output=True, env=env, timeout=5, check=True)
    assert "bashio::config 'proxy_listen_addr' returned empty" in result.stdout
    assert 'falling back to /data/options.json (value=synthetic-value)' in result.stdout
    assert 'RESULT:synthetic-value' in result.stdout
