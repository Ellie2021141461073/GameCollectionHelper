import { NextRequest } from 'next/server';
import { proxyRecommender } from '../_proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get('q')?.trim();
  if (!q) return Response.json({ error: '请输入游戏名称或 AppID' }, { status: 400 });
  return proxyRecommender('/similar', {
    q,
    limit: request.nextUrl.searchParams.get('limit') || '8',
  });
}
