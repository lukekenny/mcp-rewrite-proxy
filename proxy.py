#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HTTP Streamable MCP Rewrite Proxy
---------------------------------

This proxy sits between:
    OpenWebUI (HTTP Streamable MCP client)
        → this proxy
            → Firecrawl MCP server (HTTP Streamable)

Key features:
    • Proper SSE streaming passthrough
    • Correct Firecrawl headers injected on upstream requests
    • Full packet-flow logging (A→B, B→C, C→B, B→A)
    • Color-coded logs with timestamps
    • Final truncation rule:
          If packet does NOT start with '{':
              - Measure characters excluding '\n'
              - If >350, truncate to first 350 chars, preserving newlines,
                and append "... (truncated)" on the same line.
          If it DOES start with '{':
              - Log the entire JSON packet fully.
    • No duplicate packet logs
    • Safe shutdown behavior
"""

import requests
from flask import Flask, request, Response, stream_with_context
import sys
import time
import threading

app = Flask(__name__)

# -----------------------------------------------------------
# Configuration
# -----------------------------------------------------------
UPSTREAM_URL = "http://172.16.10.51:8030/mcp"    # Change if needed
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9000


# -----------------------------------------------------------
# ANSI Color Helpers
# -----------------------------------------------------------
class Color:
    RESET = "\033[0m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[31m"


# -----------------------------------------------------------
# Logging Utility
# -----------------------------------------------------------
def log_packet(direction, content, color=Color.CYAN):
    """
    direction: string label ("A→B", "B→C", "C→B", "B→A")
    content:   payload string
    color:     ANSI color for all lines printed
    """

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}[{ts}] {direction}{Color.RESET}")

    for line in content.split("\n"):
        print(f"{color}{line}{Color.RESET}")

    print("")  # blank line for readability
    sys.stdout.flush()


# -----------------------------------------------------------
# Truncation Rule (Final Specification)
# -----------------------------------------------------------
def apply_truncation_rule_if_needed(raw_packet):
    """
    Implements the precise behavior requested:

    If first non-whitespace char is not '{':
        • Count characters excluding '\n'
        • If > 350, truncate to first 350 such characters
          (preserving newline structure for the characters that remain)
        • Append '... (truncated)' on the SAME line

    If it starts with '{':
        • No truncation; return the packet as-is.
    """

    # Strip leading whitespace for the test, but don't remove it from content.
    stripped = raw_packet.lstrip()

    # JSON packets are logged fully
    if stripped.startswith("{"):
        return raw_packet

    # Count chars excluding newlines
    visible_chars = [c for c in raw_packet if c != "\n"]
    visible_len = len(visible_chars)

    if visible_len <= 350:
        return raw_packet

    # Need truncation:
    # Build a truncated string that keeps original newlines,
    # but only up to 350 visible chars.
    remaining = 350
    output = []
    for ch in raw_packet:
        if ch == "\n":
            output.append(ch)
            continue
        if remaining > 0:
            output.append(ch)
            remaining -= 1
        else:
            # Stop collecting further characters
            break

    # Append marker on same line
    output.append("... (truncated)")
    return "".join(output)


# -----------------------------------------------------------
# Helper: Remove Hop-by-Hop Headers
# -----------------------------------------------------------
def strip_hop_by_hop_headers(headers):
    """Remove headers that must not be forwarded."""
    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}


# -----------------------------------------------------------
# Main Proxy Route
# -----------------------------------------------------------
@app.route("/mcp", methods=["POST"])
def mcp():
    # A→B : Client → Proxy
    incoming_body = request.get_data(as_text=True) or ""
    incoming_headers = dict(request.headers)

    log_packet("A→B  Client → Proxy", incoming_body, Color.GREEN)

    # Prepare upstream headers
    filtered = strip_hop_by_hop_headers(incoming_headers)
    filtered.update({
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json"
    })

    # B→C : Proxy → Upstream
    log_packet("B→C  Proxy → Upstream", incoming_body, Color.MAGENTA)

    try:
        upstream_response = requests.post(
            UPSTREAM_URL,
            data=incoming_body.encode("utf-8"),
            headers=filtered,
            stream=True,
            timeout=None
        )
    except Exception as e:
        err = f"Proxy error contacting upstream:\n{repr(e)}"
        log_packet("ERROR", err, Color.RED)
        return Response("Upstream connection error", status=502)

    # C→B : Upstream → Proxy (SSE chunks)
    def generate():
        for chunk in upstream_response.iter_lines(decode_unicode=True):
            if chunk is None:
                continue

            # Ensure chunk ends with newline for logging + forwarding clarity
            text = chunk + "\n"

            # Log once (C→B) with truncation rule
            logged = apply_truncation_rule_if_needed(text)
            log_packet("C→B  Upstream → Proxy", logged, Color.YELLOW)

            # Forward unmodified to client
            yield text

    # B→A : Proxy → Client
    # Note: We deliberately do NOT re-log the data here (no duplicates).
    return Response(stream_with_context(generate()),
                    status=upstream_response.status_code,
                    content_type=upstream_response.headers.get("Content-Type", "text/event-stream"))


# -----------------------------------------------------------
# Graceful Shutdown Handler
# -----------------------------------------------------------
def shutdown_server():
    func = request.environ.get("werkzeug.server.shutdown")
    if func:
        func()


@app.route("/shutdown", methods=["POST"])
def shutdown():
    threading.Thread(target=shutdown_server).start()
    return "Proxy shutting down..."


# -----------------------------------------------------------
# Entry Point
# -----------------------------------------------------------
if __name__ == "__main__":
    print(f"\nStarting MCP proxy on http://{LISTEN_HOST}:{LISTEN_PORT}/mcp\n")
    sys.stdout.flush()
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True)
