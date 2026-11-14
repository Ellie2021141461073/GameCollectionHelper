import { NextRequest, NextResponse } from 'next/server';
import { safeError } from '@/lib/http';
import { paginateDeals, type DealPageQuery } from '@/lib/dealPagination';
import { getCsvGameCatalog } from '@/lib/csvCatalog';
import type { Analysis, Filters } from '@/lib/types';

export const runtime='nodejs';
export const dynamic='force-dynamic';

const MAX_PRICE_USD = 70;
const DEFAULT_MAX_PRICE_USD = 10;
const DEFAULT_PAGE_SIZE = 8;
const MAX_PAGE_SIZE = 20;

const object=(value:unknown):Record<string,unknown> =>
  typeof value==='object'&&value!==null&&!Array.isArray(value)
    ? value as Record<string,unknown>
    : {};

const clamp=(value:unknown,min:number,max:number,fallback:number)=>{
  const number=Number(value);
  return Number.isFinite(number)?Math.max(min,Math.min(max,number)):fallback;
};

function readQuery(input:Record<string,unknown>):DealPageQuery{
  const filters=object(input.filters);
  const analyses=object(input.analyses);
  return {
    page:clamp(input.page,1,Number.MAX_SAFE_INTEGER,1),
    pageSize:Math.trunc(clamp(input.pageSize,1,MAX_PAGE_SIZE,DEFAULT_PAGE_SIZE)),
    filters:{
      query:String(filters.query||'').slice(0,100),
      maxPrice:clamp(filters.maxPrice,0,MAX_PRICE_USD,DEFAULT_MAX_PRICE_USD),
      minDiscount:clamp(filters.minDiscount,0,100,0),
      minRecovery:clamp(filters.minRecovery,0,100,0),
      sort:['price','discount','recovery'].includes(String(filters.sort))
        ? String(filters.sort) as Filters['sort']
        : 'price',
      onlyQualified:filters.onlyQualified===true,
    },
    analyses:Object.fromEntries(Object.entries(analyses).map(([id,value])=>{
      const summary=object(value);
      const status=['unscanned','ok','none','partial','error'].includes(String(summary.status))
        ? String(summary.status) as Analysis['status']
        : undefined;
      return [id,{status,recoveryRate:summary.recoveryRate==null?null:Number(summary.recoveryRate)}];
    })),
  };
}

async function paginate(query:DealPageQuery){
  try {
    const index=await getCsvGameCatalog();
    const result=paginateDeals(index.games,query);
    return NextResponse.json({
      configured:true,
      ...result,
      source:'games.csv',
      updatedAt:index.updatedAt,
      message:`从本地游戏库的 ${index.games.length.toLocaleString()} 款游戏中筛选出 ${result.totalItems.toLocaleString()} 款。`,
    });
  }catch(e){
    return NextResponse.json({configured:true,games:[],error:safeError(e)}, {status:502});
  }
}

export async function GET(req:NextRequest){
  const params=Object.fromEntries(req.nextUrl.searchParams.entries());
  return paginate(readQuery(params));
}

export async function POST(req:NextRequest){
  let body:unknown;
  try{
    body=await req.json();
  }catch{
    return NextResponse.json({error:'无效的 JSON 请求'},{status:400});
  }
  return paginate(readQuery(object(body)));
}
