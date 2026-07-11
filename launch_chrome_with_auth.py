#!/usr/bin/env python3
"""
Launch Chrome with Shopify auth cookies from fedex-test-automation/auth.json
so you're already logged in when the browser opens.
"""
import json
import subprocess
import time
import requests
import sys

AUTH_JSON = "/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/auth.json"
TARGET_URL = "https://admin.shopify.com/store/kee-fedex-qa/apps/testing-553"
DEBUG_PORT = 9222

def launch_chrome():
    cmd = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ]
    subprocess.Popen(cmd)
    print("Launching Chrome...")
    time.sleep(2)

def get_tab():
    for _ in range(10):
        try:
            tabs = requests.get(f"http://localhost:{DEBUG_PORT}/json").json()
            for tab in tabs:
                if tab.get("type") == "page":
                    return tab
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Could not connect to Chrome DevTools")

def inject_cookies_and_navigate(tab, cookies):
    ws_url = tab["webSocketDebuggerUrl"]
    import websocket
    import json as _json

    ws = websocket.create_connection(ws_url)
    msg_id = 1

    def send(method, params={}):
        nonlocal msg_id
        ws.send(_json.dumps({"id": msg_id, "method": method, "params": params}))
        result = _json.loads(ws.recv())
        msg_id += 1
        return result

    # Set each cookie
    for cookie in cookies:
        c = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", True),
            "httpOnly": cookie.get("httpOnly", False),
            "sameSite": cookie.get("sameSite", "Lax"),
        }
        if "expires" in cookie:
            c["expires"] = int(cookie["expires"])
        send("Network.setCookie", c)
        print(f"  Set cookie: {cookie['name']} → {cookie['domain']}")

    # Navigate to target URL
    send("Page.navigate", {"url": TARGET_URL})
    print(f"\nNavigating to: {TARGET_URL}")
    ws.close()

def main():
    with open(AUTH_JSON) as f:
        auth = json.load(f)

    cookies = auth.get("cookies", [])
    print(f"Loaded {len(cookies)} cookies from auth.json")

    launch_chrome()
    tab = get_tab()
    print(f"Connected to tab: {tab.get('title', 'unknown')}")

    try:
        inject_cookies_and_navigate(tab, cookies)
        print("\nDone! Chrome should now be open and logged into Shopify.")
        print("Use the Claude extension to run your BDD test.")
    except ImportError:
        # websocket-client not installed, fallback: just open URL
        print("websocket-client not available — opening URL directly...")
        subprocess.Popen([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            TARGET_URL
        ])

if __name__ == "__main__":
    main()
