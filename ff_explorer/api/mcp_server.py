"""
ff_explorer.api.mcp_server
===========================
FastMCP server derived from the REST FastAPI app.

This module creates the MCP server from the **same** ``rest.app`` FastAPI
application, ensuring zero logic duplication (F-single-core principle).
FastMCP introspects the FastAPI routes and auto-generates MCP tools from them.

MCP tools exposed
-----------------
health              — liveness + version (from GET /health).
post_list_entries   — list matching entries, non-destructive (from POST /entries).
post_entry_metadata — metadata for a single path (from POST /metadata).
post_save_listing   — write a .txt listing file (from POST /listing).
post_remove         — remove entries, GUARDED (from POST /remove).
post_compress       — compress entries, GUARDED (from POST /compress).

Dry-run default and confirm-token contract (for agents)
-------------------------------------------------------
``post_remove`` and ``post_compress`` are **DESTRUCTIVE operations**.

SAFE DEFAULT: calling either tool without ``dry_run: false`` and
``confirm: true`` returns a PREVIEW of what would be affected and
mutates NOTHING.  This is the default behaviour — agents should always
call the tool once in preview mode first.

TO ACTUALLY MUTATE: the tool call body MUST include BOTH:
  - ``"dry_run": false``    — explicitly disables preview mode
  - ``"confirm": true``     — explicit, unambiguous opt-in token

Sending only one of the two flags is NOT sufficient.

``post_remove`` routes deletes through send2trash (OS recycle bin) when
available, making removals recoverable.

Empty ``name_seed`` for destructive tools raises a structured MCP error
(``EmptySeedError``) — never use an empty seed with these tools.

Transports
----------
Streamable HTTP: ``mcp_app`` (ASGI app) mounted at ``/mcp`` by ``main.py``.
stdio:           run this module directly or via the ``ff-explorer-mcp``
                 console script.

ValueError / EmptySeedError propagation
----------------------------------------
FastMCP propagates HTTP 422 responses from the underlying FastAPI layer as
structured MCP tool errors (``isError: true`` with the ``detail`` field from
the 422 body), so the core's error messages reach the MCP client in a
structured form.
"""
from __future__ import annotations

from fastmcp import FastMCP

from ff_explorer.api.rest import app as _rest_app

# ---------------------------------------------------------------------------
# Create the MCP server from the REST app (single-core dual-interface pattern).
# FastMCP.from_fastapi() introspects the FastAPI route table and generates one
# MCP tool per route, delegating execution back to the FastAPI app.
# ---------------------------------------------------------------------------

mcp: FastMCP = FastMCP.from_fastapi(
    app=_rest_app,
    name="FF-Explorer MCP",
)

# ASGI app for Streamable HTTP transport.
# transport="streamable-http" is set explicitly (research limitation L3:
# confirmed here and pinned per the FastMCP 3.4.2 API).
mcp_app = mcp.http_app(path="/mcp", transport="streamable-http")


# ---------------------------------------------------------------------------
# stdio entry point
# ---------------------------------------------------------------------------

def run_stdio() -> None:  # pragma: no cover
    """Run the MCP server over stdio (for CLI/agent clients).

    Invoked by the ``ff-explorer-mcp`` console script or directly::

        python -m ff_explorer.api.mcp_server
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    run_stdio()
