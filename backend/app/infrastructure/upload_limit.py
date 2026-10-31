"""Cap multipart requests while receiving, including chunked request bodies."""

from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.errors import api_error


class UploadLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") != "/api/floor-plans/uploads":
            return await self.app(scope, receive, send)
        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                raise api_error(413, "image_too_large", "Upload request exceeds the size limit.")
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except HTTPException as exc:
            if started:
                raise
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
