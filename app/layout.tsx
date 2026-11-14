import type { Metadata } from 'next';
import WorkspaceShell from '@/components/WorkspaceShell';
import './globals.css';
import './steam.css';
export const metadata: Metadata = {
  title: 'GameCollectionHelper',
  description: 'Steam 游戏发现、关注收藏与卡牌价值参考。',
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="zh-CN"><body><WorkspaceShell>{children}</WorkspaceShell></body></html>;
}
