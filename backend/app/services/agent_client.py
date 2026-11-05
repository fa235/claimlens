"""Agentex client — delegates claim analysis to the Agentex multi-agent system.

Used only when ANALYSIS_MODE=agents. ClaimLens calls the Agentex backend's
agent RPC endpoint to run the orchestrator agent (which coordinates the Damage
Detection and Cost Estimation sub-agents) against a claim ID.

Flow (two JSON-RPC calls to POST /agents/name/{agent}/rpc):
  1. task/create   → creates a task for the agent
  2. message/send  → sends the claim ID; returns the agent's text summary

This keeps ClaimLens's inline pipeline intact — it's an alternate path behind
the ANALYSIS_MODE flag, not a replacement.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings


def _rpc_url() -> str:
    base = settings.agentex_base_url.rstrip("/")
    return f"{base}/agents/name/{settings.agentex_agent_name}/rpc"


class AgentUnavailableError(RuntimeError):
    """Raised when the Agentex agent can't be reached or returns an error."""


async def run_claim_via_agent(claim_id: str, timeout: float = 180.0) -> str:
    """Run the Agentex orchestrator on a claim ID; return its text summary.

    Raises AgentUnavailableError on any transport/protocol failure so the
    caller can fall back or surface a clear message.
    """
    url = _rpc_url()
    async with httpx.AsyncClient(timeout=timeout) as client:
        # 1) Create a task for this analysis.
        try:
            task_resp = await client.post(url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "task/create",
                "params": {"name": f"claimlens-{claim_id[:8]}-{uuid.uuid4().hex[:6]}"},
            })
        except httpx.HTTPError as e:
            raise AgentUnavailableError(f"Could not reach Agentex at {url}: {e}")

        if task_resp.status_code != 200:
            raise AgentUnavailableError(
                f"Agentex task/create failed ({task_resp.status_code}): {task_resp.text[:200]}"
            )
        task = (task_resp.json() or {}).get("result") or {}
        task_id = task.get("id")
        if not task_id:
            raise AgentUnavailableError(f"Agentex task/create returned no task id: {task_resp.text[:200]}")

        # 2) Send the claim ID as a message; the agent orchestrates and replies.
        try:
            msg_resp = await client.post(url, json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "message/send",
                "params": {
                    "task_id": task_id,
                    "content": {
                        "type": "text",
                        "author": "user",
                        "content": f"Analyze claim {claim_id}",
                    },
                    "stream": False,
                },
            })
        except httpx.HTTPError as e:
            raise AgentUnavailableError(f"Agentex message/send transport error: {e}")

        if msg_resp.status_code != 200:
            raise AgentUnavailableError(
                f"Agentex message/send failed ({msg_resp.status_code}): {msg_resp.text[:200]}"
            )

    payload = msg_resp.json() or {}
    if payload.get("error"):
        raise AgentUnavailableError(f"Agentex returned an error: {payload['error']}")

    # result is a list of task messages; take the last agent text message.
    result = payload.get("result")
    messages = result if isinstance(result, list) else [result]
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        content = m.get("content") or {}
        if content.get("author") == "agent" and content.get("content"):
            return content["content"]
    raise AgentUnavailableError("Agentex response contained no agent message.")
