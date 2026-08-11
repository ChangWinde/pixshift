"""Entry point: ``python -m pixshift.mcp`` serves MCP over stdio."""

from .server import serve

if __name__ == "__main__":
    serve()
