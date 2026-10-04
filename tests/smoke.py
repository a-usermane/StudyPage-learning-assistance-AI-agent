"""API integration suite; creates courses only in the isolated runner data directory."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('STUDY_TEST_URL', 'http://127.0.0.1:8001')
checks = []

def request(path, data=None, method='GET', expected=200, content_type='application/json'):
    if isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')
    headers = {'Content-Type': content_type} if data is not None else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    assert status == expected, (path, status, raw[:400])
    return json.loads(raw)

def upload(course_id, name, contents, expected=201, category='other'):
    boundary = 'StudyTest' + uuid.uuid4().hex
    data = (f'--{boundary}\r\nContent-Disposition: form-data; name="category"\r\n\r\n{category}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + contents + f'\r\n--{boundary}--\r\n'.encode()
    return request(f'/api/courses/{course_id}/documents', data, 'POST', expected, 'multipart/form-data; boundary=' + boundary)

def check(name):
    checks.append(name)
    print('PASS:', name)

def main():
    health = request('/api/health')
    data_dir = Path(health['data_dir']).resolve()
    assert data_dir.is_relative_to(ROOT / '.cache'), 'Run tests/offline_check.py to isolate test records from your library.'
    assert health['mode'] == 'demo' and health['schema_version'] == 2
    course = request('/api/courses', {'name': 'API 验证课程'}, 'POST', 201)
    cid = course['id']
    cp = '/api/courses/' + cid
    assert course['status'] == 'pending' and not any(c['id'] == cid for c in request('/api/courses'))
    upload(cid, 'broken.pdf', b'broken pdf', 400)
    assert request(cp)['status'] == 'pending'
    doc = upload(cid, 'test-text.txt', 'Gradient descent\n<script>alert(1)</script>\n中文测试'.encode(), category='exercises')
    assert request(cp)['status'] == 'ready' and doc['category'] == 'exercises'
    path = data_dir / 'courses' / cid / 'materials/exercises' / doc['id'] / 'original.txt'
    assert path.exists() and request(f"/api/documents/{doc['id']}/pages/1")['text'].endswith('中文测试')
    check('pending course activation and classified local storage')
    source = {'course_id': cid, 'document_id': doc['id'], 'page_start': 1, 'page_end': 1}
    known = request('/api/demo', {**source, 'action': 'translate', 'selected_text': 'gradient descent'}, 'POST')
    assert '梯度下降' in known['content'] and '演示模式' in known['content']
    unknown = request('/api/demo', {**source, 'action': 'translate', 'selected_text': 'unlisted_variable'}, 'POST')
    assert '没有这段内容' in unknown['content']
    message_source = {k: v for k,v in source.items() if k != 'course_id'}
    ask = request(cp + '/messages', {**message_source, 'question': '术语是什么？'}, 'POST', 201)
    assert ask['citation']['page_start'] == 1 and '未生成解答' in ask['content']
    note = request(cp + '/notes', {**message_source, 'body': '自己的理解'}, 'POST', 201)
    assert len(request(cp + '/messages')) == 2 and len(request(cp + '/notes')) == 1
    database = data_dir / 'db/library.db'
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT COUNT(*) FROM messages WHERE course_id=?', (cid,)).fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM notes WHERE id=?', (note['id'],)).fetchone()[0] == 1
    check('known/unknown demo answers and course conversation/note persistence')
    pdf = upload(cid, 'test.pdf', (ROOT / 'samples/optimization.pdf').read_bytes(), category='slides')
    assert pdf['pages'] == 2
    assert 'Overfitting' in request(f"/api/documents/{pdf['id']}/pages/2")['text']
    cross = request(cp + '/messages', {'document_id': pdf['id'], 'page_start': 1, 'page_end': 2,
        'selected_text': 'Gradient descent / Overfitting', 'question': '跨页问题'}, 'POST', 201)
    assert cross['citation']['page_end'] == 2 and len(request(cp + '/messages')) == 4
    summary = request('/api/demo', {'course_id': cid, 'action': 'summary', 'document_id': pdf['id'], 'page_start': 2}, 'POST')
    assert '不是 AI 总结' in summary['content'] and 'Overfitting' in summary['content']
    scan = upload(cid, 'scan.pdf', (ROOT / 'samples/scan-no-ocr.pdf').read_bytes())
    assert '不支持 OCR' in scan['warning'] and not request(f"/api/documents/{scan['id']}/pages/1")['text'].strip()
    slide = upload(cid, 'slides.pptx', (ROOT / 'samples/lecture.pptx').read_bytes(), category='slides')
    assert slide['pages'] == 2
    assert '讲者备注' in request(f"/api/documents/{slide['id']}/pages/1")['text']
    assert 'Fit parameters  |  Check generalization' in request(f"/api/documents/{slide['id']}/pages/2")['text']
    code = upload(cid, 'program.py', (ROOT / 'samples/example.py').read_bytes(), category='code')
    assert 'updated_weight' in request(f"/api/documents/{code['id']}/pages/1")['text']
    gb = upload(cid, 'gb.txt', '中文编码'.encode('gb18030'))
    assert request(f"/api/documents/{gb['id']}/pages/1")['text'] == '中文编码'
    utf = upload(cid, 'utf.txt', 'UTF16 中文'.encode('utf-16'))
    assert '中文' in request(f"/api/documents/{utf['id']}/pages/1")['text']
    check('PDF/PPTX/text/code formats, cross-page sources and course-wide history')
    other = request('/api/courses', {'name': '另一门课程'}, 'POST', 201)
    request('/api/demo', {**source, 'course_id': other['id'], 'action': 'ask', 'question': 'wrong course'}, 'POST', 400)
    request('/api/courses/' + other['id'] + '/notes', {**message_source, 'body': 'wrong course'}, 'POST', 400)
    request(cp + '/notes?document_id=' + code['id'])
    request(cp + '/pending', method='DELETE', expected=409)
    request('/api/courses/' + other['id'] + '/pending', method='DELETE')
    request('/api/courses/' + other['id'], expected=404)
    upload(cid, 'wrong.exe', b'file', 400)
    upload(cid, 'empty.txt', b'', 400)
    upload(cid, 'binary.txt', b'abc\x00def', 400)
    upload(cid, 'badcategory.txt', b'text', 400, category='../code')
    upload(cid, 'huge.txt', b'x' * (health['upload_limit'] + 1), 413)
    from pypdf import PdfWriter
    encrypted = PdfWriter(); encrypted.add_blank_page(300,400); encrypted.encrypt('secret')
    buffer = io.BytesIO(); encrypted.write(buffer)
    assert '加密' in upload(cid, 'encrypted.pdf', buffer.getvalue(), 400)['detail']
    request(f"/api/documents/{pdf['id']}/pages/99", expected=400)
    request('/api/demo', {**source, 'action': 'ask'}, 'POST', 400)
    request(cp + '/notes', message_source, 'POST', 400)
    request(cp + '/messages', {'document_id': pdf['id'], 'page_start': 2, 'page_end': 1, 'question': 'wrong range'}, 'POST', 400)
    check('course isolation, upload limits and readable validation errors')
    request('/api/documents/' + doc['id'], method='DELETE')
    notes = request(cp + '/notes')
    assert notes[0]['document_id'] is None and notes[0]['name'] == doc['name']
    assert len(request(cp + '/messages')) == 4
    assert not path.exists()
    request('/api/notes/' + note['id'], method='DELETE')
    request('/api/notes/' + note['id'], method='DELETE', expected=404)
    request(f"/api/documents/{doc['id']}/pages/1", expected=404)
    with closing(sqlite3.connect(database)) as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM pages WHERE document_id=?', (doc['id'],)).fetchone()[0] == 0
    check('deleting materials retains source snapshots and clears extracted pages')
    (ROOT / '.cache/smoke-report.json').write_text(json.dumps({'passed': checks, 'count': len(checks)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('All API checks passed in isolated test data.')

if __name__ == '__main__':
    main()
