"""
ff_explorer.api.main
=====================
Combined ASGI application: REST routes + MCP at ``/mcp``.

This is the **single runnable entry point** for the access layer.  It
stitches together the FastAPI REST app (``rest.app``) and the FastMCP ASGI
app (``mcp_server.mcp_app``) into one ``FastAPI`` instance served by a
single uvicorn process.

Architecture
------------
  rest.app           — the FastAPI REST app (routes: /health, /entries,
                       /metadata, /listing, /remove, /compress)
  mcp_server.mcp_app — the FastMCP ASGI app (Streamable HTTP at /mcp)
  app                — this module's combined app: all routes merged,
                       MCP lifespan forwarded

The MCP lifespan is forwarded to ``app`` as required by FastMCP (it starts
the internal MCP session manager).

Run commands
------------
HTTP server (REST + MCP Streamable HTTP)::

    uvicorn ff_explorer.api.main:app --host 0.0.0.0 --port 8000

or via the ``ff-explorer-api`` console script::

    ff-explorer-api

stdio MCP client::

    ff-explorer-mcp

Endpoints after startup
-----------------------
REST:
  GET  http://localhost:8000/health
  POST http://localhost:8000/entries
  POST http://localhost:8000/metadata
  POST http://localhost:8000/listing
  POST http://localhost:8000/remove
  POST http://localhost:8000/compress

MCP (Streamable HTTP):
  http://localhost:8000/mcp

Interactive docs (FastAPI auto-generated):
  http://localhost:8000/docs
  http://localhost:8000/redoc
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from ff_explorer import __version__
from ff_explorer.api.mcp_server import mcp_app
from ff_explorer.api.rest import app as _rest_app

# ---------------------------------------------------------------------------
# Combine REST routes + MCP routes in one ASGI app.
# The MCP lifespan MUST be forwarded — it starts the FastMCP session manager
# (required per research Finding F1.4 / gofastmcp.com/integrations/fastapi).
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FF-Explorer (REST + MCP)",
    version=__version__,
    description=(
        "Combined REST + MCP access layer for the FF-Explorer package.  "
        "REST routes are served directly; MCP (Streamable HTTP) is at /mcp.  "
        "Destructive routes (remove, compress) default to dry-run preview mode."
    ),
    lifespan=mcp_app.lifespan,  # REQUIRED: starts the MCP session manager
)

# Mount all routes from both apps into the combined app.
for route in mcp_app.routes:
    app.routes.append(route)
for route in _rest_app.routes:
    app.routes.append(route)


# ---------------------------------------------------------------------------
# Console-script entry point (ff-explorer-api)
# ---------------------------------------------------------------------------

def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:  # pragma: no cover
    """Start the uvicorn server.

    Invoked by the ``ff-explorer-api`` console script.
    """
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run_server()
