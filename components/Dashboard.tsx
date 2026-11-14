'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Icon from './Icons';
import CardThumb from './CardThumb';
import {displayCardName,formatMoney,fmtRate,qualityLabel,qualifies} from '@/lib/analysis';
import {normalizeSteamImageUrl} from '@/lib/steamParse';
import type {Analysis,Filters,GameDeal,ScanState} from '@/lib/types';

const defaultFilters:Filters={query:'',maxPrice:10,minDiscount:0,minRecovery:0,sort:'price',onlyQualified:false};
const PAGE_SIZE=8;
const emptyAnalysis:Analysis={status:'unscanned',cards:[],expectedDrops:0,estimatedNetCents:null,recoveryRate:null,estimatedProfitCents:null};
const patternColors=['#a073fb','#4d90f4','#25b6a5','#ed966a','#fac26e','#e569b4','#7bd79a','#77c7f5'];
const formatDate=(raw?:string)=>raw && raw.startsWith('20')?new Date(raw).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'待获取';

function Badge({children,kind='neutral'}:{children:React.ReactNode;kind?:'green'|'orange'|'neutral'|'purple'|'red'}){return <span className={`badge badge-${kind}`}>{children}</span>}
function Price({cents}:{cents:number|null|undefined}){return <span className="numeric">{formatMoney(cents)}</span>}
function Empty({title,text}:{title:string,text:string}){return <div className="empty"><div className="empty-mark"><Icon name="search" size={25}/></div><h3>{title}</h3><p>{text}</p></div>}

export type DashboardView='overview'|'watchlist';

