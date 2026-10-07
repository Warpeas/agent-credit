"""MonkeyCode 钱包/签到端点探测（只读）。

凭据：%APPDATA%/com.chaitin.baizhi.monkeycode/monkeycode-cookies.json
      cookie name = monkeycode_ai_session
端点（exe 内字符串逆向）：
      https://monkeycode-ai.com/api/v1/users/wallet
      https://monkeycode-ai.com/api/v1/users/wallet/checkin
"""
import os
import json
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(os.environ["APPDATA"]) / "com.chaitin.baizhi.monkeycode"
HOST = "https://monkeycode-ai.com"


def cookies():
    out = []
    for f in ("monkeycode-cookies.json", "baizhi-cookies.json"):
        p = APP / f
        if not p.exists():
            continue
        for c in json.loads(p.read_text(encoding="utf-8")):
            if c.get("name") and c.get("value"):
                out.append((c["name"], c["value"], c.get("domain", "")))
    return out


def mask(s, ck):
    for n, v, _ in ck:
        s = s.replace(v, f"<{n}>")
    return s


ck = cookies()
print("cookies:", [(n, d) for n, _, d in ck])

# monkeycode-ai.com 域下用 monkeycode_ai_session；baizhi 域的也一并发（服务端可能同源）
for name, val, dom in ck:
    if "monkeycode" not in dom and "baizhi" not in dom:
        continue
    jar = "; ".join(f"{n}={v}" for n, v, _d in ck if "monkeycode" in _d or "baizhi" in _d)
    break

print("cookie header names:", [n for n, _v, _d in ck])


def get(path, extra=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 monkeycode-probe/1.0",
        "Cookie": jar,
    }
    if extra:
        headers.update(extra)
    req = urllib.request.Request(HOST + path, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


for p in ("/api/v1/users/wallet", "/api/v1/users/profile", "/api/v1/users/status"):
    code, body = get(p)
    print(f"\nGET {p} -> HTTP {code}")
    print("   ", mask(body, ck)[:600])
