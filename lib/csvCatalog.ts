import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import type { GameDeal } from './types';

const CSV_FILENAME = 'games.csv';
const COLUMNS_PER_ROW = 40;
const MAX_PRICE_USD = 70;
const TRADING_CARDS_CATEGORY = 'steam trading cards';
const DEMO_RE = /(?<![\p{L}\p{N}_])(?:playtest|demo|soundtrack|original soundtrack|beta)(?![\p{L}\p{N}_])/iu;

interface CatalogIndex {
  games: GameDeal[];
  updatedAt: string;
  mtimeMs: number;
  size: number;
}

type CatalogGlobal = typeof globalThis & {
  __gchCsvCatalog?: CatalogIndex | null;
  __gchCsvCatalogPending?: Promise<CatalogIndex> | null;
};

const runtime = globalThis as CatalogGlobal;
let cachedIndex = runtime.__gchCsvCatalog || null;
let pendingIndex = runtime.__gchCsvCatalogPending || null;

class CsvRecordParser {
  private readonly onRecord: (values:string[]) => void;
  private field = '';
  private record: string[] = [];
  private inQuotes = false;
  private quotePending = false;
  private started = false;

  constructor(onRecord:(values:string[])=>void) {
    this.onRecord=onRecord;
  }

  push(chunk:string){
    for(let index=0;index<chunk.length;index++){
      const char=chunk[index];
      if(!this.started){
        this.started=true;
        if(char==='\uFEFF')continue;
      }
      if(this.inQuotes){
        if(this.quotePending){
          if(char==='"'){
            this.field+='"';
            this.quotePending=false;
            continue;
          }
          this.quotePending=false;
          this.inQuotes=false;
        }else if(char==='"'){
          this.quotePending=true;
          continue;
        }else{
          this.field+=char;
          continue;
        }
      }
      if(char==='"'){
        this.inQuotes=true;
      }else if(char===','){
        this.record.push(this.field);
        this.field='';
      }else if(char==='\n'){
        this.record.push(this.field);
        this.field='';
        this.emitRecord();
      }else if(char!=='\r'){
        this.field+=char;
      }
    }
  }

  end(){
    if(this.quotePending){
      this.quotePending=false;
      this.inQuotes=false;
    }
    if(this.field.length||this.record.length){
      this.record.push(this.field);
      this.field='';
      this.emitRecord();
    }
  }

  private emitRecord(){
    if(!this.record.length)return;
    const record=this.record;
    this.record=[];
    this.onRecord(record);
  }
}

function cleanText(value:string){
  return value
    .replace(/&#x([0-9a-f]+);/gi,(_,hex:string)=>String.fromCodePoint(Number.parseInt(hex,16)))
    .replace(/&#(\d+);/g,(_,decimal:string)=>String.fromCodePoint(Number(decimal)))
    .replace(/&nbsp;/gi,' ')
    .replace(/&amp;/gi,'&')
    .replace(/&quot;/gi,'"')
    .replace(/&#39;|&apos;/gi,"'")
    .replace(/&lt;/gi,'<')
    .replace(/&gt;/gi,'>')
    .replace(/<[^>]+>/g,' ')
    .replace(/\s+/g,' ')
    .trim();
}

function parseNumber(value:string,fallback=0){
  const match=(value||'').replaceAll(',','').match(/-?\d+(?:\.\d+)?/);
  if(!match)return fallback;
  const number=Number(match[0]);
  return Number.isFinite(number)?number:fallback;
}

export function catalogRowToDeal(values:string[]):GameDeal|null{
  if(values.length<COLUMNS_PER_ROW){
    values=[...values,...Array(COLUMNS_PER_ROW-values.length).fill('')];
  }
  const appid=Math.trunc(parseNumber(values[0]));
  const title=cleanText(values[1]||'');
  if(!Number.isSafeInteger(appid)||appid<=0||!title||DEMO_RE.test(title))return null;

  const priceUsd=parseNumber(values[6]);
  if(priceUsd<=0||priceUsd>=MAX_PRICE_USD)return null;
  const categories=cleanText(values[35]||'').toLocaleLowerCase('en-US');
  if(!categories.includes(TRADING_CARDS_CATEGORY))return null;

  const priceCents=Math.round(priceUsd*100);
  const discount=Math.max(0,Math.min(100,Math.trunc(parseNumber(values[7]))));
  const originalCents=discount>0
    ?Math.max(priceCents,Math.round(priceCents/(1-discount/100)))
    :priceCents;

  return {
    id:`steam-${appid}`,
    appid,
    title,
    priceCents,
    originalCents,
    discount,
    currency:'USD',
    storeUrl:`https://store.steampowered.com/app/${appid}/`,
    imageUrl:cleanText(values[13]||'')||undefined,
    source:'catalog',
    isBaseGame:true,
    canDropCards:true,
  };
}

async function buildCatalogIndex(
  filePath:string,
  mtimeMs:number,
  size:number,
):Promise<CatalogIndex>{
  const games=new Map<number,GameDeal>();
  let recordNumber=0;
  const parser=new CsvRecordParser(values=>{
    if(recordNumber++===0)return;
    const game=catalogRowToDeal(values);
    if(game&&!games.has(game.appid))games.set(game.appid,game);
  });

  await new Promise<void>((resolve,reject)=>{
    const stream=createReadStream(filePath,{encoding:'utf8',highWaterMark:1024*1024});
    stream.on('data',(chunk:string|Buffer)=>parser.push(typeof chunk==='string'?chunk:chunk.toString('utf8')));
    stream.on('error',reject);
    stream.on('end',()=>{
      parser.end();
      resolve();
    });
  });

  return {
    games:Array.from(games.values()),
    updatedAt:new Date(mtimeMs).toISOString(),
    mtimeMs,
    size,
  };
}

export async function getCsvGameCatalog():Promise<CatalogIndex>{
  const filePath=path.join(process.cwd(),CSV_FILENAME);
  const file=await stat(filePath).catch(()=>null);
  if(!file?.isFile()){
    throw new Error(`${CSV_FILENAME} was not found in the project root.`);
  }
  if(cachedIndex&&cachedIndex.mtimeMs===file.mtimeMs&&cachedIndex.size===file.size){
    return cachedIndex;
  }
  if(pendingIndex)return pendingIndex;

  pendingIndex=buildCatalogIndex(filePath,file.mtimeMs,file.size)
    .then(index=>{
      cachedIndex=index;
      runtime.__gchCsvCatalog=index;
      return index;
    })
    .finally(()=>{
      pendingIndex=null;
      runtime.__gchCsvCatalogPending=null;
    });
  runtime.__gchCsvCatalogPending=pendingIndex;
  return pendingIndex;
}
