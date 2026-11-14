import type { Analysis, Filters, GameDeal } from './types';

export type AnalysisSummary = Partial<Pick<Analysis,'status'|'recoveryRate'>>;

export interface DealPageQuery {
  page: number;
  pageSize: number;
  filters: Filters;
  analyses: Record<string,AnalysisSummary>;
}

export function paginateDeals(games:GameDeal[],query:DealPageQuery){
  const filters=query.filters;
  const q=filters.query.trim().toLowerCase();
  const minRecovery=filters.minRecovery;
  const onlyAnalyzed=filters.onlyQualified;
  const filtered=games.filter(game=>{
    if(game.priceCents>filters.maxPrice*100||game.discount<filters.minDiscount)return false;
    if(q&&!game.title.toLowerCase().includes(q)&&!String(game.appid).includes(q))return false;
    if(onlyAnalyzed){
      const analysis=query.analyses[game.id]||query.analyses[String(game.appid)];
      if(!analysis||analysis.status!=='ok')return false;
    }
    return true;
  }).sort((a,b)=>{
    if(filters.sort==='discount')return b.discount-a.discount||a.priceCents-b.priceCents;
    if(filters.sort==='recovery'){
      const ar=query.analyses[a.id]?.recoveryRate??query.analyses[String(a.appid)]?.recoveryRate??-1;
      const br=query.analyses[b.id]?.recoveryRate??query.analyses[String(b.appid)]?.recoveryRate??-1;
      return br-ar||a.priceCents-b.priceCents;
    }
    return a.priceCents-b.priceCents||a.title.localeCompare(b.title,'en-US');
  });

  const totalItems=filtered.length;
  const totalPages=Math.max(1,Math.ceil(totalItems/query.pageSize));
  const page=Math.max(1,Math.min(totalPages,Math.trunc(query.page)));
  const offset=(page-1)*query.pageSize;
  const analyzedRates=filtered
    .map(game=>query.analyses[game.id]||query.analyses[String(game.appid)])
    .filter((analysis):analysis is AnalysisSummary=>analysis?.status==='ok'&&analysis.recoveryRate!=null)
    .map(analysis=>analysis.recoveryRate as number);
  const qualified=filtered.filter(game=>{
    const analysis=query.analyses[game.id]||query.analyses[String(game.appid)];
    return analysis?.status==='ok'&&analysis.recoveryRate!=null&&analysis.recoveryRate>=minRecovery;
  }).length;
  return {
    games:filtered.slice(offset,offset+query.pageSize),
    page,
    pageSize:query.pageSize,
    totalItems,
    totalPages,
    hasPrevious:page>1,
    hasNext:page<totalPages,
    stats:{
      analyzed:analyzedRates.length,
      qualified,
      averageRecovery:analyzedRates.length
        ? analyzedRates.reduce((sum,rate)=>sum+rate,0)/analyzedRates.length
        : null,
    },
  };
}
