"""ASGI entrypoint for the SDD Factory backend."""

from backend.api.app import create_app

app = create_app()
