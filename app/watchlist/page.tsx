import type { Metadata } from 'next';
import Dashboard from '@/components/Dashboard';

export const metadata: Metadata = {
  title: '关注清单 · GameCollectionHelper',
  description: '查看收藏的 Steam 游戏与卡牌价值。',
};

export default function WatchlistPage() {
  return <Dashboard view="watchlist"/>;
}
