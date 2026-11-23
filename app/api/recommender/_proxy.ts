import { NextResponse } from 'next/server';

const BASE_URL = (process.env.RECOMMENDER_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function proxyRecommender(path: string, params?: Record<string, string>) {
  const url = new URL(`${BASE_URL}${path}`);
  for (const [key, value] of Object.entries(params || {})) url.searchParams.set(key, value);

  try {
    const response = await fetch(url, {
      cache: 'no-store',
      // The first /search after a restart has to load BGE-M3 into the device and
      // explain every hit, which can exceed 35 s. A short timeout surfaced that
      // as a misleading 503 "service unavailable" even though the API answered.
      signal: AbortSignal.timeout(120_000),
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({
      error: '推荐服务不可用，请确认 8000 端口的 Python 服务已经启动。',
      detail: message,
    }, { status: 503 });
  }
}
