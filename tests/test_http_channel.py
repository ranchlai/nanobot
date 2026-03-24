import asyncio

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.http import HTTPChannel, HTTPChannelConfig


@pytest.fixture
def config():
    return HTTPChannelConfig(
        enabled=True,
        host="127.0.0.1",
        port=18799,
        path="/webhook",
        auth_token="test-token",
        allow_from=["*"],
    )


@pytest.fixture
async def channel(config):
    bus = MessageBus()
    ch = HTTPChannel(config, bus)
    await ch.start()
    yield ch
    await ch.stop()


@pytest.fixture
async def channel_no_auth():
    config = HTTPChannelConfig(
        enabled=True,
        host="127.0.0.1",
        port=18798,
        path="/webhook",
        auth_token="",
        allow_from=["*"],
    )
    bus = MessageBus()
    ch = HTTPChannel(config, bus)
    await ch.start()
    yield ch
    await ch.stop()


@pytest.mark.asyncio
async def test_health_check(channel):
    """Test GET request returns health status."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    request = b"GET /webhook HTTP/1.1\r\nHost: localhost\r\n\r\n"
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 200 OK" in response
    assert b'"status": "ok"' in response


@pytest.mark.asyncio
async def test_send_message_with_auth(channel):
    """Test POST request with valid auth token."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    body = '{"content": "Hello!", "sender_id": "user1", "chat_id": "chat1"}'
    request = (
        f"POST /webhook HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Authorization: Bearer test-token\r\n"
        f"\r\n"
        f"{body}"
    ).encode()
    
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 200 OK" in response
    assert b'"status": "ok"' in response


@pytest.mark.asyncio
async def test_send_message_without_auth(channel):
    """Test POST request without auth token returns 401."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    body = '{"content": "Hello!"}'
    request = (
        f"POST /webhook HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        f"{body}"
    ).encode()
    
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 401 Unauthorized" in response


@pytest.mark.asyncio
async def test_send_message_invalid_token(channel):
    """Test POST request with invalid auth token returns 401."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    body = '{"content": "Hello!"}'
    request = (
        f"POST /webhook HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Authorization: Bearer wrong-token\r\n"
        f"\r\n"
        f"{body}"
    ).encode()
    
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 401 Unauthorized" in response


@pytest.mark.asyncio
async def test_invalid_path(channel):
    """Test request to invalid path returns 404."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    request = b"GET /invalid HTTP/1.1\r\nHost: localhost\r\n\r\n"
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 404 Not Found" in response


@pytest.mark.asyncio
async def test_invalid_json(channel):
    """Test POST with invalid JSON returns 400."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18799)
    
    body = "not valid json"
    request = (
        f"POST /webhook HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Authorization: Bearer test-token\r\n"
        f"\r\n"
        f"{body}"
    ).encode()
    
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 400 Bad Request" in response


@pytest.mark.asyncio
async def test_message_without_auth_allowed(channel_no_auth):
    """Test POST without auth token succeeds when auth is not configured."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 18798)
    
    body = '{"content": "Hello!", "sender_id": "user1", "chat_id": "chat1"}'
    request = (
        f"POST /webhook HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        f"{body}"
    ).encode()
    
    writer.write(request)
    await writer.drain()
    
    response = await reader.read(1024)
    writer.close()
    await writer.wait_closed()
    
    assert b"HTTP/1.1 200 OK" in response
