import { execFile } from "child_process";
import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const PREFERRED_SERVER_KEYS = ["sleeper-agent-mcp", "sleeper-overseer-mcp"] as const;
const SLEEPER_MODULE_MARKER = "sleeper_agent_mcp.server";
const REQUIRED_ENV_KEYS = [] as const;
const SOLARI_ENV_KEYS = ["SOLARI_API_KEY"] as const;

export type McpReloadPreview = {
  config_path: string;
  server_key: string | null;
  applied_keys: string[];
  missing_required: string[];
  cursor_api_key_set: boolean;
  solari_api_key_set: boolean;
  backend: string;
  error: string | null;
};

export type McpReloadResponse = McpReloadPreview & {
  status: "OK" | "WARN" | "ERROR";
  reload_request_path: string;
  processes_stopped: number;
  message: string;
};

function globalMcpConfigPath(): string {
  return path.join(os.homedir(), ".cursor", "mcp.json");
}

function reloadRequestPath(): string {
  return path.join(os.homedir(), ".sleeper_agent", "reload_mcp.request");
}

function reloadStatusPath(): string {
  return path.join(os.homedir(), ".sleeper_agent", "mcp_reload_status.json");
}

function findSleeperServer(
  servers: Record<string, unknown>,
): [string | null, Record<string, unknown> | null] {
  for (const key of PREFERRED_SERVER_KEYS) {
    if (key in servers && typeof servers[key] === "object" && servers[key]) {
      return [key, servers[key] as Record<string, unknown>];
    }
  }

  for (const [key, value] of Object.entries(servers)) {
    if (!value || typeof value !== "object") continue;
    const args = (value as { args?: unknown[] }).args ?? [];
    const joined = args.map(String).join(" ");
    if (joined.includes(SLEEPER_MODULE_MARKER)) {
      return [key, value as Record<string, unknown>];
    }
  }

  return [null, null];
}

function missingRequiredKeys(env: Record<string, string>): string[] {
  const missing: string[] = [];
  for (const key of REQUIRED_ENV_KEYS) {
    if (!env[key]?.trim()) missing.push(key);
  }
  const backend = env.SLEEPER_BACKEND?.trim().toLowerCase() ?? "docker";
  if (backend === "solari") {
    for (const key of SOLARI_ENV_KEYS) {
      if (!env[key]?.trim()) missing.push(key);
    }
  }
  return missing;
}

export async function previewGlobalMcpEnv(): Promise<McpReloadPreview> {
  const configPath = globalMcpConfigPath();
  if (!(await fileExists(configPath))) {
    return {
      config_path: configPath,
      server_key: null,
      applied_keys: [],
      missing_required: [...REQUIRED_ENV_KEYS],
      cursor_api_key_set: false,
      solari_api_key_set: false,
      backend: "docker",
      error: `Global MCP config not found: ${configPath}`,
    };
  }

  const raw = await fs.readFile(configPath, "utf8");
  const parsed = JSON.parse(raw) as { mcpServers?: Record<string, unknown> };
  const servers = parsed.mcpServers ?? {};
  const [serverKey, serverConfig] = findSleeperServer(servers);

  if (!serverConfig) {
    return {
      config_path: configPath,
      server_key: null,
      applied_keys: [],
      missing_required: [...REQUIRED_ENV_KEYS],
      cursor_api_key_set: false,
      solari_api_key_set: false,
      backend: "docker",
      error: "No sleeper-agent-mcp entry found in global mcp.json",
    };
  }

  const envBlock = (serverConfig.env ?? {}) as Record<string, unknown>;
  const env = Object.fromEntries(
    Object.entries(envBlock).map(([key, value]) => [key, String(value)]),
  );
  const missing = missingRequiredKeys(env);

  return {
    config_path: configPath,
    server_key: serverKey,
    applied_keys: Object.keys(env).sort(),
    missing_required: missing,
    cursor_api_key_set: Boolean(env.CURSOR_API_KEY?.trim()),
    solari_api_key_set: Boolean(env.SOLARI_API_KEY?.trim()),
    backend: env.SLEEPER_BACKEND?.trim() || "docker",
    error: missing.length
      ? `Missing required env keys: ${missing.join(", ")}`
      : null,
  };
}

async function fileExists(target: string): Promise<boolean> {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

async function writeReloadRequest(reason: string): Promise<string> {
  const requestPath = reloadRequestPath();
  await fs.mkdir(path.dirname(requestPath), { recursive: true });
  await fs.writeFile(
    requestPath,
    JSON.stringify(
      {
        requested_at: new Date().toISOString(),
        reason,
      },
      null,
      2,
    ),
    "utf8",
  );
  return requestPath;
}

async function writeReloadStatus(preview: McpReloadPreview): Promise<void> {
  const statusPath = reloadStatusPath();
  await fs.mkdir(path.dirname(statusPath), { recursive: true });
  await fs.writeFile(
    statusPath,
    JSON.stringify(
      {
        ...preview,
        status: preview.error ? "ERROR" : preview.missing_required.length ? "WARN" : "RELOADED",
        reloaded_at: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf8",
  );
}

async function stopSleeperMcpProcesses(): Promise<number> {
  if (process.platform === "win32") {
    const script = [
      "$procs = Get-CimInstance Win32_Process | Where-Object {",
      "  ($_.Name -eq 'python.exe' -or $_.Name -eq 'python3.12.exe') -and",
      "  $_.CommandLine -match 'sleeper_agent_mcp'",
      "};",
      "$procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };",
      "Write-Output ($procs | Measure-Object).Count",
    ].join(" ");
    const { stdout } = await execFileAsync("powershell", [
      "-NoProfile",
      "-Command",
      script,
    ]);
    return Number.parseInt(stdout.trim(), 10) || 0;
  }

  const { stdout } = await execFileAsync("bash", [
    "-lc",
    "pids=$(pgrep -f sleeper_agent_mcp.server || true); if [ -n \"$pids\" ]; then kill $pids 2>/dev/null || true; echo \"$pids\" | wc -w; else echo 0; fi",
  ]);
  return Number.parseInt(stdout.trim(), 10) || 0;
}

export async function reloadMcpServer(
  mode: "reload" | "restart" = "restart",
): Promise<McpReloadResponse> {
  const preview = await previewGlobalMcpEnv();
  const requestPath = await writeReloadRequest(`dashboard:${mode}`);
  await writeReloadStatus(preview);

  let processesStopped = 0;
  if (mode === "restart") {
    processesStopped = await stopSleeperMcpProcesses();
    try {
      const configPath = globalMcpConfigPath();
      const raw = await fs.readFile(configPath, "utf8");
      await fs.writeFile(configPath, raw, "utf8");
    } catch {
      // Best-effort nudge for Cursor to notice config changes.
    }
  }

  const status: McpReloadResponse["status"] = preview.error
    ? "ERROR"
    : preview.missing_required.length
      ? "WARN"
      : "OK";

  const message =
    mode === "restart"
      ? processesStopped > 0
        ? `Stopped ${processesStopped} MCP process(es). Cursor should respawn the server; the next health poll applies env from ~/.cursor/mcp.json.`
        : "Queued env reload. If MCP is connected, call get_queue_status once to apply it. Otherwise restart MCP from Cursor settings."
      : "Queued env reload from ~/.cursor/mcp.json. The running MCP server applies it on the next get_queue_status poll.";

  return {
    status,
    reload_request_path: requestPath,
    processes_stopped: processesStopped,
    message,
    ...preview,
  };
}
