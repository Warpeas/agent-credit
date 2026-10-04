"""一次性探测：不管 slot 是否 empty，直接 POST 签到动作，看服务端真实反应。

幂等：AlreadyClaimed(51104) 会被服务端拒绝，不存在重复领取风险。
token 不打印。
"""
import json, sqlite3, urllib.request, urllib.error
from pathlib import Path

DB = Path(r"C:/Users/Hunter/AppData/Roaming/LobsterAI/lobsterai.sqlite")
HOST = "https://lobsterai-server.youdao.com"

con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
row = con.execute("SELECT value FROM kv WHERE key='auth_tokens'").fetchone()
con.close()
tok = json.loads(row[0]).get("accessToken")
print("token len =", len(tok))

def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HOST + path, data=data, method=method, headers={
        "Authorization": "Bearer " + tok,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "lobster-probe/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

for p in [
    "/api/client-activities/daily_check_in/context?configRevision=0",
]:
    s, t = call(p)
    print(f"GET  {p}\n  -> {s} {t[:300]}")

s, t = call("/api/client-activities/daily_check_in/actions/check_in", "POST", {})
print(f"POST /api/client-activities/daily_check_in/actions/check_in\n  -> {s} {t[:600]}")
