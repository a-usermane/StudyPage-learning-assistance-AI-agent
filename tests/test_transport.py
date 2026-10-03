"""Raw ASGI request limits independent of Content-Length and multipart parsing."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from backend.api.middleware import UploadBodyLimit
from backend.config import ROOT

class UploadTransportTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, chunks, headers=(), disconnect=False):
        root = ROOT / '.cache/tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            delivered = []
            sent = []
            messages = [{'type': 'http.request', 'body': body, 'more_body': i < len(chunks) - 1}
                        for i, body in enumerate(chunks)]
            if disconnect:
                messages = [{'type': 'http.disconnect'}]
            async def receive():
                return messages.pop(0)
            async def send(message):
                sent.append(message)
            async def downstream(scope, receive, send):
                while True:
                    message = await receive()
                    delivered.append(message['body'])
                    if not message.get('more_body'):
                        break
                await send({'type': 'http.response.start', 'status': 201, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'OK'})
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/courses/course/documents', 'headers': list(headers)}
            await UploadBodyLimit(downstream, 32, Path(folder))(scope, receive, send)
            self.assertFalse(list(Path(folder).iterdir()))
            return delivered, sent

    async def test_chunked_oversize_never_enters_multipart_parser(self):
        delivered, sent = await self.exercise([b'x' * 600_000, b'x' * 600_000])
        self.assertEqual(delivered, [])
        self.assertEqual(sent[0]['status'], 413)

    async def test_spoofed_content_length_still_counts_real_bytes(self):
        delivered, sent = await self.exercise([b'x' * 1_100_000], [(b'content-length', b'1')])
        self.assertEqual(delivered, [])
        self.assertEqual(sent[0]['status'], 413)

    async def test_replay_preserves_bytes_and_allows_bounded_request(self):
        delivered, sent = await self.exercise([b'first', b'second'])
        self.assertEqual(b''.join(delivered), b'firstsecond')
        self.assertEqual(sent[0]['status'], 201)

    async def test_invalid_length_and_disconnect(self):
        _, sent = await self.exercise([b'body'], [(b'content-length', b'bad')])
        self.assertEqual(sent[0]['status'], 400)
        delivered, sent = await self.exercise([], disconnect=True)
        self.assertEqual((delivered, sent), ([], []))
