import type { GameDeal } from './types';

type JsonObject = Record<string, unknown>;

export interface SteamMarketCardCandidate {
  name: string;
  listings: number;
  marketUrl: string;
  imageUrl: string;
  foil: boolean;
}

export interface SteamMarketSearch {
  total: number;
  pageSize: number;
  cards: SteamMarketCardCandidate[];
}

export class SteamDataError extends Error {
  status: number;

  constructor(message: string, status = 502) {
    super(message);
    this.name = 'SteamDataError';
    this.status = status;
  }
}

const asObject = (value: unknown): JsonObject =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : {};

const parseUsdAmount = (value: string): number | null => {
  const numeric = value.replace(/,/g, '').replace(/[^\d.]/g, '');
  if (!numeric) return null;
  const amount = Number(numeric);
  return Number.isFinite(amount) && amount > 0 ? Math.round(amount * 100) : null;
};

const decodeHtml = (value: string): string => value
  .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => String.fromCodePoint(parseInt(code, 16)))
  .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number(code)))
  .replace(/&quot;/g, '"')
  .replace(/&apos;/g, "'")
  .replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>')
  .replace(/&amp;/g, '&');

export const normalizeSteamImageUrl=(value:string)=>{
  if(!value)return '';
  try{
    const url=new URL(value);
    if(url.hostname.endsWith('eccdnx.com'))url.hostname='shared.fastly.steamstatic.com';
    return url.toString();
  }catch{
    return value;
  }
};

/** Parse the public Steam Store appdetails response into the app's canonical model. */
export function parseSteamAppDetails(raw: unknown, appid: number): GameDeal {
  const entry = asObject(asObject(raw)[String(appid)]);
  if (entry.success !== true) {
    throw new SteamDataError('Steam 未返回该 AppID，或该游戏在当前商店区域不可用。', 404);
  }

  const data = asObject(entry.data);
  const type = String(data.type || '');
  if (type && type !== 'game') {
    throw new SteamDataError('该 AppID 不是 Steam 游戏，无法按游戏卡牌分析。', 422);
  }

  const title = String(data.name || '').trim();
  if (!title) throw new SteamDataError('Steam 返回的数据缺少游戏名称。', 502);

  const price = asObject(data.price_overview);
  const currency = String(price.currency || 'USD').toUpperCase();
  if (currency !== 'USD') {
    throw new SteamDataError(`Steam 当前返回 ${currency} 价格；本项目配置为美区 USD。`, 422);
  }

  const isFree = data.is_free === true;
  const finalCents = Number(price.final);
  const initialCents = Number(price.initial);
  if (!isFree && (!Number.isFinite(finalCents) || finalCents <= 0)) {
    throw new SteamDataError('Steam 未返回该游戏的美元售价，可能是地区限制或商店数据不可用。', 422);
  }

  const priceCents = isFree ? 0 : Math.round(finalCents);
  const originalCents = isFree
    ? 0
    : Number.isFinite(initialCents) && initialCents > 0
      ? Math.round(initialCents)
      : priceCents;
  const discount = Number.isFinite(Number(price.discount_percent))
    ? Math.max(0, Math.min(100, Math.round(Number(price.discount_percent))))
    : originalCents > priceCents
      ? Math.round((1 - priceCents / originalCents) * 100)
      : 0;
  const imageUrl = normalizeSteamImageUrl(String(data.header_image || '').trim())
    || `https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`;
  const storeUrl = `https://store.steampowered.com/app/${appid}/`;
  const categories: unknown[] = Array.isArray(data.categories) ? data.categories : [];
  const categoryIds = categories.map(category => Number(asObject(category).id));

  return {
    id: `steam-${appid}`,
    appid,
    title,
    priceCents,
    originalCents,
    discount,
    currency: 'USD',
    storeUrl,
    sourceUrl: storeUrl,
    imageUrl,
    source: 'live',
    isBaseGame: true,
    canDropCards: categoryIds.includes(29),
  };
}

/** Normalize and deduplicate ordinary and foil cards from the Community Market search response. */
export function parseSteamMarketSearch(raw: unknown): SteamMarketSearch {
  const data = asObject(raw);
  if (data.success !== true && data.success !== 1) {
    throw new SteamDataError('Steam 市场没有返回有效结果（可能受地区限制或限流）。');
  }

  const total = Number(data.total_count ?? 0);
  const items: unknown[] = Array.isArray(data.results) ? data.results : [];
  const cards = items.map(item => {
    const result = asObject(item);
    const description = asObject(result.asset_description);
    const tags: unknown[] = Array.isArray(description.tags) ? description.tags : [];
    const tagIds = tags.map(tag => String(asObject(tag).internal_name || ''));
    const name = String(result.hash_name || result.name || 'Unknown Card');
    const foil=tagIds.includes('cardborder_1')||/\bfoil\b/i.test(name);
    const iconUrl=String(description.icon_url||'').trim();
    return {
      name,
      listings: Number(result.sell_listings || 0),
      marketUrl: `https://steamcommunity.com/market/listings/753/${encodeURIComponent(name)}`,
      imageUrl:iconUrl?`https://community.fastly.steamstatic.com/economy/image/${iconUrl}/64fx64f`:'',
      foil,
    };
  }).filter(card => card.name !== 'Unknown Card');

  return {
    total,
    pageSize: Math.max(1,Number(data.pagesize||items.length||10)),
    cards: Array.from(new Map(cards.map(card => [card.name, card])).values()),
  };
}

