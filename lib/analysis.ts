import type { Analysis, GameDeal, MarketCard } from './types';

/** Steam community market estimates in USD minor units (cents).
 * These estimates are NOT an official seller proceeds quotation.
 * Actual fees, regional floors and rounding may differ.
 */
export function estimatedSellerNetCents(grossCents: number): number {
  if (!Number.isFinite(grossCents) || grossCents <= 0) return 0;
  const gross = Math.round(grossCents);
  const steamFee = Math.max(1, Math.floor(gross * 0.05));
  const publisherFee = Math.max(1, Math.floor(gross * 0.10));
  return Math.max(0, gross - steamFee - publisherFee);
}
export function estimateCardValue(cards: MarketCard[], priceCents: number, updatedAt?: string): Analysis {
  if (!cards.length) return {status:'none',cards:[],expectedDrops:0,estimatedNetCents:null,recoveryRate:null,estimatedProfitCents:null,updatedAt,note:'未检索到可掉落的普通卡牌，不能据此判定游戏永不掉卡。'};
  const expectedDrops = Math.floor(cards.length / 2); // conservative approximation
  const averageNet = cards.reduce((sum, card) => sum + card.netCents,0) / cards.length;
  const estimatedNetCents = Math.round(expectedDrops * averageNet);
  const recoveryRate = priceCents > 0 ? Math.round(estimatedNetCents / priceCents * 1000) / 10 : null;
  return {status:'ok',cards,expectedDrops,estimatedNetCents,recoveryRate,estimatedProfitCents:estimatedNetCents - priceCents,updatedAt,note:'按约半套随机掉落、各普通卡等概率和近似手续费计算，仅为估计值。'};
}
export const displayCardName=(name:string)=>name.replace(/^\d+-/,'').replace(/\s*\(Foil\)\s*$/i,'').trim()||name;
export const formatMoney = (cents: number | null | undefined) => cents == null ? '—' : `$${(cents/100).toFixed(2)}`;
export const fmtRate = (n: number | null | undefined) => n == null ? '—' : `${n.toFixed(1)}%`;
export function qualityLabel(analysis?: Analysis): string {
  if(!analysis || analysis.status==='unscanned') return '待分析';
  if(analysis.status==='error') return '查询失败';
  if(analysis.status==='none') return '未查到卡牌';
  if(analysis.status==='partial') return '数据不完整';
  if(analysis.recoveryRate == null) return '无有效数据';
  if(analysis.recoveryRate >= 40) return '高回收率';
  if(analysis.recoveryRate >= 30) return '中回收率';
  return '低回收率';
}
export function qualifies(game: GameDeal, a: Analysis | undefined, minRate: number): boolean {
  return !!a && a.status==='ok' && a.recoveryRate != null && a.recoveryRate >= minRate && game.priceCents>0;
}
