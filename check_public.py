"""Validate the publishable static package using only the Python standard library."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import base64
import hashlib
import re
import struct
import json

ROOT = Path(__file__).resolve().parent
ALLOWED = {'index.html','preview.jpg','README.md','source-manifest.json','analysis-ir.json','artifact-manifest.json','check_public.py','.nojekyll','.gitignore'}

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.images = []
        self.checks = 0
        self.prompts = 0
        self.csp = ''
        self.in_script = False
        self.script = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        assert not any(k.lower().startswith('on') for k in a), 'Inline event handler'
        assert not any(str(v).lower().startswith('javascript:') for v in a.values()), 'Unsafe URL'
        if 'id' in a:
            self.ids.append(a['id'])
        if 'data-check' in a:
            self.checks += 1
        if 'prompt' in (a.get('class') or '').split():
            self.prompts += 1
        if tag == 'a':
            self.links.append(a.get('href',''))
        if tag == 'img':
            assert a.get('alt'), 'Image without description'
            assert a.get('src','').startswith('data:image/jpeg;base64,'), 'Remote image dependency'
            self.images.append(a['src'])
        if tag == 'svg':
            assert a.get('aria-label'), 'Diagram without accessible label'
        if tag in {'iframe','object','embed'}:
            raise AssertionError('Remote or executable embedded content')
        if tag == 'script':
            assert 'src' not in a, 'Remote script dependency'
            self.in_script = True
        if tag == 'link':
            assert a.get('rel') != 'stylesheet', 'External stylesheet dependency'
        if tag == 'meta' and (a.get('http-equiv') or '').lower() == 'content-security-policy':
            self.csp = a.get('content','')

    def handle_data(self, data):
        if self.in_script:
            self.script += data

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

def check_jpeg(data):
    assert data[:2] == b'\xff\xd8'
    # Refuse EXIF, XMP, IPTC and JPEG comments; allow ordinary JFIF headers.
    i = 2
    while i < len(data):
        assert data[i] == 255, 'Unexpected JPEG segment'
        while data[i] == 255:
            i += 1
        marker = data[i]
        i += 1
        if marker in (0xDA,0xD9):
            break
        if marker in (0x01,*range(0xD0,0xD8)):
            continue
        size = struct.unpack('>H',data[i:i+2])[0]
        assert marker not in (0xE1,0xED,0xFE), 'Identifying JPEG metadata'
        i += size

def main():
    files = {x.name for x in ROOT.iterdir() if x.is_file()}
    assert files == ALLOWED, f'Unexpected or missing publication files: {files ^ ALLOWED}'
    for name in files - {'preview.jpg'}:
        assert b'\r\n' not in (ROOT/name).read_bytes(), f'Use LF line endings: {name}'
    html = (ROOT/'index.html').read_text(encoding='utf-8')
    page = Page()
    page.feed(html)
    assert len(page.ids) == len(set(page.ids)), 'Duplicate IDs'
    assert page.checks == 6 and page.prompts == 17
    assert len(page.images) == 1, 'Public edition must retain only its reviewed clean excerpt'
    for link in page.links:
        if link.startswith('#'):
            assert link[1:] in page.ids, f'Broken anchor: {link}'
        elif not urlsplit(link).scheme:
            target = (ROOT/unquote(urlsplit(link).path)).resolve()
            assert target.is_relative_to(ROOT) and target.is_file(), f'Unsafe or missing local target: {link}'
    digest = base64.b64encode(hashlib.sha256(page.script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in page.csp, 'CSP script hash mismatch'
    assert "default-src 'none'" in page.csp and "connect-src 'none'" in page.csp
    for image in page.images:
        check_jpeg(base64.b64decode(image.split(',',1)[1]))
    check_jpeg((ROOT/'preview.jpg').read_bytes())
    # Exclude this scanner itself because its rules intentionally contain path/key syntax.
    combined = '\n'.join((ROOT/name).read_text(encoding='utf-8') for name in ALLOWED if name.endswith(('.html','.json','.md')))
    patterns = [r'(?i)[a-z]:[\\/](?:users|documents)[\\/]',r'(?i)/(?:users|home)/[^\s<]+',r'(?i)file:///',r'(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b',r'-----BEGIN [A-Z ]*PRIVATE KEY-----',r'(?i)\b(?:MIT PhD|IIT JEE|graduated in 1989)\b']
    # Base64 images are inspected separately; do not mistake arbitrary encoded bytes for text.
    combined = re.sub(r'data:image/jpeg;base64,[A-Za-z0-9+/=]+','[embedded reviewed image]',combined)
    for pattern in patterns:
        assert not re.search(pattern,combined), f'Privacy scan failed for pattern: {pattern}'
    assert 'native computer-control APIs are disabled' not in html
    assert 'unavailable in this chat' not in html
    readme = (ROOT/'README.md').read_text(encoding='utf-8')
    assert 'https://www.youtube.com/watch?v=FwiS44-xyYw&t=25s' in readme
    assert '[![Preview' in readme and 'https://az9713.github.io/cooking-with-codex/' in readme
    ir = json.loads((ROOT/'analysis-ir.json').read_text(encoding='utf-8'))
    assert len(ir['visual_samples']) == 24 and len(ir['adapted_prompts']) == 17
    for artifact in json.loads((ROOT/'artifact-manifest.json').read_text(encoding='utf-8'))['artifacts']:
        assert (ROOT/artifact['path']).is_file()
    print('PASS: publication allowlist, privacy patterns, JPEG metadata, references, anchors, offline dependencies, CSP and expected guide content.')

if __name__ == '__main__':
    main()
