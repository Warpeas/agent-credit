#!/usr/bin/env python3
from pathlib import Path
import shutil

skill_dir = Path(__file__).resolve().parent.parent / "skill"
home = Path.home()
targets = [
    home / "AppData/Roaming/com.chaitin.baizhi.monkeycode/ohmyagent/skills/agent-credit/SKILL.md",
    home / ".agents/skills/agent-credit/SKILL.md",
    home / ".claude/skills/agent-credit/SKILL.md",
    home / "MonkeyCode/.ohmyagent/skills/agent-credit/SKILL.md",
]
for dest in targets:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_dir / "SKILL.md", dest)
    print("installed", dest)

# Loomy 技能目录带实例 hash（C:/Users/Public/Loomy/<hash>/opencode/skills/），
# hash 可能随版本变化，所以逐个实例 glob 安装 loomy-taskbox-worker
for base in Path("C:/Users/Public/Loomy").glob("*/opencode/skills"):
    dest = base / "loomy-taskbox-worker" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_dir / "loomy-taskbox-worker" / "SKILL.md", dest)
    print("installed", dest)
