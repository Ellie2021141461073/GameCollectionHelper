import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {displayCardName,estimatedSellerNetCents,estimateCardValue,formatMoney,qualityLabel} from '../lib/analysis.ts';
import {catalogRowToDeal} from '../lib/csvCatalog.ts';
import {paginateDeals} from '../lib/dealPagination.ts';
import {normalizeSteamImageUrl,parseSteamAppDetails,parseSteamMarketSearch,parseSteamStoreResults,parseSteamStoreSearch,parseSteamUsdOverview,SteamDataError} from '../lib/steamParse.ts';

test('seller proceeds estimation uses minimum fees',()=>{
  assert.equal(estimatedSellerNetCents(149),128);
  assert.equal(estimatedSellerNetCents(3),1);
  assert.equal(estimatedSellerNetCents(-1),0);
  assert.equal(formatMoney(149),'$1.49');
});
test('card display name removes AppID prefix and foil suffix',()=>{
  assert.equal(displayCardName('952040-Mask Dude'),'Mask Dude');
  assert.equal(displayCardName('952040-Mask Dude (Foil)'),'Mask Dude');
});
test('recovery labels use 30 and 40 percent boundaries',()=>{
  const analysis=rate=>({status:'ok',cards:[],expectedDrops:0,estimatedNetCents:null,recoveryRate:rate,estimatedProfitCents:null});
  assert.equal(qualityLabel(analysis(29.9)),'低回收率');
  assert.equal(qualityLabel(analysis(30)),'中回收率');
  assert.equal(qualityLabel(analysis(39.9)),'中回收率');
  assert.equal(qualityLabel(analysis(40)),'高回收率');
});
test('Steam capsule URLs use the reachable Fastly CDN',()=>{
  assert.equal(
    normalizeSteamImageUrl('https://shared.st.dl.eccdnx.com/store_item_assets/steam/apps/1165860/capsule_231x87.jpg'),
    'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1165860/capsule_231x87.jpg'
  );
});
test('recovery is based on expected *drop count*, not the full card set',()=>{
  const cards=[40,40,40,40,40,40].map((c,i)=>({name:String(i),grossCents:c,netCents:estimatedSellerNetCents(c),listings:10,marketUrl:''}));
  const r=estimateCardValue(cards,200);
  assert.equal(r.expectedDrops,3);
  assert.equal(r.estimatedNetCents,102);
  assert.equal(r.recoveryRate,51);
});
test('empty card list must not become recommendation',()=>{
  const a=estimateCardValue([],100);
  assert.equal(a.status,'none');
  assert.equal(a.recoveryRate,null);
});
test('games.csv rows map only the existing GameDeal fields',()=>{
  const values=Array(40).fill('');
  values[0]='413150';
  values[1]='Stardew Valley';
  values[6]='24.00';
  values[7]='50';
  values[13]='https://example.test/stardew.jpg';
  values[35]="['Steam Trading Cards', 'Single-player']";

  const deal=catalogRowToDeal(values);
  assert.deepEqual(deal,{
    id:'steam-413150',
    appid:413150,
    title:'Stardew Valley',
    priceCents:2400,
    originalCents:4800,
    discount:50,
    currency:'USD',
    storeUrl:'https://store.steampowered.com/app/413150/',
    imageUrl:'https://example.test/stardew.jpg',
    source:'catalog',
    isBaseGame:true,
    canDropCards:true,
  });
});
test('games.csv ignores demo and playtest catalogue rows',()=>{
  const values=Array(40).fill('');
  values[0]='2539430';
  values[1]='Black Dragon Mage Playtest';
  values[6]='9.99';
  values[35]="['Steam Trading Cards']";
  assert.equal(catalogRowToDeal(values),null);
});
test('games.csv demo filtering follows Unicode word boundaries',()=>{
  const values=Array(40).fill('');
  values[0]='3933730';
  values[1]='着色 Project_Shading 技术演示demo';
  values[6]='2.39';
  values[35]="['Steam Trading Cards']";
  assert.equal(catalogRowToDeal(values)?.appid,3933730);
});
test('games.csv keeps only paid card games below seventy US dollars',()=>{
  const base=Array(40).fill('');
  base[0]='100';
  base[1]='Valid Card Game';
  base[6]='69.99';
  base[35]="['Steam Trading Cards']";
  assert.equal(catalogRowToDeal(base)?.priceCents,6999);

  assert.equal(catalogRowToDeal([...base.slice(0,6),'0',...base.slice(7)]),null);
  assert.equal(catalogRowToDeal([...base.slice(0,6),'70',...base.slice(7)]),null);
  const noCards=[...base];
  noCards[35]="['Single-player']";
  assert.equal(catalogRowToDeal(noCards),null);
});
test('recommender uses DeepSeek without card-page OpenAI settings',()=>{
  const env=readFileSync('.env.example','utf8');
  assert.ok(env.includes('DEEPSEEK_API_KEY='));
  assert.ok(env.includes('EMBEDDING_MODEL=BAAI/bge-m3'));
  assert.equal(env.includes('OPENAI_API_KEY='),false);
  assert.ok(readFileSync('README.md','utf8').includes('Steam 实时接口'));
});
test('Steam Store USD prices are converted from cents without invented values',()=>{
  const deal=parseSteamAppDetails({
    413150:{success:true,data:{type:'game',name:'Stardew Valley',is_free:false,header_image:'https://example.test/header.jpg',
      price_overview:{currency:'USD',initial:4800,final:2400,discount_percent:50},
      categories:[{id:2,description:'Single-player'},{id:29,description:'Steam Trading Cards'}]}}
  },413150);
  assert.equal(deal.appid,413150);
  assert.equal(deal.title,'Stardew Valley');
  assert.equal(deal.priceCents,2400);
  assert.equal(deal.originalCents,4800);
  assert.equal(deal.discount,50);
  assert.equal(deal.source,'live');
  assert.equal(deal.isBaseGame,true);
  assert.equal(deal.canDropCards,true);
  assert.equal(deal.storeUrl,'https://store.steampowered.com/app/413150/');
});
test('Steam Store rejects unavailable or non-USD app data',()=>{
  assert.throws(()=>parseSteamAppDetails({1:{success:false}},1),SteamDataError);
  assert.throws(()=>parseSteamAppDetails({
    1:{success:true,data:{type:'game',name:'Region Test',price_overview:{currency:'CNY',initial:1000,final:500}}}
  },1),SteamDataError);
});
test('Steam Community Market parser classifies unique normal and foil cards',()=>{
  const market=parseSteamMarketSearch({
    success:true,
    total_count:4,
    pagesize:10,
    results:[
      {hash_name:'413150-Evelyn',sell_price:11,sell_listings:5247,asset_description:{icon_url:'test-icon'}},
      {hash_name:'413150-Evelyn',sell_price:11,sell_listings:5247,asset_description:{icon_url:'test-icon'}},
      {hash_name:'413150-Abigail (Foil)',sell_price:115,sell_listings:42},
      {hash_name:'413150-Sebastian (Foil Trading Card)',sell_price:110,sell_listings:35}
    ]
  });
  assert.equal(market.total,4);
  assert.equal(market.pageSize,10);
  assert.equal(market.cards.length,3);
  assert.deepEqual(market.cards[0],{
    name:'413150-Evelyn',
    listings:5247,
    marketUrl:'https://steamcommunity.com/market/listings/753/413150-Evelyn',
    imageUrl:'https://community.fastly.steamstatic.com/economy/image/test-icon/64fx64f',
    foil:false,
  });
  assert.equal(market.cards[1].foil,true);
  assert.equal(market.cards[2].foil,true);
});
test('Steam Store search resolves the exact AppID and USD price',()=>{
  const deal=parseSteamStoreSearch({
    total:2,
    items:[
      {type:'app',name:'Wrong App',id:1,price:{currency:'USD',initial:1000,final:500},tiny_image:'wrong'},
      {type:'app',name:'ZED ZONE',id:1211600,price:{currency:'USD',initial:4800,final:2880},tiny_image:'https://example.test/zed.jpg'}
    ]
  },1211600);
  assert.equal(deal?.title,'ZED ZONE');
  assert.equal(deal?.priceCents,2880);
  assert.equal(deal?.originalCents,4800);
  assert.equal(deal?.discount,40);
});
test('Steam priceoverview USD strings are converted to cents',()=>{
  assert.equal(parseSteamUsdOverview({success:true,lowest_price:'$0.73',median_price:'$0.74'}),73);
  assert.equal(parseSteamUsdOverview({success:true,lowest_price:'$1,234.56'}),123456);
  assert.equal(parseSteamUsdOverview({success:true}),null);
});
test('Steam Store low-price results exclude free and over-limit games and sort ascending',()=>{
  const games=parseSteamStoreResults({success:1,results_html:`
    <a href="https://store.steampowered.com/app/200/Second/"> data-ds-appid="200"
      <div class="search_capsule"><img src="https://example.test/200.jpg"></div>
      <div class="search_name"><span class="title">Second</span></div>
      <div data-price-final="990"></div></a>
    <a href="https://store.steampowered.com/app/100/First/"> data-ds-appid="100"
      <div class="search_capsule"><img src="https://example.test/100.jpg"></div>
      <div class="search_name"><span class="title">First &amp; Best</span></div>
      <div data-price-final="250"></div></a>
    <a href="https://store.steampowered.com/app/300/Free/"> data-ds-appid="300"
      <div class="search_name"><span class="title">Free</span></div>
      <div data-price-final="0"></div></a>
    <a href="https://store.steampowered.com/app/400/High/"> data-ds-appid="400"
      <div class="search_name"><span class="title">High</span></div>
      <div data-price-final="2000"></div></a>
  `},2000,60);
  assert.deepEqual(games.map(game=>game.appid),[100,200]);
  assert.equal(games[0].title,'First & Best');
  assert.equal(games[0].priceCents,250);
  assert.equal(games[0].currency,'USD');
  assert.equal(games[0].isBaseGame,true);
  assert.equal(games[0].canDropCards,true);
});
test('appdetails reports games without category 29 as not card-droppable',()=>{
  const deal=parseSteamAppDetails({
    1211600:{success:true,data:{type:'game',name:'ZED ZONE',is_free:false,
      price_overview:{currency:'USD',initial:4800,final:2880,discount_percent:40},
      categories:[{id:2,description:'Single-player'},{id:30,description:'Steam Workshop'}]}}
  },1211600);
  assert.equal(deal.isBaseGame,true);
  assert.equal(deal.canDropCards,false);
});
test('server pagination recalculates pages after filters and recovery change',()=>{
  const games=Array.from({length:25},(_,index)=>({
    id:`steam-${index}`,
    appid:index,
    title:`Game ${index}`,
    priceCents:300+index*20,
    originalCents:1000,
    discount:index>=23?95:20,
    currency:'USD',
    storeUrl:'',
    source:'live',
    isBaseGame:true,
    canDropCards:true,
  }));
  const baseFilters={query:'',maxPrice:10,minDiscount:0,minRecovery:0,sort:'price',onlyQualified:false};
  const base=paginateDeals(games,{page:1,pageSize:10,filters:baseFilters,analyses:{}});
  assert.equal(base.totalItems,25);
  assert.equal(base.totalPages,3);
  assert.deepEqual(base.stats,{analyzed:0,qualified:0,averageRecovery:null});

  const globalStats=paginateDeals(games,{page:1,pageSize:10,filters:baseFilters,analyses:{
    'steam-24':{status:'ok',recoveryRate:130},
  }});
  assert.equal(globalStats.games.some(game=>game.id==='steam-24'),false);
  assert.deepEqual(globalStats.stats,{analyzed:1,qualified:1,averageRecovery:130});

  const discounted=paginateDeals(games,{page:1,pageSize:10,filters:{...baseFilters,minDiscount:90},analyses:{}});
  assert.equal(discounted.totalItems,2);
  assert.equal(discounted.totalPages,1);

  const recoveryThresholdOnly=paginateDeals(games,{page:1,pageSize:10,filters:{...baseFilters,minRecovery:100},analyses:{
    'steam-1':{status:'ok',recoveryRate:150},
    'steam-2':{status:'ok',recoveryRate:80},
  }});
  assert.equal(recoveryThresholdOnly.totalItems,25);

  const analyzed=paginateDeals(games,{page:1,pageSize:10,filters:{...baseFilters,minRecovery:100,onlyQualified:true},analyses:{
    'steam-1':{status:'ok',recoveryRate:150},
    'steam-2':{status:'ok',recoveryRate:80},
    'steam-3':{status:'error',recoveryRate:null},
  }});
  assert.equal(analyzed.totalItems,2);
  assert.equal(analyzed.games[0].appid,1);
  assert.equal(analyzed.stats.analyzed,2);
  assert.equal(analyzed.stats.qualified,1);
});
