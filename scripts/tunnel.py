"""
scripts/tunnel.py — Start and maintain the ngrok tunnel.

Keeps the tunnel alive, auto-updates WEBHOOK_PUBLIC_URL in .env,
and clears proxy env vars that ngrok injects (which break Google API SSL).

Run:
    python scripts/tunnel.py
"""

import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from pyngrok import ngrok

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH      = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH)

NGROK_AUTH = os.getenv("NGROCK_AUTH", "")
API_PORT   = int(os.getenv("API_PORT", "8000"))

if NGROK_AUTH:
    ngrok.set_auth_token(NGROK_AUTH)
else:
    print("WARNING: NGROCK_AUTH not set in .env")

tunnel     = ngrok.connect(API_PORT, bind_tls=True)
public_url = tunnel.public_url

# Remove proxy vars ngrok may have injected — they break Google API SSL
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)

print(f"\n{'='*60}")
print(f"  Ngrok tunnel active")
print(f"  Public URL : {public_url}")
print(f"  Webhook    : {public_url}/webhook/gmail")
print(f"{'='*60}\n")

# Auto-update .env with the current URL
env_text = ENV_PATH.read_text(encoding="utf-8")
if "WEBHOOK_PUBLIC_URL=" in env_text:
    env_text = re.sub(r"WEBHOOK_PUBLIC_URL=.*", f"WEBHOOK_PUBLIC_URL={public_url}", env_text)
else:
    env_text += f"\nWEBHOOK_PUBLIC_URL={public_url}\n"
ENV_PATH.write_text(env_text, encoding="utf-8")
print(f"✓ .env updated: WEBHOOK_PUBLIC_URL={public_url}")
print(f"\nUpdate your Pub/Sub push subscription endpoint to:")
print(f"  {public_url}/webhook/gmail\n")
print("Tunnel running. Press Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(30)
        if not ngrok.get_tunnels():
            print("Tunnel died — reconnecting...")
            tunnel     = ngrok.connect(API_PORT, bind_tls=True)
            public_url = tunnel.public_url
            print(f"New URL: {public_url}")
except KeyboardInterrupt:
    print("\nStopping ngrok tunnel...")
    ngrok.kill()
    print("Done.")
