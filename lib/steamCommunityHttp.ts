import { execFile } from 'node:child_process';
import { fetchJson } from './http';

export class SteamCommunityRateLimitError extends Error {
  constructor(message='Steam Community 请求受到限流') {
    super(message);
    this.name='SteamCommunityRateLimitError';
  }
}

const POWERSHELL_SCRIPT = [
  '[Console]::OutputEncoding=[Text.Encoding]::UTF8',
  '$uri=[Environment]::GetEnvironmentVariable("STEAM_COMMUNITY_URL")',
  '$content=(Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 20 -Headers @{"User-Agent"="CardScout-portfolio/0.1 (read-only market research)";"Accept"="application/json";"Accept-Language"="en-US,en;q=0.9"}).Content',
  '[Console]::Out.Write($content)',
].join('; ');

const encodedScript = Buffer.from(POWERSHELL_SCRIPT, 'utf16le').toString('base64');

function fetchWithPowerShell(url: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', encodedScript], {
      env: { ...process.env, STEAM_COMMUNITY_URL: url },
      maxBuffer: 20 * 1024 * 1024,
      timeout: 30_000,
      windowsHide: true,
    }, (error, stdout, stderr) => {
      if (error) {
        const detail=`${stderr} ${error.message}`;
        if (/\(429\)|too many requests/i.test(detail)){
          reject(new SteamCommunityRateLimitError('Steam 市场搜索触发 429 限流'));
          return;
        }
        reject(new Error(`PowerShell 读取 Steam Community 失败：${stderr.trim() || error.message}`));
        return;
      }
      const body = stdout.replace(/^\uFEFF/, '').trim();
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new SteamCommunityRateLimitError('Steam Community 返回了限流或验证页面'));
      }
    });
  });
}

/**
 * Steam Community is blocked for direct Node sockets in some Windows setups.
 * Prefer the system PowerShell network stack on Windows and keep native fetch elsewhere.
 */
export async function fetchSteamCommunityJson(url: string, timeoutMs = 16_000): Promise<unknown> {
  const transport = process.env.STEAM_COMMUNITY_TRANSPORT?.toLowerCase();
  if (transport === 'direct') {
    return fetchJson(url, {
      cache: 'no-store',
      headers: { 'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9' },
    }, timeoutMs);
  }
  if (process.platform === 'win32') {
    return fetchWithPowerShell(url);
  }
  return fetchJson(url, {
    cache: 'no-store',
    headers: { 'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9' },
  }, timeoutMs);
}
