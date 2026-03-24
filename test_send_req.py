#!/usr/bin/env python3
"""Test script to send requests to the HTTP channel webhook."""

import argparse
import asyncio
import json
import httpx


async def send_message(
    url: str,
    content: str,
    sender_id: str = "test_user",
    chat_id: str = "test_chat",
    auth_token: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Send a message to the HTTP channel webhook."""
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    payload = {
        "content": content,
        "sender_id": sender_id,
        "chat_id": chat_id,
    }
    if metadata:
        payload["metadata"] = metadata

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def health_check(url: str) -> dict:
    """Check if the HTTP channel is running."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def main():
    parser = argparse.ArgumentParser(description="Test HTTP channel webhook")
    parser.add_argument(
        "--url",
        default="http://localhost:18791/webhook",
        help="Webhook URL",
    )
    parser.add_argument(
        "--content",
        default="Hello from HTTP channel!",
        help="Message content",
    )
    parser.add_argument(
        "--sender-id",
        default="test_user",
        help="Sender ID",
    )
    parser.add_argument(
        "--chat-id",
        default="test_chat",
        help="Chat ID",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Auth token (if configured)",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Perform health check instead of sending message",
    )

    args = parser.parse_args()

    if args.health:
        print(f"Checking health at {args.url}...")
        result = await health_check(args.url)
        print(f"Health check result: {json.dumps(result, indent=2)}")
    else:
        print(f"Sending message to {args.url}...")
        print(f"Content: {args.content}")
        print(f"Sender: {args.sender_id}, Chat: {args.chat_id}")

        result = await send_message(
            url=args.url,
            content=args.content,
            sender_id=args.sender_id,
            chat_id=args.chat_id,
            auth_token=args.token or None,
        )
        print(f"Response: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