export default function Dashboard({view='overview'}:{view?:DashboardView}){
  const isWatchlist=view==='watchlist';
  const [games,setGames]=useState<GameDeal[]>([]);
  const [analyses,setAnalyses]=useState<ScanState>({});
  const [filters,setFilters]=useState<Filters>(defaultFilters);
  const [liveLoading,setLiveLoading]=useState(false);
  const [scanning,setScanning]=useState(false);
  const [scanProgress,setScanProgress]=useState({done:0,total:0});
  const [notice,setNotice]=useState(isWatchlist?'正在显示已关注游戏。':'正在加载本地游戏库。');
  const [watchlist,setWatchlist]=useState<string[]>([]);
  const [savedGames,setSavedGames]=useState<GameDeal[]>([]);
  const [selected,setSelected]=useState<GameDeal|null>(null);
  const [selectedImageFailed,setSelectedImageFailed]=useState(false);
  const [loadingCardId,setLoadingCardId]=useState<string|null>(null);
  const [manualOpen,setManualOpen]=useState(false);
  const [manual,setManual]=useState({appid:'',title:'',price:'',discount:'0'});
  const [manualError,setManualError]=useState('');
  const [manualSteam,setManualSteam]=useState<GameDeal|null>(null);
  const [manualLoading,setManualLoading]=useState(false);
  const [error,setError]=useState('');
  const [page,setPage]=useState(1);
  const [serverPagination,setServerPagination]=useState<{
    pageSize:number;
    totalItems:number;
    totalPages:number;
    stats:{analyzed:number;qualified:number;averageRecovery:number|null};
  }|null>(null);
  const liveIndexReady=useRef(false);

  useEffect(()=>{
    try{
      const saved=localStorage.getItem('cardscout-saved-games-v2');
      let validSavedIds:Set<string>|null=null;
      if(saved){
        const list=JSON.parse(saved);
        if(Array.isArray(list)){
          const usdGames=list.filter(game=>game?.currency==='USD');
          setSavedGames(usdGames);
          validSavedIds=new Set(usdGames.map(game=>game.id));
        }
      }
      const ids=localStorage.getItem('cardscout-favorites-v1');
      if(ids){
        const favorites=JSON.parse(ids);
        if(Array.isArray(favorites)){
          setWatchlist(validSavedIds?favorites.filter(id=>validSavedIds.has(id)):favorites);
        }
      }
    }catch{}
  },[]);
  useEffect(()=>{
    try{
      localStorage.setItem('cardscout-favorites-v1',JSON.stringify(watchlist));
      localStorage.setItem('cardscout-saved-games-v2',JSON.stringify(savedGames));
    }catch{}
  },[watchlist,savedGames]);
  useEffect(()=>{
    window.dispatchEvent(new CustomEvent('gch:workspace-counts',{detail:isWatchlist?{watchlist:watchlist.length}:{overview:games.length,watchlist:watchlist.length}}));
  },[games.length,watchlist.length,isWatchlist]);
  useEffect(()=>setSelectedImageFailed(false),[selected?.id]);
  const updateFilters=(patch:Partial<Filters>)=>{setFilters(p=>({...p,...patch}));setPage(1);};
  const loadLive=useCallback(async(targetPage=1,nextFilters=filters,nextAnalyses=analyses)=>{
    setLiveLoading(true);setError('');
    try{
      const analysisSummary=Object.fromEntries(Object.entries(nextAnalyses).map(([id,analysis])=>[
        id,{status:analysis.status,recoveryRate:analysis.recoveryRate},
      ]));
      const res=await fetch('/api/deals',{
        method:'POST',
        cache:'no-store',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({page:targetPage,pageSize:PAGE_SIZE,filters:nextFilters,analyses:analysisSummary}),
      });
      const data=await res.json();
      if(!res.ok)throw new Error(data.error||'折扣数据获取失败');
      if(!data.configured){setNotice(data.message);return;}
      const list=(data.games||[]) as GameDeal[];
      setGames(list);
      setPage(Number(data.page)||targetPage);
      setServerPagination({
        pageSize:Number(data.pageSize)||PAGE_SIZE,
        totalItems:Number(data.totalItems)||0,
        totalPages:Math.max(1,Number(data.totalPages)||1),
        stats:{
          analyzed:Number(data.stats?.analyzed)||0,
          qualified:Number(data.stats?.qualified)||0,
          averageRecovery:data.stats?.averageRecovery==null?null:Number(data.stats.averageRecovery),
        },
      });
      setNotice(data.message||`已获取 ${list.length} 款游戏。`);
      liveIndexReady.current=true;
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLiveLoading(false);}
  },[filters,analyses]);
  useEffect(()=>{if(!isWatchlist&&!liveLoading&&games.length===0)void loadLive();},[]);
  const analysisKey=Object.keys(analyses).sort().map(id=>{
    const analysis=analyses[id];
    return `${id}:${analysis.status}:${analysis.recoveryRate??''}`;
  }).join('|');
  const filterKey=[filters.query,filters.maxPrice,filters.minDiscount,filters.minRecovery,filters.sort,filters.onlyQualified,analysisKey].join('|');
  useEffect(()=>{
    if(isWatchlist||!liveIndexReady.current||scanning)return;
    const timer=setTimeout(()=>void loadLive(1,filters,analyses),250);
    return ()=>clearTimeout(timer);
  },[filterKey,scanning,isWatchlist]);
  const analyze=useCallback(async(game:GameDeal):Promise<Analysis>=>{
    const res=await fetch('/api/cards',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({appid:game.appid,priceCents:game.priceCents})});
    const data=await res.json();
    if(!res.ok)throw new Error(data.error||'卡牌查询失败');
    const a=data as Analysis;setAnalyses(p=>({...p,[game.id]:a}));return a;
  },[]);
  const openGame=async(game:GameDeal)=>{
    setSelected(game);
    setLoadingCardId(game.id);setError('');
    try{
      await analyze(game);
    }catch(e){
      const note=e instanceof Error?e.message:'掉落卡牌获取失败';
      setAnalyses(p=>({...p,[game.id]:{...emptyAnalysis,status:'error',note}}));
      setError(note);
    }finally{
      setLoadingCardId(current=>current===game.id?null:current);
    }
  };
  const scanAll=async()=>{
    const sourceGames=isWatchlist?savedGames:games;
    const targets=sourceGames.filter(g=>analyses[g.id]?.status!=='ok').slice(0,8);
    if(!targets.length){setNotice('当前页没有可获取卡牌数据的游戏。单次最多处理 8 款。');return;}
    setScanning(true);setScanProgress({done:0,total:targets.length});setError('');
    let failed=0;
    for(let i=0;i<targets.length;i++){
      try{await analyze(targets[i]);}catch(e){failed++;setAnalyses(p=>({...p,[targets[i].id]:{...emptyAnalysis,status:'error',note:e instanceof Error?e.message:'网络错误'}}));}
      setScanProgress({done:i+1,total:targets.length});
    }
    setNotice(`已尝试分析 ${targets.length} 款游戏，其中 ${failed} 款失败。若遇到 429， 请稍后重试。`);setScanning(false);
  };
  const openManual=()=>{setManualOpen(true);setManualError('');setManualSteam(null);setManual({appid:'',title:'',price:'',discount:'0'});};
  const lookupSteamApp=async()=>{
    const appid=Number(manual.appid);
    if(!Number.isSafeInteger(appid)||appid<1||appid>1e10){setManualError('请输入有效的 AppID。');return;}
    setManualLoading(true);setManualError('');
    try{
      const res=await fetch(`/api/steam/app?appid=${appid}`,{cache:'no-store'});
      const data=await res.json();
      if(!res.ok)throw new Error(data.error||'Steam 游戏读取失败');
      const deal=data.deal as GameDeal;
      setManualSteam(deal);
      setManual({appid:String(deal.appid),title:deal.title,price:(deal.priceCents/100).toFixed(2),discount:String(deal.discount)});
      if(deal.priceCents<=0)setManualError('该游戏当前免费；免费游戏通常不能按购买价估算掉卡回收。');
    }catch(e){setManualSteam(null);setManualError(e instanceof Error?e.message:String(e));}
    finally{setManualLoading(false);}
  };
  const addManual=()=>{
    const appid=Number(manual.appid),price=Number(manual.price),discount=Number(manual.discount);
    if(!Number.isSafeInteger(appid)||appid<1||appid>1e10||!Number.isFinite(price)||price<=0||price>10000||!Number.isFinite(discount)||discount<0||discount>99){setManualError('请输入有效的 AppID、美元价格以及折扣百分比。');return;}
    const next:GameDeal=manualSteam?.appid===appid?manualSteam:{id:`manual-${appid}`,appid,title:manual.title.trim()||`Steam App ${appid}`,priceCents:Math.round(price*100),originalCents:discount>0?Math.round(price*100/(1-discount/100)):Math.round(price*100),discount:Math.round(discount),currency:'USD',storeUrl:`https://store.steampowered.com/app/${appid}/`,imageUrl:`https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`,source:'manual'};
    setGames(p=>[next,...p.filter(g=>g.appid!==appid)]);setAnalyses(p=>{const q={...p};delete q[next.id];return q;});setManualOpen(false);setManualError('');setManualSteam(null);setManual({appid:'',title:'',price:'',discount:'0'});setPage(1);setNotice(next.source==='live'?`已从 Steam Store 读取 AppID ${appid}（${next.title}）。点击“分析卡牌”查询真实社区市场挂单。`:`已添加 AppID ${appid}。价格手动填写，卡牌价格需要点击游戏再查询。`);
  };
  const toggleFavorite=(game:GameDeal)=>{
    if(watchlist.includes(game.id)){
      setWatchlist(p=>p.filter(id=>id!==game.id));
      setSavedGames(p=>p.filter(saved=>saved.id!==game.id));
    }else{
      setWatchlist(p=>[...p,game.id]);
      setSavedGames(p=>[game,...p.filter(saved=>saved.id!==game.id)]);
    }
  };
  const viewGames=isWatchlist?savedGames:games;
  const filtered=useMemo(()=>{
    const q=filters.query.trim().toLowerCase();
    return viewGames.filter(g=>{
      const a=analyses[g.id];
      if(q&&!g.title.toLowerCase().includes(q)&&!String(g.appid).includes(q))return false;
      if(g.priceCents>filters.maxPrice*100 || g.discount<filters.minDiscount)return false;
      if(g.isBaseGame===false||g.canDropCards===false)return false;
      if(filters.onlyQualified&&a?.status!=='ok')return false;
      return true;
    }).sort((a,b)=>filters.sort==='price'?a.priceCents-b.priceCents:filters.sort==='discount'?b.discount-a.discount:(analyses[b.id]?.recoveryRate??-1)-(analyses[a.id]?.recoveryRate??-1));
  },[viewGames,analyses,filters]);
  const serverPaged=!isWatchlist&&serverPagination!==null;
  const totalPages=serverPaged?serverPagination.totalPages:Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));
  const totalItems=serverPaged?serverPagination.totalItems:filtered.length;
  const visibleGames=serverPaged?filtered:filtered.slice((page-1)*PAGE_SIZE,page*PAGE_SIZE);
  useEffect(()=>{if(!serverPaged&&page>totalPages)setPage(totalPages);},[page,totalPages,serverPaged]);
  const goToPage=(next:number)=>{
    const bounded=Math.max(1,Math.min(totalPages,next));
    if(bounded===page)return;
    setPage(bounded);
    if(serverPaged)void loadLive(bounded);
    requestAnimationFrame(()=>document.getElementById('results-top')?.scrollIntoView({behavior:'smooth',block:'start'}));
  };
  const stats=useMemo(()=>{
    if(!isWatchlist&&serverPagination){
      return {
        count:totalItems,
        analyzed:serverPagination.stats.analyzed,
        qualified:serverPagination.stats.qualified,
        average:serverPagination.stats.averageRecovery,
      };
    }
    const verified=filtered.filter(g=>analyses[g.id]?.status==='ok');
    const qualified=verified.filter(g=>qualifies(g,analyses[g.id],filters.minRecovery));
    const rates=verified.map(g=>analyses[g.id].recoveryRate).filter((r):r is number=>r!=null);
    return {count:totalItems,analyzed:verified.length,qualified:qualified.length,average:rates.length?rates.reduce((s,n)=>s+n,0)/rates.length:null};
  },[isWatchlist,filtered,analyses,filters.minRecovery,totalItems,serverPagination]);
  const exportCsv=()=>{
    const lines=[['AppID','Game','PriceUSD','DiscountPct','ExpectedNetUSD','RecoveryPct','Status','Source'],...filtered.map(g=>[String(g.appid),g.title,(g.priceCents/100).toFixed(2),String(g.discount),analyses[g.id]?.estimatedNetCents==null?'':(analyses[g.id].estimatedNetCents!/100).toFixed(2),String(analyses[g.id]?.recoveryRate??''),analyses[g.id]?.status??'unscanned',g.source])];
    const csv='\uFEFF'+lines.map(row=>row.map(s=>'"'+String(s).replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='collection-results.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const selectedCardLoading=selected!==null&&loadingCardId===selected.id;
  return <>
          <div className="heading-row"><div><div className="eyebrow"><span className="eyebrow-dot"/> STEAM GAME DISCOVERY</div><h1>{isWatchlist?'珍藏每一份惊喜':'见证每一份热爱'}<span className="heading-mark">✦</span></h1><p className="lead">{isWatchlist?'把值得关注的游戏保存下来，方便下次继续查看。':'从游戏折扣到卡牌价值，找到更适合收藏的 Steam 游戏。'}</p></div><a className="primary-button assistant-cta" href="/recommend"><Icon name="sparkles" size={17}/> 打开智能推荐 <Icon name="arrow" size={16}/></a></div>
          <div className="mode-banner"><div className="mode-left"><span className="mode-symbol mode-live"><Icon name="database" size={18}/></span><div><strong>本地游戏库</strong><p>{notice}</p></div></div></div>
          <section className="stat-grid" aria-label="统计概览">
            <Stat icon="grid" title="候选游戏" value={String(stats.count)} foot="筛选后全部匹配数" tone="purple"/>
            <Stat icon="chart" title="已分析卡牌" value={String(stats.analyzed)} foot="数据完整可估算" tone="blue"/>
            <Stat icon="bolt" title="满足回本条件" value={String(stats.qualified)} foot={`回本率 ≥ ${filters.minRecovery}%`} tone="green"/>
            <Stat icon="star" title="平均预估回本率" value={stats.average==null?'—':`${stats.average.toFixed(1)}%`} foot="仅基于已成功分析项" tone="orange"/>
          </section>
          <div className="workspace-grid">
            <section className="panel filter-panel"><div className="panel-heading"><div><Icon name="filter" size={18}/><strong>查询条件</strong></div><button className="text-button" onClick={()=>updateFilters(defaultFilters)}>重置</button></div>
              <label className="field-label" htmlFor="search-box">搜索游戏 / AppID</label><div className="search-field"><Icon name="search" size={17}/><input id="search-box" value={filters.query} placeholder="输入游戏名称..." onChange={e=>updateFilters({query:e.target.value})}/></div>
              <div className="field-heading"><label htmlFor="price-range">游戏价格</label><span className="field-value">${filters.maxPrice.toFixed(0)}</span></div><input id="price-range" type="range" min="0" max="70" step="1" value={filters.maxPrice} onChange={e=>updateFilters({maxPrice:Number(e.target.value)})}/><div className="range-labels"><span>$0</span><span>$70</span></div>
              <div className="field-heading"><label htmlFor="discount-range">折扣力度</label><span className="field-value">{filters.minDiscount}%</span></div><input id="discount-range" type="range" min="0" max="100" step="5" value={filters.minDiscount} onChange={e=>updateFilters({minDiscount:Number(e.target.value)})}/><div className="range-labels"><span>0%</span><span>100%</span></div>
              <div className="field-heading"><label htmlFor="recovery-range">卡牌回本率</label><span className="field-value lime">{filters.minRecovery}%</span></div><input id="recovery-range" type="range" min="0" max="100" step="10" value={filters.minRecovery} onChange={e=>updateFilters({minRecovery:Number(e.target.value)})}/><div className="range-labels"><span>0%</span><span>100%</span></div>
              <div className="filter-divider"/><label className="toggle-row"><span><strong>只显示已分析游戏</strong><small>请先点击游戏获取回本率</small></span><input type="checkbox" checked={filters.onlyQualified} onChange={e=>updateFilters({onlyQualified:e.target.checked})}/><span className="toggle-ui"/></label>
              <div className="sidebar-tip"><Icon name="info" size={15}/><p>回本率 = 预估卡牌出售净额 / 游戏价格。不是稳赚概率，未分析项不会被推荐。</p></div>
            </section>
            <section className="results-area" id="results-top"><div className="results-title"><div><div className="results-main-title"><h2>{isWatchlist?'关注列表':'游戏列表'}</h2><span className="subtle-count">{totalItems} 款游戏</span><span className="subtle-count">第 {page}/{totalPages} 页 · 每页 {serverPagination?.pageSize||PAGE_SIZE} 款</span></div><p>由计算规则筛选，数据源清晰可追溯</p></div><div className="result-actions"><button className="small-button" onClick={exportCsv}><Icon name="download" size={16}/> <span className="hide-mobile">导出 CSV</span></button>{!isWatchlist&&<><button className="small-button" onClick={openManual}><Icon name="plus" size={16}/> 按 AppID 添加</button><button className="small-button" onClick={()=>loadLive(1)} disabled={liveLoading||scanning}><Icon name="refresh" size={16}/>{liveLoading?'加载中':'刷新游戏列表'}</button></>}<button className="small-button emphasize" disabled={scanning||liveLoading||(isWatchlist?savedGames.length:games.length)===0} onClick={scanAll}><Icon name="bolt" size={16}/>{scanning?`${scanProgress.done}/${scanProgress.total}`:'获取当前页回本率 (8)'}</button></div></div>
              {error&&<div className="error-banner"><Icon name="warning" size={16}/>{error}<button onClick={()=>setError('')} aria-label="关闭错误"><Icon name="close" size={16}/></button></div>}
              {!isWatchlist&&games.length===0&&<div className="prestart panel"><div className="prestart-icon"><Icon name="database" size={28}/></div><h3>{liveLoading?'正在读取本地游戏库':'正在等待本地游戏数据'}</h3><p>{liveLoading?'正在读取本地数据库。首次加载速度较慢。':'可点击刷新，或输入 AppID 实时获取单款游戏数据。'}</p><div className="prestart-actions"><button className="primary-button" onClick={()=>loadLive(1)} disabled={liveLoading}><Icon name="refresh" size={16}/>{liveLoading?'加载中...':'加载游戏库'}</button><button className="small-button" onClick={openManual}><Icon name="plus" size={16}/> 按 AppID 添加</button></div><small>总览来自本地数据库，卡牌与 AppID 查询使用 Steam 实时接口</small></div>}
              {isWatchlist&&viewGames.length===0&&<div className="panel"><Empty title="暂无关注" text="请先在游戏总览中点击星标关注游戏。"/></div>}
              {viewGames.length>0&&(filtered.length>0?<div className="games-list">{visibleGames.map((g,i)=><GameRow key={g.id} game={g} analysis={analyses[g.id]} index={(page-1)*PAGE_SIZE+i} saved={watchlist.includes(g.id)} onSaved={()=>toggleFavorite(g)} onClick={()=>void openGame(g)}/>)}</div>:<div className="panel"><Empty title="没有符合条件的收藏游戏" text="试着调整筛选条件，或先获取游戏的卡牌数据。"/></div>)}
              {viewGames.length>0&&filtered.length>0&&<Pagination page={page} totalPages={totalPages} totalItems={totalItems} onChange={goToPage} disabled={liveLoading||scanning}/>}
              {viewGames.length>0&&<div className="list-foot"><Icon name="info" size={15}/> 卡牌市场报价可能延迟，且手续费、税费、掉落和成交情况会影响实际结果。</div>}
            </section>
          </div>
          <footer className="content-footer"><span>GameCollectionHelper · Steam 游戏收藏助手 · 非 Steam 官方产品</span><span>US / USD · Read-only discovery & collection helper</span></footer>
    {selected&&<div className="modal-overlay" onMouseDown={()=>setSelected(null)}>
      <div className="details-panel" role="dialog" aria-modal="true" aria-label="游戏卡牌分析详情" onMouseDown={e=>e.stopPropagation()}>
        <div className="drawer-top"><span className="eyebrow">CARD VALUE DETAILS / #{selected.appid}</span><button className="icon-button" aria-label="关闭详情" onClick={()=>setSelected(null)}><Icon name="close"/></button></div>
    <div className="drawer-hero"><span className={`drawer-cover ${selected.imageUrl&&!selectedImageFailed?'has-image':''}`} style={{background:patternColors[selected.appid%patternColors.length]}}>{selected.imageUrl&&!selectedImageFailed?<img className="drawer-cover-image" src={normalizeSteamImageUrl(selected.imageUrl)} alt={`${selected.title} 胶囊图`} decoding="async" referrerPolicy="no-referrer" onError={()=>setSelectedImageFailed(true)}/>:<Icon name="bolt" size={35}/>}</span><div><h2>{selected.title}</h2><div className="drawer-pills"><Badge kind="green">{selected.source==='manual'?'手动价格':selected.source==='catalog'?'本地游戏库':'Steam Store'}</Badge>{selected.isBaseGame&&<Badge kind="neutral">游戏本体</Badge>}{selected.canDropCards&&<Badge kind="green">可掉卡</Badge>}{selectedCardLoading&&<Badge kind="orange">正在获取卡牌</Badge>}<Badge kind="orange">-{selected.discount}%</Badge></div></div></div>
        <div className="drawer-stat-grid"><div><span>游戏售价</span><strong><Price cents={selected.priceCents}/></strong></div><div><span>预计卡牌净回本</span><strong><Price cents={analyses[selected.id]?.estimatedNetCents}/></strong></div><div><span>预计回本率</span><strong className={(analyses[selected.id]?.recoveryRate??-1)>=40?'green-text':(analyses[selected.id]?.recoveryRate??-1)>=30?'normal-text':'muted-text'}>{fmtRate(analyses[selected.id]?.recoveryRate)}</strong></div></div>
        <div className="drawer-section-heading"><strong>普通卡牌列表</strong><span>{selectedCardLoading?'获取中…':`${analyses[selected.id]?.cards.length||0} 张`}</span></div>
        <div className="drawer-explain">{selectedCardLoading?'正在从 Steam Community Market 获取该游戏的普通卡牌和美元报价…':`估算掉落 ${analyses[selected.id]?.expectedDrops||0} 张 · 价格为买家报价，净额为手续费近似估算，不表示一定能卖出。`}</div>
        {selectedCardLoading
          ? <div className="card-loading"><span className="card-loading-spinner"/><strong>正在获取掉落卡牌</strong><small>正在获取卡牌价格，卡牌较多时可能需要 1–2 分钟。</small></div>
          : (analyses[selected.id]?.cards.length||0)>0
            ? <div className="card-price-list">
                <div className="card-price-header"><span>卡牌名字</span><span>最低售价</span><span>到手价</span><span/></div>
                {analyses[selected.id].cards.map((c,i)=>{const cardName=displayCardName(c.name);return <div className="card-price-row" key={i}><div className="card-name-cell"><CardThumb src={c.imageUrl} name={cardName}/><span title={c.name}>{cardName}</span></div><strong className="card-gross"><Price cents={c.grossCents}/></strong><strong className="card-net"><Price cents={c.netCents}/></strong>{c.marketUrl?<a href={c.marketUrl} target="_blank" rel="noreferrer" aria-label="查看 Steam 市场卡牌"><Icon name="external" size={13}/></a>:<span/>}</div>})}
              </div>
            : <Empty title="暂无完整卡牌数据" text={analyses[selected.id]?.note||'弹窗打开时会自动获取 Steam 社区市场普通卡牌掉落池。'}/>
        }
        <p className="drawer-warning"><Icon name="warning" size={15}/>{selectedCardLoading?'未登录状态只能获取游戏掉落池，无法确认当前账号的真实剩余掉落次数。':analyses[selected.id]?.note||'结果仅为估计，不承诺获得或卖出任何卡牌。'}</p>
        <div className="drawer-bottom"><button className="small-button" onClick={()=>void openGame(selected)} disabled={selectedCardLoading}><Icon name="refresh" size={16}/> {selectedCardLoading?'获取中…':'获取 / 刷新掉落卡牌'}</button>{selected.storeUrl&&<a href={selected.storeUrl} target="_blank" rel="noreferrer" className="primary-button">访问 Steam <Icon name="external" size={16}/></a>}</div>
      </div>
    </div>}
    {manualOpen&&<div className="modal-overlay" onMouseDown={()=>setManualOpen(false)}><div className="manual-modal" role="dialog" aria-modal="true" aria-label="添加 Steam 游戏" onMouseDown={e=>e.stopPropagation()}>
      <div className="drawer-top"><span className="eyebrow">ADD STEAM GAME</span><button className="icon-button" onClick={()=>setManualOpen(false)} aria-label="关闭"><Icon name="close"/></button></div>
      <h2>按 AppID 添加 Steam 游戏</h2>
      <p>输入商店 AppID 并读取 Steam 美区 Store 的真实名称、美元价格和折扣。读取失败时，仍可手动填写价格用于分析。</p>
      <label>Steam AppID<input type="number" placeholder="例如：413150" value={manual.appid} onChange={e=>{setManual(p=>({...p,appid:e.target.value}));setManualSteam(null);setManualError('');}}/></label>
      <div className="steam-lookup-row"><button type="button" className="small-button steam-lookup" onClick={lookupSteamApp} disabled={manualLoading||!manual.appid}><Icon name="refresh" size={15}/>{manualLoading?'正在读取 Steam...':'从 Steam 读取'}</button><span>{manualSteam?'Steam Store 数据已读取':'无需 Steam Web API Key'}</span></div>
      {manualSteam&&<div className="steam-read-success"><Icon name="check" size={15}/><span>{manualSteam.title}</span><strong><Price cents={manualSteam.priceCents}/> · -{manualSteam.discount}%</strong></div>}
      <label>游戏名称<input placeholder="例如：Stardew Valley" value={manual.title} onChange={e=>{setManual(p=>({...p,title:e.target.value}));setManualSteam(null);}}/></label>
      <div className="manual-two"><label>购买价格（USD）<input type="number" step="0.01" min="0.01" placeholder="9.99" value={manual.price} onChange={e=>{setManual(p=>({...p,price:e.target.value}));setManualSteam(null);}}/></label><label>折扣（%）<input type="number" min="0" max="99" value={manual.discount} onChange={e=>{setManual(p=>({...p,discount:e.target.value}));setManualSteam(null);}}/></label></div>
      {manualError&&<div className="error-banner">{manualError}</div>}
      <button className="primary-button manual-submit" onClick={addManual} disabled={manualLoading}><Icon name="plus" size={16}/> 添加并进入游戏总览</button>
    </div></div>}
  </>;
}
function Pagination({page,totalPages,totalItems,onChange,disabled}:{page:number;totalPages:number;totalItems:number;onChange:(page:number)=>void;disabled?:boolean}){
  const first=(page-1)*PAGE_SIZE+1;
  const last=Math.min(page*PAGE_SIZE,totalItems);
  const [jumpPage,setJumpPage]=useState(String(page));
  useEffect(()=>setJumpPage(String(page)),[page]);
  const pages:Array<number|'start-gap'|'end-gap'>=[];
  if(totalPages<=7){
    for(let number=1;number<=totalPages;number++)pages.push(number);
  }else{
    pages.push(1);
    if(page>4)pages.push('start-gap');
    for(let number=Math.max(2,page-1);number<=Math.min(totalPages-1,page+1);number++)pages.push(number);
    if(page<totalPages-3)pages.push('end-gap');
    pages.push(totalPages);
  }
  const submitJump=(event:React.FormEvent)=>{
    event.preventDefault();
    const target=Number(jumpPage);
    if(Number.isSafeInteger(target))onChange(Math.max(1,Math.min(totalPages,target)));
  };
  return <nav className="pagination" aria-label="游戏列表分页">
    <span className="pagination-meta">显示 {first}–{last}，共 {totalItems} 款</span>
    <div className="pagination-controls">
      <button type="button" onClick={()=>onChange(page-1)} disabled={disabled||page===1} aria-label="上一页">‹ 上一页</button>
      <div className="pagination-pages">
        {pages.map(item=>typeof item==='number'
          ? <button type="button" key={item} className={item===page?'active':''} onClick={()=>onChange(item)} disabled={disabled} aria-current={item===page?'page':undefined} aria-label={`第 ${item} 页`}>{item}</button>
          : <span className="pagination-gap" key={item}>…</span>
        )}
      </div>
      <button type="button" onClick={()=>onChange(page+1)} disabled={disabled||page===totalPages} aria-label="下一页">下一页 ›</button>
    </div>
    <form className="pagination-jump" onSubmit={submitJump}>
      <span>跳至</span><input type="number" min="1" max={totalPages} value={jumpPage} onChange={event=>setJumpPage(event.target.value)} disabled={disabled} aria-label="输入页码"/><span>页</span><button type="submit" disabled={disabled}>前往</button>
    </form>
  </nav>;
}
function Stat({icon,title,value,foot,tone}:{icon:'grid'|'chart'|'bolt'|'star';title:string;value:string;foot:string;tone:string}){return <div className="stat-card"><div className="stat-top"><span>{title}</span><div className={`stat-icon tone-${tone}`}><Icon name={icon} size={18}/></div></div><div className="stat-value">{value}</div><div className="stat-foot">{foot}</div></div>}
function GameRow({game,analysis,index,saved,onSaved,onClick}:{game:GameDeal;analysis?:Analysis;index:number;saved:boolean;onSaved:()=>void;onClick:()=>void}){
  const a=analysis||emptyAnalysis;
  const rate=a.recoveryRate;
  const [imageFailed,setImageFailed]=useState(false);
  return <div className="game-row" onClick={onClick} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')onClick();}}>
    <div className="game-rank">{String(index+1).padStart(2,'0')}</div>
    <div className={`cover-art ${game.imageUrl&&!imageFailed?'has-image':''}`} style={{background:`linear-gradient(132deg,${patternColors[index%patternColors.length]} 0%,#182946 85%)`}}>
      {game.imageUrl&&!imageFailed
        ? <img className="cover-game-image" src={normalizeSteamImageUrl(game.imageUrl)} alt={`${game.title} 胶囊图`} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={()=>setImageFailed(true)}/>
        : <span className="cover-game-initial">{game.title.slice(0,1)}</span>}
    </div>
    <div className="game-title-cell"><strong title={game.title}>{game.title}</strong><div className="game-subline"><span>APP {game.appid}</span><span>·</span><span>{game.source==='manual'?'手动输入':game.source==='catalog'?'本地游戏库':'Steam Store · US'}</span>{game.canDropCards&&<><span>·</span><span>可掉卡</span></>}</div></div>
    <div className="game-discount"><Badge kind="green">-{game.discount}%</Badge></div>
    <div className="game-price"><strong><Price cents={game.priceCents}/></strong><del><Price cents={game.originalCents}/></del></div>
    <div className="game-recovery"><strong className={(rate??-1)>=40?'green-text':(rate??-1)>=30?'normal-text':'muted-text'}>{fmtRate(rate)}</strong><small>{a.status==='ok'?`预估净额 ${formatMoney(a.estimatedNetCents)}`:a.status==='unscanned'?'尚未查询':a.status==='error'?'接口失败':a.status==='partial'?'数据不完整':'暂无卡牌数据'}</small></div>
    <div className="game-status">{a.status==='ok'&&rate!=null?<Badge kind={rate>=40?'green':rate>=30?'orange':'red'}>{qualityLabel(a)}</Badge>:null}</div>
    <button className={`favorite ${saved?'is-favorite':''}`} aria-label={saved?'取消关注':'添加关注'} onClick={e=>{e.stopPropagation();onSaved();}}><Icon name={saved?'starFill':'star'} size={19}/></button>
    <button className="row-arrow" aria-label="查看详情" onClick={e=>{e.stopPropagation();onClick();}}><Icon name="chevron" size={17}/></button>
  </div>;
}
