#!/usr/bin/env python3
from pathlib import Path
import shutil

src = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
home = Path.home()
targets = [
    home / "AppData/Roaming/com.chaitin.baizhi.monkeycode/ohmyagent/skills/agent-credit/SKILL.md",
    home / ".agents/skills/agent-credit/SKILL.md",
    home / ".claude/skills/agent-credit/SKILL.md",
    home / "MonkeyCode/.ohmyagent/skills/agent-credit/SKILL.md",
]
for dest in targets:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print("installed", dest)