/** Convert Steam's USD priceoverview string into cents without using an exchange rate. */
export function parseSteamUsdOverview(raw: unknown): number | null {
  const data = asObject(raw);
  if (data.success === false) return null;
  const formatted = String(data.lowest_price || data.median_price || '');
  return parseUsdAmount(formatted);
}

/** Parse the Steam Store infinite-search response into paid USD games under the requested price. */
export function parseSteamStoreResults(raw: unknown, maxPriceCents = 2000, limit = 60): GameDeal[] {
  const data = asObject(raw);
  if (data.success !== 1 && data.success !== true) {
    throw new SteamDataError('Steam 商店搜索结果不可用，请稍后重试。');
  }

  const html = String(data.results_html || '');
  const chunks = html.split(/<a href="https:\/\/store\.steampowered\.com\/app\//i).slice(1);
  const found: GameDeal[] = [];
  for (const chunk of chunks) {
    const appid = Number(chunk.match(/^(\d+)/)?.[1]);
    if (!Number.isSafeInteger(appid) || appid < 1) continue;
    const priceMatch = chunk.match(/data-price-final="(\d+)"/);
    if (!priceMatch) continue;
    const priceCents = Number(priceMatch[1]);
    if (!Number.isFinite(priceCents) || priceCents <= 0 || priceCents >= maxPriceCents) continue;

    const titleMatch = chunk.match(/class="title">([\s\S]*?)<\/span>/i);
    const title = decodeHtml(titleMatch?.[1] || '').replace(/<[^>]+>/g, '').trim();
    if (!title) continue;
    const imageMatch = chunk.match(/class="search_capsule"><img src="([^"]+)"/i);
    const discountMatch = chunk.match(/data-discount="(\d+)"/i);
    const discount = discountMatch ? Math.max(0, Math.min(100, Number(discountMatch[1]))) : 0;
    const originalMatch = chunk.match(/class="discount_original_price">([^<]+)<\/div>/i);
    const originalCents = parseUsdAmount(decodeHtml(originalMatch?.[1] || ''))
      || (discount > 0 ? Math.round(priceCents / (1 - discount / 100)) : priceCents);
    const storeUrl = `https://store.steampowered.com/app/${appid}/`;

    found.push({
      id: `steam-${appid}`,
      appid,
      title,
      priceCents,
      originalCents: Math.max(priceCents, originalCents),
      discount,
      currency: 'USD',
      storeUrl,
      sourceUrl: storeUrl,
      imageUrl: normalizeSteamImageUrl(decodeHtml(imageMatch?.[1] || '')),
      source: 'live',
    isBaseGame: true,
    canDropCards: true,
    });
  }

  const unique = Array.from(new Map(
    found
      .sort((a, b) => a.priceCents - b.priceCents || a.title.localeCompare(b.title, 'en-US'))
      .map(game => [game.appid, game])
  ).values());
  return unique.slice(0, limit);
}

/** Parse Steam Store's lightweight search response by exact AppID. */
export function parseSteamStoreSearch(raw: unknown, appid: number): GameDeal | null {
  const data = asObject(raw);
  const items: unknown[] = Array.isArray(data.items) ? data.items : [];
  const item = items.map(asObject).find(candidate =>
    Number(candidate.id) === appid && String(candidate.type || 'app') === 'app'
  );
  if (!item) return null;

  const title = String(item.name || '').trim();
  if (!title) return null;
  const price = asObject(item.price);
  const hasPrice = Object.keys(price).length > 0;
  const currency = String(price.currency || 'USD').toUpperCase();
  if (hasPrice && currency !== 'USD') {
    throw new SteamDataError(`Steam 当前返回 ${currency} 价格；本项目配置为美区 USD。`, 422);
  }

  const finalCents = Number(price.final);
  const initialCents = Number(price.initial);
  const priceCents = hasPrice && Number.isFinite(finalCents) ? Math.max(0, Math.round(finalCents)) : 0;
  const originalCents = hasPrice && Number.isFinite(initialCents) && initialCents > 0
    ? Math.max(priceCents, Math.round(initialCents))
    : priceCents;
  const discount = originalCents > priceCents
    ? Math.round((1 - priceCents / originalCents) * 100)
    : 0;
  const storeUrl = `https://store.steampowered.com/app/${appid}/`;
  const imageUrl = normalizeSteamImageUrl(String(item.tiny_image || '').trim())
    || `https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`;

  return {
    id: `steam-${appid}`,
    appid,
    title,
    priceCents,
    originalCents,
    discount,
    currency: 'USD',
    storeUrl,
    sourceUrl: storeUrl,
    imageUrl,
    source: 'live',
    isBaseGame: true,
  };
}
