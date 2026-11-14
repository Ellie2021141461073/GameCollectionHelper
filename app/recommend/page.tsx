import type { Metadata } from 'next';
import RecommendationExplorer from '@/components/RecommendationExplorer';
import './recommend.css';

export const metadata: Metadata = {
  title: '智能推荐 · GameCollectionHelper',
  description: '基于 BM25、向量检索和 LLM 解释的 Steam 游戏混合推荐系统。',
};

export default function RecommendPage() {
  return <RecommendationExplorer />;
}
