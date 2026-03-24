"""HTTP channel implementation - exposes webhook endpoints for messaging."""

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


class HTTPChannelConfig(Base):
    """HTTP channel configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 18791
    path: str = "/webhook"
    response_path: str = "/response"
    auth_token: str = ""
    allow_from: list[str] = Field(default_factory=list)


class HTTPChannel(BaseChannel):
    """HTTP channel exposing webhook endpoints."""

    name = "http"
    display_name = "HTTP"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return HTTPChannelConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = HTTPChannelConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: HTTPChannelConfig = config
        self._server: asyncio.Server | None = None
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._responses_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the HTTP server."""
        if not self.config.enabled:
            return

        self._running = True

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await self._handle_request(reader, writer)

        self._server = await asyncio.start_server(handler, self.config.host, self.config.port)

        logger.info(
            "HTTP channel listening on http://{}:{}{}",
            self.config.host,
            self.config.port,
            self.config.path,
        )

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._running = False
        logger.info("HTTP channel stopped")

    def _get_response_key(self, chat_id: str) -> str:
        """Generate key for response queue."""
        return chat_id

    async def _get_or_create_queue(self, key: str) -> asyncio.Queue:
        """Get or create a response queue for the given key."""
        async with self._responses_lock:
            if key not in self._pending_responses:
                self._pending_responses[key] = asyncio.Queue()
            return self._pending_responses[key]

    async def _handle_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming HTTP request."""
        try:
            request_line = await reader.readline()
            if not request_line:
                await self._write_error(writer, 400, "Bad Request")
                return

            method, path, _ = request_line.decode().strip().split()

            headers = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, value = line.decode().strip().split(":", 1)
                headers[key.lower()] = value.strip()

            content_length = int(headers.get("content-length", 0))
            body = b""
            if content_length > 0:
                body = await reader.read(content_length)

            if path == self.config.path and method == "POST":
                await self._handle_post(writer, headers, body)
            elif path == self.config.path and method == "GET":
                await self._handle_get(writer)
            elif path.startswith(self.config.response_path) and method == "GET":
                await self._handle_response_get(writer, headers, path)
            else:
                await self._write_error(writer, 404, "Not Found")
        except Exception as e:
            logger.error("HTTP channel error: {}", e)
            await self._write_error(writer, 500, "Internal Server Error")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_post(
        self,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Handle POST request - receive inbound message."""
        if self.config.auth_token:
            auth_header = headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                await self._write_error(writer, 401, "Unauthorized")
                return
            token = auth_header[7:]
            if token != self.config.auth_token:
                await self._write_error(writer, 401, "Unauthorized")
                return

        try:
            data = json.loads(body.decode())
        except json.JSONDecodeError:
            await self._write_error(writer, 400, "Invalid JSON")
            return

        content = data.get("content", "")
        sender_id = data.get("sender_id", "http_user")
        user_id = data.get("user_id", sender_id)
        chat_id = data.get("chat_id", "http_chat")
        metadata = data.get("metadata", {})

        key = self._get_response_key(chat_id)
        await self._get_or_create_queue(key)

        await self._handle_message(
            sender_id=sender_id,
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            metadata=metadata,
        )

        await self._write_json(writer, 200, {
            "status": "ok",
            "chat_id": chat_id,
            "response_url": f"{self.config.response_path}?chat_id={chat_id}"
        })

    async def _handle_response_get(
        self,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        path: str,
    ) -> None:
        """Handle GET request - poll for response."""
        if self.config.auth_token:
            auth_header = headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                await self._write_error(writer, 401, "Unauthorized")
                return
            token = auth_header[7:]
            if token != self.config.auth_token:
                await self._write_error(writer, 401, "Unauthorized")
                return

        query = path.split("?")[1] if "?" in path else ""
        params = dict(p.split("=") for p in query.split("&") if "=" in p)
        chat_id = params.get("chat_id", "")

        if not chat_id:
            await self._write_error(writer, 400, "Missing chat_id")
            return

        key = self._get_response_key(chat_id)

        try:
            queue = self._pending_responses.get(key)
            if queue is None or queue.empty():
                await self._write_json(writer, 200, {"status": "no_response"})
                return

            try:
                response = await asyncio.wait_for(queue.get(), timeout=30.0)
                await self._write_json(writer, 200, {
                    "status": "ok",
                    "content": response.content,
                })
            except asyncio.TimeoutError:
                await self._write_json(writer, 200, {"status": "waiting"})
        except Exception as e:
            logger.error("Response polling error: {}", e)
            await self._write_error(writer, 500, str(e))

    async def _handle_get(self, writer: asyncio.StreamWriter) -> None:
        """Handle GET request - health check."""
        await self._write_json(writer, 200, {"status": "ok", "channel": self.name})

    async def send(self, msg: OutboundMessage) -> None:
        """Store outbound message for polling."""
        key = self._get_response_key(msg.chat_id)
        queue = self._pending_responses.get(key)
        if queue:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Response queue full for {}", key)
        else:
            logger.debug("No pending request for {}: {}", key, msg.content[:50])

    async def _write_json(self, writer: asyncio.StreamWriter, status: int, data: dict) -> None:
        """Write JSON response."""
        body = json.dumps(data).encode()
        await self._write_response(writer, status, "application/json", body)

    async def _write_error(self, writer: asyncio.StreamWriter, status: int, message: str) -> None:
        """Write error response."""
        body = json.dumps({"error": message}).encode()
        await self._write_response(writer, status, "application/json", body)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        content_type: str,
        body: bytes,
    ) -> None:
        """Write HTTP response."""
        status_text = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
        }.get(status, "OK")

        response = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body

        writer.write(response)
        await writer.drain()
