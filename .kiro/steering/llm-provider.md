# LLM Provider — ClaimLens

## Decision: OpenAI only. Groq has been removed.

ClaimLens uses **OpenAI (GPT-4o)** for both the vision call (car color/model
identification) and the cost-estimation call. This is the single supported
LLM provider for running and testing the project.

## Rules for the agent

- **Do NOT reintroduce additional models like Groq.** Groq was evaluated and dropped because its
  catalog had no usable vision chat model. Any leftover Groq config, env vars
  (`GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_COST_MODEL`), or code branches should
  be treated as dead and removed, not revived.
- **Do NOT test for or check for additional models like Groq loading** when running the project. There is
  no Groq key to validate and no Groq route to exercise.
- When running or verifying the backend, assume `LLM_PROVIDER=openai`.
- `bedrock` remains a valid future provider (pending AWS on-demand quota), but
  the default and the only path to test right now is `openai`.

## Quick reference

- Vision: OpenAI `gpt-4o` (`OPENAI_VISION_MODEL`)
- Cost estimate: OpenAI `gpt-4o` (`OPENAI_COST_MODEL`)
- Required env: `OPENAI_API_KEY`
