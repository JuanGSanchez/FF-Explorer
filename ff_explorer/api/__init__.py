"""
ff_explorer.api
===============
Agent-access layer for the FF-Explorer package.

Exposes the pure core (``ff_explorer.core``) through two front-doors — a
FastAPI REST app and a FastMCP MCP server — over a **single shared service
implementation**.  No traversal or filesystem logic lives here; all
computation is delegated to the core.

Importing this package does NOT require the GUI dependencies (PySide6).
The ``api`` optional-dependency group must be installed to run the server::

    pip install "ff-explorer[api]"

Sub-modules
-----------
service    — the one shared service layer both REST and MCP call.
rest       — FastAPI application (REST surface).
mcp_server — FastMCP server: Streamable HTTP + stdio entry point.
main       — combined ASGI app (REST routes + MCP at ``/mcp``); uvicorn entry.
"""
