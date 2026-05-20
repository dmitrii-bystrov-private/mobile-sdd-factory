"""ASGI entrypoint for the Constellation: Agent Runtime backend."""

from backend.api.app import create_app

app = create_app()
