import { NextRequest, NextResponse } from 'next/server';
import { estimateCardValue } from '@/lib/analysis';
import { safeError } from '@/lib/http';
import { fetchSteamMarketCards } from '@/lib/steam';
import type { Analysis } from '@/lib/types';
export const runtime='nodejs';
const cache=new Map<number,{expires:number,data:Analysis}>();
const inflight=new Map<number,Promise<Analysis>>();

async function getCardAnalysis(appid:number):Promise<Analysis>{
  const cached=cache.get(appid);
  if(cached&&cached.expires>Date.now())return cached.data;
  let pending=inflight.get(appid);
  if(!pending){
    pending=fetchSteamMarketCards(appid,1);
    inflight.set(appid,pending);
  }
  try{
    const result=await pending;
    cache.set(appid,{expires:Date.now()+5*60_000,data:result});
    return result;
  }finally{
    inflight.delete(appid);
  }
}

export async function GET(req:NextRequest){
  const appid=Number(req.nextUrl.searchParams.get('appid'));
  if(!Number.isSafeInteger(appid)||appid<1||appid>1e10)
    return NextResponse.json({error:'无效的 AppID'},{status:400});
  try{
    const result=await getCardAnalysis(appid);
    return NextResponse.json({
      configured:true,
      appid,
      status:result.status,
      currency:'USD',
      cardSetSize:result.cards.length,
      estimatedDropCount:result.expectedDrops,
      dropQuotaConfirmed:false,
      cards:result.cards,
      updatedAt:result.updatedAt,
      note:result.note,
      warning:'该接口只返回普通卡牌，不返回闪卡；闪卡不参与掉落张数和回收率计算。账号真实剩余掉落次数需要 Steam 登录态，不能通过匿名接口确认。',
    });
  }catch(e){return NextResponse.json({error:safeError(e)},{status:502});}
}

export async function POST(req:NextRequest){
  let body:any;try{body=await req.json();}catch{return NextResponse.json({error:'无效的 JSON 请求'},{status:400});}
  const appid=Number(body.appid);const priceCents=Math.round(Number(body.priceCents));
  if(!Number.isSafeInteger(appid)||appid<1||appid>1e10||!Number.isFinite(priceCents)||priceCents<1||priceCents>1e7)
    return NextResponse.json({error:'无效的 AppID 或游戏价格'},{status:400});
  try{
    const result=await getCardAnalysis(appid);
    return NextResponse.json(result.status==='ok'?estimateCardValue(result.cards,priceCents,result.updatedAt):result);
  }catch(e){return NextResponse.json({error:safeError(e)},{status:502});}
}
