// Trae Credit Dump — agent-credit 项目的客户端内数据采集器。
//
// 合规性（research/SAFETY.md）：
//   - 只调用客户端自己注册的官方命令（workbench.action.icubeGet*），
//     数据由客户端服务层直接返回，等同于「让客户端自己说话」（允许路线 2）。
//   - 不读取/不传输任何凭据：这里没有 token，命令内部怎么走与我们无关。
//   - 不注入、不改客户端、不开调试口；唯一的写动作是往项目 logs/ 落一个 JSON。
//   - 不新增服务端压力：这些 getter 读的是客户端会话内已拉取/缓存的数据。
//
// 产出：logs/trae_credit_detail.json
//   fetched_at  ISO 时间
//   results     每个命令 { ok, data | error }
//
// 触发时机（scripts/trae_credit_sync.ps1 依赖前两个）：
//   1. IDE 窗口启动 15s 后（startup）
//   2. 窗口获得焦点时，距上次 dump ≥5min（focus）
//   3. 每 30min 兜底（interval）
const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");

const REPO =
  process.env.AGENT_CREDIT_REPO ||
  path.join(os.homedir(), "Documents", "Warpeas", "agent-credit");
const OUT_FILE = path.join(REPO, "logs", "trae_credit_detail.json");

const FOCUS_THROTTLE_MS = 5 * 60 * 1000;
const INTERVAL_MS = 30 * 60 * 1000;

// 只读 getter 清单。icubeGetCreditsUsageInfo / icubeGetFastRequestQuotaInfo
// 只在完整 IDE bundle 注册，solo-lite 没有 —— 单个失败不影响其它项。
const COMMANDS = [
  ["creditsUsage", "workbench.action.icubeGetCreditsUsageInfo"],
  ["fastRequestQuota", "workbench.action.icubeGetFastRequestQuotaInfo"],
  ["entitlementInfo", "workbench.action.icubeGetEntitlementInfo"],
  ["checkinSnapshot", "workbench.action.icubeGetCheckinCreditsSnapshot"],
  ["accountManagement", "workbench.action.icubeGetIdeAccountManagementSnapshot"],
];

let lastDumpAt = 0;

function safeStringify(value) {
  const seen = new WeakSet();
  return JSON.stringify(
    value,
    (k, v) => {
      if (typeof v === "object" && v !== null) {
        if (seen.has(v)) return "[circular]";
        seen.add(v);
      }
      if (typeof v === "function") return undefined;
      return v;
    },
    2
  );
}

async function collect() {
  const out = { fetched_at: new Date().toISOString(), results: {} };
  for (const [key, id] of COMMANDS) {
    try {
      const data = await vscode.commands.executeCommand(id);
      out.results[key] = { ok: true, data: data === undefined ? null : data };
    } catch (e) {
      out.results[key] = { ok: false, error: String((e && e.message) || e) };
    }
  }
  return out;
}

async function dump(reason) {
  try {
    const payload = await collect();
    payload.reason = reason;
    fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
    fs.writeFileSync(OUT_FILE, safeStringify(payload), "utf8");
    lastDumpAt = Date.now();
    console.log(`[trae-credit-dump] written (${reason}): ${OUT_FILE}`);
    return true;
  } catch (e) {
    console.error(`[trae-credit-dump] failed (${reason}):`, e);
    return false;
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("agentCredit.dumpTraeCredit", async () => {
      const ok = await dump("manual");
      vscode.window.showInformationMessage(
        ok ? "Agent Credit: 已导出 trae_credit_detail.json" : "Agent Credit: 导出失败，见控制台"
      );
    })
  );
  // 1. 启动后等客户端服务就绪再导一次（每日首次开 IDE 窗口即自动留档）。
  const timer = setTimeout(() => {
    dump("startup").catch(() => {});
  }, 15000);
  context.subscriptions.push({ dispose: () => clearTimeout(timer) });
  // 2. 聚焦触发（节流）：sync 脚本把 IDE 窗口拉到前台后这里出新鲜 dump。
  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((e) => {
      if (!e.focused) return;
      if (Date.now() - lastDumpAt < FOCUS_THROTTLE_MS) return;
      dump("focus").catch(() => {});
    })
  );
  // 3. 长开兜底。
  const iv = setInterval(() => {
    dump("interval").catch(() => {});
  }, INTERVAL_MS);
  context.subscriptions.push({ dispose: () => clearInterval(iv) });
}

function deactivate() {}

module.exports = { activate, deactivate };
