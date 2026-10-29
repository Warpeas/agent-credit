"""只读检查 Trae 本地缓存里有没有已落盘的积分/权益数据（不碰加密登录态）。

查三处：
1. User/globalStorage/state.vscdb（sqlite 明文全局状态）中含 credit/entitle 的 key
2. Local Storage leveldb 的 .log/.ldb 里是否含 creditsUsage / entitlement 明文
3. ModularData 目录概览
"""
import re
import sqlite3
from pathlib import Path

ROAM = Path(r"C:\Users\Hunter\AppData\Roaming\Trae CN")
KW = re.compile(rb"credit|entitle|expire|bonus", re.I)


def scan_vscdb():
    db = ROAM / "User" / "globalStorage" / "state.vscdb"
    print(f"===== {db} =====")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print("tables:", tables)
        for t in tables:
            try:
                rows = cur.execute(f"SELECT key, length(value) FROM [{t}]").fetchall()
            except sqlite3.Error as e:
                print(f"  [{t}] read err: {e}")
                continue
            print(f"  [{t}] {len(rows)} rows")
            for k, vlen in rows:
                if re.search(r"credit|entitle|expire|bonus|usage", str(k), re.I):
                    print(f"    KEY {k!r} (value {vlen} bytes)")
        con.close()
    except sqlite3.Error as e:
        print(f"  open err: {e}")


def scan_leveldb():
    ld = ROAM / "Local Storage" / "leveldb"
    print(f"\n===== {ld} =====")
    for f in sorted(ld.glob("*.l*")):
        try:
            data = f.read_bytes()
        except OSError:
            continue
        hits = set()
        for m in KW.finditer(data):
            frag = data[max(0, m.start() - 40): m.end() + 60]
            frag = re.sub(rb"[^\x20-\x7e]", b".", frag)
            hits.add(frag.decode("ascii", "replace"))
        if hits:
            print(f"  {f.name}: {len(hits)} frags")
            for h in sorted(hits)[:12]:
                print("   ", h)


def scan_modular():
    md = ROAM / "ModularData"
    print(f"\n===== {md} =====")
    if not md.exists():
        print("  (missing)")
        return
    for p in sorted(md.rglob("*")):
        if p.is_file() and p.stat().st_size < 5_000_000:
            rel = p.relative_to(md)
            if re.search(r"credit|usage|entitle|user|account|profile", str(rel), re.I):
                print("  ", rel, p.stat().st_size)


if __name__ == "__main__":
    scan_vscdb()
    scan_leveldb()
    scan_modular()
