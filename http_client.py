#!/usr/bin/env python3
"""Simple HTTP client to send queries to nanobot HTTP channel."""

import argparse
import asyncio
import json
import uuid

import httpx


async def send_query(
    url: str,
    content: str,
    chat_id: str | None = None,
    user_id: str | None = None,
    auth_token: str | None = None,
    timeout: float = 120.0,
    poll_interval: float = 1.0,
) -> str | None:
    """Send a query and poll for response."""
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    chat_id = chat_id or f"http_{uuid.uuid4().hex[:8]}"
    user_id = user_id or "http_user"

    payload = {
        "content": content,
        "chat_id": chat_id,
        "user_id": user_id,
    }
    print(f"Sending query to {url} with payload: {json.dumps(payload)}")

    response_url = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        print(f"Query: {content}")
        print(f"Chat ID: {chat_id}")
        print("-" * 40)
        print("Waiting for response...")

        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        if data.get("response_url"):
            response_url = data["response_url"]

        if not response_url:
            print("No response endpoint available")
            return None

        base_url = url.split("/webhook")[0]
        poll_url = f"{base_url}{response_url}"

        while True:
            await asyncio.sleep(poll_interval)
            try:
                resp = await client.get(poll_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") == "ok" and data.get("content"):
                    return data["content"]
                elif data.get("status") == "no_response":
                    print(".", end="", flush=True)
                    continue
                else:
                    print(f"\nStatus: {data.get('status')}")
            except httpx.TimeoutException:
                print(".", end="", flush=True)
                continue
            except Exception as e:
                print(f"\nError polling: {e}")
                return None


async def main():
    parser = argparse.ArgumentParser(description="Send query to nanobot via HTTP channel")
    parser.add_argument(
        "--url",
        default="http://localhost:18791/webhook",
        help="Webhook URL",
    )
    parser.add_argument(
        "--content",
        required=True,
        help="Query content",
    )
    parser.add_argument(
        "--chat-id",
        help="Chat ID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--user-id",
        help="User ID (http_user if not provided)",
    )
    parser.add_argument(
        "--token",
        help="Auth token (if configured)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds",
    )

    args = parser.parse_args()

    result = await send_query(
        url=args.url,
        content=args.content,
        chat_id=args.chat_id,
        user_id=args.user_id,
        auth_token=args.token or None,
        poll_interval=args.poll_interval,
    )

    if result:
        print("\n" + "=" * 40)
        print("Response:")
        print(result)
    else:
        print("\nNo response received")


if __name__ == "__main__":
    asyncio.run(main())
