"""零风险探测 MiniMax OAuth2 token 端点是否可用。

只用无效 refresh_token 发请求，服务端不会作废真实凭据。
目的：确认 https://account.minimax.cn/oauth2/token 是标准 OAuth2 端点。
"""
import json
import urllib.error
import urllib.request

URLS = [
    "https://account.minimax.cn/oauth2/token",
    "https://account.minimax.cn/oauth2/device/code",
]
FORMS = ["json", "form"]

for url in URLS:
    for kind in FORMS:
        body = {
            "grant_type": "refresh_token",
            "client_id": "mcode-public",
            "refresh_token": "PROBE_INVALID_DO_NOT_USE",
        }
        if kind == "json":
            data = json.dumps(body).encode()
            ctype = "application/json"
        else:
            data = urllib.parse.urlencode(body).encode()
            ctype = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": ctype, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                print(f"[{kind}] {url} -> HTTP {r.status}: {r.read().decode('utf-8','replace')[:300]}")
        except urllib.error.HTTPError as e:
            print(f"[{kind}] {url} -> HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}")
        except Exception as e:
            print(f"[{kind}] {url} -> ERR {e}")
    print()
