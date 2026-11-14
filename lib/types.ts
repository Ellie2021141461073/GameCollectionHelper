export type SourceMode = 'live' | 'manual' | 'catalog';
export interface GameDeal {
  id: string;
  appid: number;
  title: string;
  priceCents: number;
  originalCents: number;
  discount: number;
  currency: 'USD';
  storeUrl: string;
  sourceUrl?: string;
  imageUrl?: string;
  source: SourceMode;
  isBaseGame?: boolean;
  canDropCards?: boolean;
}
export interface MarketCard {
  name: string;
  grossCents: number;
  netCents: number;
  listings: number;
  marketUrl: string;
  imageUrl?: string;
}
export type CardStatus = 'unscanned'|'ok'|'none'|'partial'|'error';
export interface Analysis {
  status: CardStatus;
  cards: MarketCard[];
  expectedDrops: number;
  estimatedNetCents: number | null;
  recoveryRate: number | null;
  estimatedProfitCents: number | null;
  updatedAt?: string;
  note?: string;
}
export type ScanState = Record<string, Analysis>;
export interface Filters {
  query: string;
  maxPrice: number;
  minDiscount: number;
  minRecovery: number;
  sort: 'recovery' | 'price' | 'discount';
  onlyQualified: boolean;
}
