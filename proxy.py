#!/usr/bin/env python3
import requests
import threading
import queue
import json
import os
import signal
import sys
from flask import Flask, request, Response

###############################################################################
# Configuration
###############################################################################

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9000

UPSTREAM_URL = "http://172.16.10.51:8030/mcp"

# Internal event queue for clean shutdown
shutdown_flag = threading.Event()

app = Flask(__name__)

###############################################################################
# Utility Functions
###############################################################################

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_header():
    clear_screen()
    print("=" * 80)
    print("              MCP REWRITE PROXY — HTTP STREAMABLE MODE")
    print("=" * 80)
    print(f"Listening on: http://{LISTEN_HOST}:{LISTEN_PORT}/mcp")
    print(f"Forwarding to upstream: {UPSTREAM_URL}")
    print("(Press 'q' at any time to quit)\n")

def safe_json_dump(data):
    try:
        return json.dumps(data, indent=2)
    except:
        return str(data)

###############################################################################
# Graceful Shutdown Controller
###############################################################################

def start_keyboard_listener():
    def wait_for_exit():
        while not shutdown_flag.is_set():
            ch = sys.stdin.read(1)
            if ch.lower() == "q":
                print("\nShutdown requested by user…")
                shutdown_flag.set()
                os._exit(0)

    t = threading.Thread(target=wait_for_exit, daemon=True)
    t.start()

def handle_sigint(sig, frame):
    print("\nCTRL‑C received — shutting down cleanly…")
    shutdown_flag.set()
    os._exit(0)

signal.signal(signal.SIGINT, handle_sigint)

###############################################################################
# Core MCP Proxy Logic
###############################################################################

@app.route("/mcp", methods=["POST"])
def proxy_mcp():

    # A → B
    print("\n--- PACKET GROUP -----------------------------------------------------")
    print("A → B (Client → Proxy)")
    print(safe_json_dump(request.json), "\n")

    # Forward A→B to upstream (B→C)
    try:
        upstream = requests.post(
            UPSTREAM_URL,
            json=request.json,
            stream=True,
            timeout=30
        )
    except Exception as e:
        print("B → C FAILED (Proxy → Upstream)")
        print(f"Error: {e}\n")
        return {"error": f"Proxy upstream request failed: {e}"}, 500

    print("B → C (Proxy → Upstream)")
    print("(sent successfully)\n")

    # Prepare streaming generator for C → B
    def generate():

        c_to_b_chunks = []
        b_to_a_sent = False

        print("C → B (Upstream → Proxy)")

        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if shutdown_flag.is_set():
                    break

                if chunk:
                    text = chunk.decode(errors="ignore")
                    c_to_b_chunks.append(text)
                    print(text.strip())
                    yield chunk

            print()  # spacing after C→B block

            print("B → A (Proxy → Client)")
            if c_to_b_chunks:
                for line in c_to_b_chunks:
                    print(line.strip())
            else:
                print("(no data received)")
            print()

        except Exception as e:
            print("C → B FAILED (error while receiving upstream stream)")
            print(f"Error: {e}\n")
            yield json.dumps({"error": f"stream failure: {e}"}).encode()

    # Return streaming response to client
    return Response(
        generate(),
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/json"),
    )

###############################################################################
# Main Entry
###############################################################################

if __name__ == "__main__":
    print_header()
    start_keyboard_listener()
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True)
