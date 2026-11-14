import { estimatedSellerNetCents, estimateCardValue } from './analysis';
import { fetchJson } from './http';
import { fetchSteamCommunityJson, SteamCommunityRateLimitError } from './steamCommunityHttp';
import { parseSteamAppDetails, parseSteamMarketSearch, parseSteamStoreSearch, parseSteamUsdOverview, type SteamMarketCardCandidate } from './steamParse';
import type { Analysis, GameDeal, MarketCard } from './types';

/** Fetch real Steam Store metadata and the current US store/USD price. No API key is required. */
export async function fetchSteamApp(appid: number): Promise<GameDeal> {
  const searchUrl = new URL('https://store.steampowered.com/api/storesearch/');
  searchUrl.searchParams.set('term', String(appid));
  searchUrl.searchParams.set('cc', 'us');
  searchUrl.searchParams.set('l', 'en');
  try {
    const searchRaw = await fetchJson(searchUrl.toString(), {
      cache: 'no-store',
      headers: { 'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9' },
    }, 9000);
    const searchDeal = parseSteamStoreSearch(searchRaw, appid);
    if (searchDeal) return searchDeal;
  } catch {
    // Fall back to the full appdetails endpoint when the lightweight endpoint is unavailable.
  }

  const url = new URL('https://store.steampowered.com/api/appdetails');
  url.searchParams.set('appids', String(appid));
  url.searchParams.set('cc', 'us');
  url.searchParams.set('l', 'en');
  const raw = await fetchJson(url.toString(), {
    cache: 'no-store',
    headers: { 'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9' },
  }, 15000);
  return parseSteamAppDetails(raw, appid);
}

const MIN_MARKET_INTERVAL_MS = 3100;
const MIN_PRICE_INTERVAL_MS = 3100;
let lastMarketRequestAt = 0;
let marketQueue: Promise<void> = Promise.resolve();
let lastPriceRequestAt = 0;
let priceQueue: Promise<void> = Promise.resolve();

function throttleMarket<T>(job: () => Promise<T>): Promise<T> {
  const done = marketQueue.then(async () => {
    const wait = Math.max(0, MIN_MARKET_INTERVAL_MS - (Date.now() - lastMarketRequestAt));
    if (wait) await new Promise(resolve => setTimeout(resolve, wait));
    lastMarketRequestAt = Date.now();
    return job();
  });
  marketQueue = done.then(() => undefined, () => undefined);
  return done;
}

function throttlePrice<T>(job: () => Promise<T>): Promise<T> {
  const done=priceQueue.then(async()=>{
    const wait=Math.max(0,MIN_PRICE_INTERVAL_MS-(Date.now()-lastPriceRequestAt));
    if(wait)await new Promise(resolve=>setTimeout(resolve,wait));
    lastPriceRequestAt=Date.now();
    return job();
  });
  priceQueue=done.then(()=>undefined,()=>undefined);
  return done;
}

/**
 * Fetch real buy-order card prices from Steam Community Market.
 * Valve does not provide a stable, documented public API for this endpoint.
 */
export async function fetchSteamMarketCards(appid: number, priceCents: number): Promise<Analysis> {
  const fetchPage=async(start:number)=>{
    const params=new URLSearchParams({
      appid:'753',
      norender:'1',
      start:String(start),
      count:'100',
      'category_753_Game[]':`tag_app_${appid}`,
      'category_753_item_class[]':'tag_item_class_2',
      country:'US',
      currency:'1',
    });
    const retryDelays=[0,10000,20000,30000];
    let lastError:unknown;
    for(const delayMs of retryDelays){
      if(delayMs)await new Promise(resolve=>setTimeout(resolve,delayMs));
      try{
        const raw=await throttleMarket(()=>fetchSteamCommunityJson(
          `https://steamcommunity.com/market/search/render/?${params}`,
          16000,
        ));
        return parseSteamMarketSearch(raw);
      }catch(error){
        lastError=error;
        if(!(error instanceof SteamCommunityRateLimitError)&&
          !/429|too many requests|非 JSON|验证页面/i.test(String((error as Error)?.message||error))){
          throw error;
        }
      }
    }
    throw new SteamCommunityRateLimitError(
      'Steam 卡牌搜索持续限流（429）。请停止重复点击，等待 5–10 分钟后重试。',
    );
  };

  const firstPage=await fetchPage(0);
  const cardCandidates=new Map(firstPage.cards.filter(card=>!card.foil).map(card=>[card.name,card]));
  const total=firstPage.total;
  const pageSize=firstPage.pageSize;
  let fetchedItems=firstPage.cards.length;
  let catalogComplete=fetchedItems>=total;
  for(let start=pageSize,page=1;!catalogComplete&&page<30;start+=pageSize,page++){
    const nextPage=await fetchPage(start);
    for(const card of nextPage.cards){
      if(!card.foil&&!cardCandidates.has(card.name)){
        cardCandidates.set(card.name,card);
      }
    }
    fetchedItems+=nextPage.cards.length;
    catalogComplete=fetchedItems>=total;
    if(nextPage.cards.length===0)break;
  }

  const cards: MarketCard[] = [];
  let priceFailures=0;
  const failedCards:SteamMarketCardCandidate[]=[];
  const loadPrice=async(card:SteamMarketCardCandidate)=>{
    const priceEndpoint = new URL('https://steamcommunity.com/market/priceoverview/');
    priceEndpoint.searchParams.set('appid', '753');
    priceEndpoint.searchParams.set('currency', '1');
    priceEndpoint.searchParams.set('market_hash_name', card.name);
    try {
      const priceRaw = await throttlePrice(() => fetchSteamCommunityJson(priceEndpoint.toString(), 12000));
      const grossCents = parseSteamUsdOverview(priceRaw);
      if (grossCents == null) {
        return false;
      }
      cards.push({
        name:card.name,
        listings:card.listings,
        marketUrl:card.marketUrl,
        imageUrl:card.imageUrl,
        grossCents,
        netCents: estimatedSellerNetCents(grossCents),
      });
      return true;
    } catch {
      return false;
    }
  };
  for(const card of cardCandidates.values()){
    if(!await loadPrice(card))failedCards.push(card);
  }
  if(failedCards.length){
    await new Promise(resolve=>setTimeout(resolve,5000));
    for(const card of failedCards){
      if(!await loadPrice(card))priceFailures++;
    }
  }
  if (cardCandidates.size>0&&cards.length===0) {
    throw new Error('已找到卡牌，但未能获取 Steam 社区市场美元报价');
  }
  const result = estimateCardValue(cards, priceCents, new Date().toISOString());
  if(total===0){
    result.note = '此游戏的普通卡牌搜索结果为空；不等于确认没有卡牌功能。';
  }else if(!catalogComplete){
    result.status='partial';
    result.note=`Steam 市场列出 ${total} 个卡牌条目，本次获取 ${cardCandidates.size} 个；未完整分页时结果按部分数据计算。`;
  }else if(priceFailures>0){
    result.note = `已获取 ${cards.length} 张卡牌美元报价，${priceFailures} 张因市场限流或数据缺失被跳过。`;
  }
  return result;
}
