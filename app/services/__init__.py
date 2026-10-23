"""Service layer: all business logic and DB access.

Shared by the REST API (app/api) and the voice agent tools (app/voice), so a
patient saved over the phone goes through exactly the same code path as
``POST /patients``.
"""
