#!/usr/bin/env python3
"""
Bot stub for Hub integration testing.

Lightweight WebSocket client that implements the bot registration protocol
used by TetraCore_Bot. Connects to Hub, registers as client_type="bot",
handles incoming tasks (ping_bot), and sends heartbeats.

Environment variables:
    HUB_URL     - WebSocket URL (default: ws://localhost:8000/ws)
    AUTH_TOKEN  - JWT auth token
    CLIENT_ID   - Bot client ID (default: auto-generated)
    CLIENT_NAME - Bot display name
"""

import asyncio
import json
import os
import signal
import sys
import uuid
from datetime import datetime, timezone

import websockets

HUB_URL = os.environ.get("HUB_URL", "ws://localhost:8000/ws")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")
CLIENT_ID = os.environ.get("CLIENT_ID", f"tetracore_bot_test_{uuid.uuid4().hex[:8]}")
CLIENT_NAME = os.environ.get("CLIENT_NAME", "TetraCore Bot (integration test)")

shutdown = asyncio.Event()


def _handle_signal(*_):
    shutdown.set()


async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    headers = {}
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

    try:
        async with websockets.connect(
            HUB_URL,
            extra_headers=headers,
            open_timeout=15,
            close_timeout=5,
        ) as ws:
            # --- Step 1: Register as bot ---
            reg_msg = {
                "type": "client_registration",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "client_id": CLIENT_ID,
                "client_type": "bot",
                "client_name": CLIENT_NAME,
                "version": "1.0.0",
                "capabilities": {
                    "supported_task_types": [
                        "ping_bot",
                        "generic_bot_task",
                        "activate_module",
                        "deactivate_module",
                        "check_user_admin",
                    ],
                    "max_concurrent_tasks": 5,
                    "average_processing_time": 0.0,
                    "max_task_size": 1048576,
                    "supported_formats": ["json"],
                    "special_capabilities": [],
                    "api_version": "1.0.0",
                    "min_priority": "low",
                    "max_priority": "critical",
                },
            }
            if AUTH_TOKEN:
                reg_msg["auth_token"] = AUTH_TOKEN

            await ws.send(json.dumps(reg_msg))

            # --- Step 2: Wait for registration response ---
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            resp = json.loads(raw)

            if not resp.get("success", False):
                print(f"REGISTRATION_FAILED: {resp}", file=sys.stderr, flush=True)
                sys.exit(1)

            session_id = resp.get("session_id", resp.get("client_id", ""))
            print(
                f"BOT_REGISTERED client_id={CLIENT_ID} session={session_id}", flush=True
            )

            # --- Step 3: Message & heartbeat loops ---
            async def read_loop():
                try:
                    async for raw_msg in ws:
                        msg = json.loads(raw_msg)
                        msg_type = msg.get("type", "")

                        if msg_type == "task":
                            task_id = msg.get("task_id", "")
                            task_type = msg.get("task_type", "")
                            print(
                                f"TASK_RECEIVED task_id={task_id} type={task_type}",
                                flush=True,
                            )

                            result_msg = {
                                "type": "task_result",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "task_id": task_id,
                                "worker_id": CLIENT_ID,
                                "status": "completed",
                                "result": {
                                    "success": True,
                                    "message": "Bot is alive",
                                    "bot_id": CLIENT_ID,
                                },
                                "execution_time": 0.001,
                            }
                            await ws.send(json.dumps(result_msg))
                            print(f"TASK_RESULT_SENT task_id={task_id}", flush=True)

                        elif msg_type == "error":
                            print(f"HUB_ERROR: {msg}", file=sys.stderr, flush=True)

                except websockets.ConnectionClosed:
                    pass

            async def heartbeat_loop():
                while not shutdown.is_set():
                    hb = {
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "client_id": CLIENT_ID,
                        "metrics": {"connected": True},
                    }
                    try:
                        await ws.send(json.dumps(hb))
                    except websockets.ConnectionClosed:
                        break
                    try:
                        await asyncio.wait_for(shutdown.wait(), timeout=30)
                        break
                    except asyncio.TimeoutError:
                        pass

            read_task = asyncio.create_task(read_loop())
            hb_task = asyncio.create_task(heartbeat_loop())
            shutdown_task = asyncio.create_task(shutdown.wait())

            done, pending = await asyncio.wait(
                [read_task, hb_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            print("BOT_SHUTDOWN", flush=True)

    except Exception as e:
        print(f"BOT_ERROR: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
