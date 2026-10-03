"""Bound raw upload requests on disk before multipart parsing, including chunked bodies."""
import tempfile
from starlette.responses import JSONResponse

class UploadBodyLimit:
    def __init__(self, app, limit, temp_dir):
        self.app, self.limit, self.temp_dir = app, limit, temp_dir

    async def __call__(self, scope, receive, send):
        is_upload = (scope["type"] == "http" and scope.get("method") == "POST"
                     and scope.get("path", "").startswith("/api/courses/")
                     and scope["path"].endswith("/documents"))
        if not is_upload:
            return await self.app(scope, receive, send)
        total_limit = self.limit + 1024 * 1024
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({"detail": "请求长度无效。"}, status_code=400)(scope, receive, send)
        if declared > total_limit:
            return await JSONResponse({"detail": "上传请求超过大小上限。"}, status_code=413)(scope, receive, send)
        with tempfile.TemporaryFile(dir=self.temp_dir) as buffered:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > total_limit:
                    return await JSONResponse({"detail": "上传请求超过大小上限。"}, status_code=413)(scope, receive, send)
                buffered.write(chunk)
                if not message.get("more_body", False):
                    break
            buffered.seek(0)
            completed = False
            async def replay():
                nonlocal completed
                if completed:
                    return await receive()
                body = buffered.read(1024 * 1024)
                completed = buffered.tell() >= size
                return {"type": "http.request", "body": body, "more_body": not completed}
            await self.app(scope, replay, send)
