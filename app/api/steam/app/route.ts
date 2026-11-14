import { NextRequest, NextResponse } from 'next/server';
import { safeError } from '@/lib/http';
import { fetchSteamApp } from '@/lib/steam';
import { SteamDataError } from '@/lib/steamParse';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const appid = Number(req.nextUrl.searchParams.get('appid'));
  if (!Number.isSafeInteger(appid) || appid < 1 || appid > 1e10) {
    return NextResponse.json({ error: '无效的 Steam AppID' }, { status: 400 });
  }

  try {
    const deal = await fetchSteamApp(appid);
    return NextResponse.json({
      configured: true,
      deal,
      source: 'Steam Store (US, USD)',
      fetchedAt: new Date().toISOString(),
    }, {
      headers: { 'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=300' },
    });
  } catch (error) {
    const status = error instanceof SteamDataError ? error.status : 502;
    return NextResponse.json({ error: safeError(error) }, { status });
  }
}
