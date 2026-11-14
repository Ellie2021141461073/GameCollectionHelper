'use client';

import { useEffect, useState } from 'react';
import { normalizeSteamImageUrl } from '@/lib/steamParse';

type Recommendation = {
  app_id: number;
  name: string;
  summary?: string;
  header_image?: string;
  release_date?: string;
  price?: number;
  genres?: string[];
  tags?: string[];
  match_percent: number;
  vector_score: number;
  bm25_score: number;
  explanation: string;
};

type RecommendResponse = {
  mode: 'search' | 'similar';
  source?: { app_id: number; name: string; summary?: string };
  query?: string;
  results: Recommendation[];
  error?: string;
};

type ServiceStatus = {
  ready: boolean;
  documents?: number;
  vector_size?: number;
  llm_explanations?: boolean;
  error?: string;
};

export default function RecommendationExplorer() {
  const [mode, setMode] = useState<'similar' | 'search'>('similar');
  const [query, setQuery] = useState('Stardew Valley');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [response, setResponse] = useState<RecommendResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/recommender/status', { cache: 'no-store' })
      .then(async result => {
        const data = await result.json();
        setStatus(data);
      })
      .catch(() => setStatus({ ready: false, error: '无法连接推荐服务' }));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (!value || loading) return;
    setLoading(true);
    setError('');
    setResponse(null);
    try {
      const endpoint = mode === 'similar' ? 'similar' : 'search';
      const result = await fetch(`/api/recommender/${endpoint}?q=${encodeURIComponent(value)}&limit=10`, {
        cache: 'no-store',
      });
      const data = await result.json() as RecommendResponse;
      if (!result.ok) throw new Error(data.error || '推荐请求失败');
      setResponse(data);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : String(requestError));
    } finally {
      setLoading(false);
    }
  };

  return <div className="rec-page">
    <section className="rec-hero">
      <div className="rec-kicker">LLM-ENHANCED HYBRID RECOMMENDER · {status?.ready ? `向量库已就绪 · ${status.documents?.toLocaleString() || 0} 款游戏` : status ? '推荐服务未就绪' : '正在检查推荐服务'}</div>
      <h1>挖掘每一份宝藏<span className="heading-mark">✦</span></h1>
      <p>结合精准词匹配与智能语义检索，按质量优排结果，大模型解读每条推荐的匹配依据。</p>

      <div className="rec-tabs">
        <button className={mode === 'similar' ? 'active' : ''} onClick={() => setMode('similar')}>相似游戏搜索</button>
        <button className={mode === 'search' ? 'active' : ''} onClick={() => setMode('search')}>自然语言搜索</button>
      </div>

      <form className="rec-search" onSubmit={submit}>
        <input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder={mode === 'similar' ? '输入游戏名称或 AppID，例如 Dead by Daylight' : '例如：适合两个人玩、轻松、有建造元素'}
        />
        <button disabled={loading || !query.trim()}>{loading ? '混合检索中…' : mode === 'similar' ? '搜索相似游戏' : '搜索相关游戏'}</button>
      </form>

      {status && !status.ready && <div className="rec-warning">
        <strong>推荐数据尚未就绪</strong>
        <span>{status.error || '请先运行 LLM 增强与向量入库脚本。'}</span>
      </div>}
      {error && <div className="rec-error">{error}</div>}
    </section>

    {response?.source && <section className="rec-source">
      <span>当前参照</span>
      <strong>{response.source.name}</strong>
      <small>AppID {response.source.app_id}</small>
    </section>}
    {response?.query && <section className="rec-source">
      <span>搜索意图</span>
      <strong>{response.query}</strong>
    </section>}

    <section className="rec-results">
      {loading && <div className="rec-loading">
        <span className="rec-spinner" />
        <strong>正在综合多维度检索</strong>
        <small>大模型正在整理推荐原因，通常需要数秒。</small>
      </div>}
      {!loading && response?.results.map((item, index) => <article className="rec-card" key={item.app_id}>
        <div className="rec-rank">{String(index + 1).padStart(2, '0')}</div>
        <div className="rec-cover">
          {item.header_image
            ? <img src={normalizeSteamImageUrl(item.header_image)} alt={`${item.name} 封面`} loading="lazy" />
            : <span>{item.name.slice(0, 1)}</span>}
        </div>
        <div className="rec-content">
          <div className="rec-title-row">
            <div>
              <h2>{item.name}</h2>
              <small>AppID {item.app_id}{item.release_date ? ` · ${item.release_date}` : ''}</small>
            </div>
            <strong className="rec-score">{item.match_percent}%</strong>
          </div>
          {item.summary && <p>{item.summary}</p>}
          <div className="rec-tag-list">
            {(item.tags || []).slice(0, 6).map(tag => <span key={tag}>{tag}</span>)}
          </div>
          <div className="rec-explanation">
            <span>推荐原因</span>
            <p>{item.explanation}</p>
          </div>
          <div className="rec-metrics">
            <span>向量 {item.vector_score.toFixed(3)}</span>
            <span>BM25 {item.bm25_score.toFixed(3)}</span>
            <a href={`https://store.steampowered.com/app/${item.app_id}/`} target="_blank" rel="noreferrer">Steam 商店 ↗</a>
          </div>
        </div>
      </article>)}
      {!loading && response && response.results.length === 0 && <div className="rec-empty">没有找到匹配游戏，请调整查询。</div>}
    </section>
  </div>;
}
