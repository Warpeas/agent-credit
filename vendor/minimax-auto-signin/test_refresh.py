"""MiniMax OAuth2 refresh_token 实机验证（一次）。

端点：POST https://account.minimax.cn/oauth2/token
凭据：~/.minimax/auth/prod/cn/mcode-public/auth.json（明文 accessToken + refreshToken）

轮换假设：旧 refresh token 刷新后作废，所以成功后必须写回 auth.json，
否则客户端下次刷新会失败（掉登录）。已备份 auth.json.bak.20261002。

输出：token 一律 <redacted>。
"""
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH = Path.home() / ".minimax" / "auth" / "prod" / "cn" / "mcode-public" / "auth.json"
TOKEN_URL = "https://account.minimax.cn/oauth2/token"
CLIENT_ID = "mcode-public"


def load():
    d = json.loads(AUTH.read_text(encoding="utf-8"))
    for k, v in (d.get("records") or {}).items():
        if "oauth" in k and isinstance(v, dict):
            return d, k, v
    raise SystemExit("no oauth record")


def mask(s, *secrets):
    for x in secrets:
        if x:
            s = s.replace(x, "<redacted>")
    return s


d, key, rec = load()
rt = rec["refreshToken"]
old_at = rec["accessToken"]
print("before: gen=%s left_h=%.3f" % (
    rec.get("generation"),
    (int(rec.get("expiresAtMs") or 0) - int(time.time() * 1000)) / 3600000))

body = urllib.parse.urlencode({
    "grant_type": "refresh_token",
    "client_id": CLIENT_ID,
    "refresh_token": rt,
}).encode()
req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        code, raw = r.status, r.read().decode("utf-8", "replace")
except urllib.error.HTTPError as e:
    code, raw = e.code, e.read().decode("utf-8", "replace")
except Exception as e:
    code, raw = -1, str(e)

print("HTTP", code)
print(mask(raw, rt, old_at)[:700])
if code != 200:
    raise SystemExit("refresh failed, auth.json untouched")

j = json.loads(raw)
new_at = j.get("access_token")
new_rt = j.get("refresh_token") or rt
exp_in = int(j.get("expires_in") or 0)
if not new_at:
    raise SystemExit("no access_token in response, auth.json untouched")

# 写回：保留原有 schema，只更新凭据字段
now_ms = int(time.time() * 1000)
rec["accessToken"] = new_at
rec["refreshToken"] = new_rt
if j.get("token_type"):
    rec["tokenType"] = j["token_type"].capitalize() if j["token_type"].lower() == "bearer" else j["token_type"]
if exp_in:
    rec["expiresAtMs"] = now_ms + exp_in * 1000
rec["generation"] = int(rec.get("generation") or 0) + 1

tmp = AUTH.with_suffix(".json.tmp")
tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.move(str(tmp), str(AUTH))

print("written back. new exp_in=%ss  gen=%s" % (exp_in, rec["generation"]))
print("verify: 新 accessToken 长度=%d  refreshToken 长度=%d" % (len(new_at), len(new_rt)))
