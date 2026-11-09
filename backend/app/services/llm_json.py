"""
Helpers for coaxing JSON out of chat-completion replies.

Both LLM steps (vision and cost) ask the model for strict JSON and then have to
cope with what actually comes back. GPT-4o is well behaved; open-weight and
reasoning models served by Fireworks are not, so these helpers handle:

  * markdown fences around the payload
  * <think>...</think> blocks and prose wrapped around the JSON
  * reasoning models that put the answer in `reasoning_content` when they run
    out of token budget before emitting `content`

Shared by vision.py and cost_estimator.py so the two stay in step.
"""

import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def message_text(response) -> str:
    """
    Reads the assistant text out of an OpenAI-shaped response.

    Reasoning models served by Fireworks put the chain of thought in a separate
    `reasoning_content` field. Normally `content` holds the answer, but if the
    model spent its whole budget thinking, `content` comes back empty/None — in
    that case the JSON, if any, is in the reasoning trace, so fall back to it.
    """
    message = response.choices[0].message
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content

    extra = getattr(message, "model_extra", None) or {}
    reasoning = extra.get("reasoning_content") or getattr(message, "reasoning_content", None)
    return (reasoning or "").strip()


def iter_json_objects(text: str):
    """
    Yields every balanced {...} span in `text` that parses as JSON.

    Needed because reasoning models often wrap the answer in commentary, so the
    payload is not the whole string.
    """
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        yield json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break


def extract_json_object(raw: str, required_key: str | None = None) -> dict:
    """
    Pulls a JSON object out of a model reply, or returns {} if there is none.

    Args:
        raw:          The model's reply text.
        required_key: If given, prefer the first balanced object containing this
                      key. Keeps us from latching onto a nested fragment when
                      the model emits several objects.
    """
    if not raw:
        return {}

    text = _THINK_RE.sub(" ", raw)
    if "{" not in text:
        # The only JSON present was inside the reasoning block — keep it rather
        # than discarding the whole reply.
        text = raw
    text = _FENCE_RE.sub("", text).strip()

    try:
        direct = json.loads(text)
        if isinstance(direct, dict):
            return direct
    except json.JSONDecodeError:
        pass

    fallback = None
    for candidate in iter_json_objects(text):
        if not isinstance(candidate, dict):
            continue
        if required_key is None or required_key in candidate:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback or {}
