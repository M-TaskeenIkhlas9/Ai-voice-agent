"""Voice agent layer: Vapi assistant config, system prompt, and tool handlers.

Vapi owns telephony, speech-to-text, text-to-speech and the LLM turn loop.
This package owns *what the agent says and does*: the prompt (prompt.py),
the tools it can call (tools.py), and the webhook Vapi calls (webhook.py).
"""
