"""Builds the Vapi assistant definition (pushed by scripts/setup_vapi.py).

Keeping the assistant as code (rather than click-ops in the Vapi dashboard)
means the prompt, tools, voice and webhook URL are versioned with the backend
that serves them.
"""

from __future__ import annotations

import os

from app.voice.prompt import build_first_message, build_system_prompt
from app.voice.tools import TOOL_SCHEMAS

ASSISTANT_NAME = "Patient Intake Agent"


def build_assistant_config(public_base_url: str, webhook_secret: str) -> dict:
    clinic = os.getenv("CLINIC_NAME", "Riverside Family Health")
    timezone = os.getenv("CLINIC_TIMEZONE", "America/New_York")

    server: dict = {"url": f"{public_base_url.rstrip('/')}/vapi/webhook", "timeoutSeconds": 20}
    if webhook_secret:
        server["headers"] = {"x-webhook-secret": webhook_secret}

    tools = [{**tool, "server": server} for tool in TOOL_SCHEMAS]
    tools.append({"type": "endCall"})

    return {
        "name": ASSISTANT_NAME,
        "firstMessage": build_first_message(clinic),
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": os.getenv("VAPI_MODEL_PROVIDER", "openai"),
            "model": os.getenv("VAPI_MODEL", "gpt-4o"),
            # Low temperature: consistent wording and faithful field capture.
            "temperature": 0.3,
            "messages": [{"role": "system", "content": build_system_prompt(clinic, timezone)}],
            "tools": tools,
        },
        "voice": {
            "provider": os.getenv("VAPI_VOICE_PROVIDER", "11labs"),
            "voiceId": os.getenv("VAPI_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
            # Multilingual model so the same voice can switch to Spanish.
            "model": os.getenv("VAPI_VOICE_MODEL", "eleven_turbo_v2_5"),
        },
        "transcriber": {
            "provider": "deepgram",
            "model": os.getenv("VAPI_TRANSCRIBER_MODEL", "nova-3"),
            # "multi" = English/Spanish code-switching for the language bonus.
            "language": os.getenv("VAPI_TRANSCRIBER_LANGUAGE", "multi"),
        },
        # Callers pause while reading out phone numbers and dates; wait a bit
        # longer before replying so the agent does not cut them off.
        "startSpeakingPlan": {"waitSeconds": 0.8},
        # Let "uh-huh" / "okay" pass without stopping the agent mid-sentence,
        # but a real interruption (2+ words) does.
        "stopSpeakingPlan": {"numWords": 2},
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 900,
        "endCallMessage": "Thanks for calling. Take care!",
        "server": server,
        "serverMessages": ["tool-calls", "status-update", "end-of-call-report"],
    }
