'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import Icon from './Icons';

type WorkspaceCounts = {
  overview?: number;
  watchlist?: number;
};

const routeTitles: Record<string,string> = {
  '/': '游戏总览',
  '/watchlist': '关注清单',
  '/recommend': '智能推荐',
};

export default function WorkspaceShell({children}:{children:React.ReactNode}){
  const pathname=usePathname();
  const route=routeTitles[pathname]?pathname:'/';
  const [counts,setCounts]=useState<WorkspaceCounts>({});

  useEffect(()=>{
    const readStoredCounts=()=>{
      try{
        const favorites=JSON.parse(localStorage.getItem('cardscout-favorites-v1')||'[]');
        if(Array.isArray(favorites))setCounts(current=>({...current,watchlist:favorites.length}));
      }catch{}
    };
    const updateCounts=(event:Event)=>{
      const detail=(event as CustomEvent<WorkspaceCounts>).detail;
      if(!detail)return;
      setCounts(current=>({
        overview:detail.overview??current.overview,
        watchlist:detail.watchlist??current.watchlist,
      }));
    };
    readStoredCounts();
    window.addEventListener('storage',readStoredCounts);
    window.addEventListener('gch:workspace-counts',updateCounts);
    return ()=>{
      window.removeEventListener('storage',readStoredCounts);
      window.removeEventListener('gch:workspace-counts',updateCounts);
    };
  },[]);

  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" href="/">
        <span className="brand-icon"><Icon name="bolt" size={23}/></span>
        <span className="brand-name">游戏收藏助手</span>
      </Link>
      <div className="sidebar-caption">WORKSPACE</div>
      <nav className="side-nav" aria-label="主导航">
        <Link className={`nav-button ${route==='/'?'selected':''}`} href="/"><Icon name="grid"/>游戏总览</Link>
        <Link className={`nav-button ${route==='/watchlist'?'selected':''}`} href="/watchlist"><Icon name="star"/>关注清单<span className="nav-count">{counts.watchlist??0}</span></Link>
        <Link className={`nav-button ${route==='/recommend'?'selected':''}`} href="/recommend"><Icon name="sparkles"/>智能推荐</Link>
      </nav>
      <div className="sidebar-bottom">
        <div className="assistant-teaser"><div className="assistant-badge"><Icon name="sparkles" size={17}/></div><strong>智能游戏推荐</strong><p>智能语义检索，大模型作出推荐。</p><Link href="/recommend" className="primary-button recommend-entry">打开智能推荐 <Icon name="arrow" size={15}/></Link></div>
        <div className="side-footer"><span className="online-dot"/> STEAM GAME DISCOVERY <span>v0.1</span></div>
      </div>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="breadcrumbs"><span>WORKSPACE</span> <Icon name="chevron" size={13}/> <span>{routeTitles[route]}</span></div>
        <div className="top-actions"><span className="top-note"><Icon name="shield" size={15}/><span>仅分析 · 不自动购买</span></span><Link className="icon-button" href="/recommend" aria-label="打开智能推荐" title="打开智能推荐"><Icon name="sparkles" size={19}/></Link><div className="avatar">AD</div></div>
      </header>
      <main className={route==='/recommend'?'content recommend-content-shell':'content'}>{children}</main>
    </div>
  </div>;
}
