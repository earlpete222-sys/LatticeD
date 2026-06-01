#!/usr/bin/env python3
"""
debug_stream.py — Raw SSE diagnostic.
Run: python debug_stream.py
Shows exactly what bytes /api/evolve sends back.
"""
import sys, time
import requests

URL = "http://127.0.0.1:8000"
KEY = "local_dev_secret_123"

print("=== Health check ===")
r = requests.get(f"{URL}/api/health", headers={"x-api-key": KEY}, timeout=5)
print(f"Status  : {r.status_code}")
print(f"Response: {r.json()}\n")

print("=== /api/evolve raw stream ===")
t0 = time.time()

resp = requests.get(
    f"{URL}/api/evolve",
    headers={"x-api-key": KEY, "Accept": "text/event-stream"},
    params={"prompt": "What is 2 plus 2?", "thread_id": "debug001", "path": "auto"},
    stream=True,
    timeout=(5, 120),
)

print(f"HTTP status : {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type', 'missing')}")
print(f"All headers : {dict(resp.headers)}")
print()

chunks_seen = 0
for chunk in resp.iter_content(chunk_size=None):
    chunks_seen += 1
    elapsed = time.time() - t0
    print(f"[{elapsed:6.2f}s] chunk #{chunks_seen}: {repr(chunk[:2000])}")
    if chunks_seen >= 30:
        print("[truncating after 30 chunks]")
        break

resp.close()
total = time.time() - t0
print(f"\nDone — {chunks_seen} chunks in {total:.2f}s")
if chunks_seen == 0:
    print("\n*** NO CHUNKS RECEIVED — server sent 0 bytes in the body ***")
    print("Check the Earl Prime console for an exception in gen().")
