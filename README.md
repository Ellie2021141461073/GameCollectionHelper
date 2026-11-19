# GameCollectionHelper

一个面向 Steam 游戏收藏爱好者的发现与收藏辅助工具：以游戏筛选、关注收藏为主，以普通卡牌价值分析为辅助，支持 CSV 导出和 LLM 智能推荐。

> **重要：** 游戏总览来自本地 `games.csv`，卡牌和手动 AppID 查询使用 Steam 实时接口。公开接口不保证 Steam 社区市场每次都返回数据。应用不会自动买游戏、出售卡牌或操作 Steam 账号。

## 快速启动

安装 Node.js 22+，在此目录执行：

```bash
npm install
cp .env.example .env.local
npm run dev
```

访问 http://localhost:3000 。总览会自动读取项目根目录的 `games.csv`；无需 Steam Web API Key。

### 获取数据文件

源码仓库不提交约 395 MB 的 `games.csv`。请从 GitHub Releases 下载后放到项目根目录：

```text
GameCollectionHelper/
  games.csv
```

BGE-M3 模型和 Qdrant 向量数据属于可重新生成的运行数据，也不提交到 Git：

- 首次运行推荐服务时，BGE-M3 会从 Hugging Face 下载。
- Qdrant 数据需要运行 `recommender.enrich_qdrant` 重新生成，或从项目发布页单独下载。

## 实时扫描

1. 打开总览后，服务端会读取 `games.csv`，修复原始 CSV 的 39/40 列错位，只保留 `0 < Price < 70 USD` 且 `Categories` 包含 `Steam Trading Cards` 的游戏，并映射为列表需要的原有字段。首次读取后会在当前服务端进程中缓存索引。
2. 也可以点击「按 AppID 添加」，输入 Steam AppID，读取单款游戏的美区价格与折扣。
3. 点击游戏列表行会打开详情弹窗，并自动请求该 AppID 的普通卡牌掉落池；弹窗内也可手动刷新。
4. 每页固定 8 款游戏，筛选、排序和服务端分页保持原有逻辑；可批量获取当前页至多 8 款游戏的掉落卡牌。为避免 Steam 市场限流，请勿高频刷新。

服务端接口：

- `GET /api/steam/app?appid=413150`：优先使用 Steam 美区 Store search，失败时回退 `appdetails`，返回游戏信息与当前 USD 售价。
- `POST /api/deals`：服务端读取本地 `games.csv`，使用现有筛选、排序和分页逻辑，每次只返回指定页的 8 款游戏。价格范围为 `$0–$70`，默认上限 `$10`。
- `GET /api/cards?appid=413150`：获取游戏的普通卡牌列表、每张卡的美元最低报价、挂单数、卡牌套数以及估算掉落张数；闪卡不会进入接口响应。
- `POST /api/cards`，请求体 `{"appid":413150,"priceCents":1499}`：Steam Community Market 卡牌挂单价与 USD 回收估算。

> `games.csv` 的首次加载需要解析约 414 MB 文件，通常耗时数秒；后续分页和筛选使用内存索引。没有找到卡牌不一定代表游戏不支持卡牌：可能是市场限制、地区限制或数据缺失。

Steam Community 在部分 Windows/代理环境中只允许系统网络栈访问，Node 直接连接会超时。Windows 下卡牌请求默认通过无 shell 注入的 PowerShell 子进程访问，Linux 和生产环境使用标准 `fetch`。如需强制 Node 直连，可设置：

```text
STEAM_COMMUNITY_TRANSPORT=direct
```

## 混合推荐系统

工作区使用三个独立路由：`/` 游戏总览、`/watchlist` 关注清单、
`/recommend` 智能推荐。三个页面共享左侧与顶部导航；卡牌接口和卡牌弹窗
不依赖推荐模块。
推荐系统从 `games.csv` 清洗数据，使用 DeepSeek 生成标签和摘要、本地 BGE-M3
生成 1024 维向量，再由 Qdrant 和 BM25 完成混合检索。完整安装、数据增强、
GCP 部署与排错步骤见
[recommender/README.md](recommender/README.md)。

主页的「智能推荐」入口会进入该页面。推荐 Key 只保存在服务端 `.env.local`，
不得使用 `NEXT_PUBLIC_` 前缀或提交到 Git。

## 容器化运行

整套服务可以用 Docker Compose 一键拉起（Qdrant server + FastAPI + Next.js）：

```powershell
docker compose up -d qdrant                    # 向量库
python -m recommender.migrate_qdrant           # 把本地 2 万条向量搬进 server（只需一次）
docker compose up -d --build recommender web   # 应用
```

打开 <http://localhost:3000>，API 在 <http://127.0.0.1:8000/status>。
容器模式下 Qdrant 改为 server 模式（不再有单进程锁限制），嵌入改在 CPU 上跑，
`games.csv` 与 BGE-M3 权重通过只读挂载复用宿主机文件。完整说明、镜像体积、
资源占用与已知限制见 [docs/docker.md](docs/docker.md)。

## 卡牌价值估算（辅助功能）

针对 Steam **普通卡牌**（排除闪卡）：

```text
预计掉落张数 = floor(可见普通卡牌品种数 / 2)
每张卡卖家预计到手 = 买家最低报价 - max($0.01, 5%平台费估算) - max($0.01, 10%发行商费估算)
预计净回收 = 预计掉落张数 × 所有普通卡预估到手价的简单平均数
回收率 = 预计净回收 / 游戏价格 × 100%
```

回收率等级：低于 30% 为“低回收率”，大于等于 30% 且低于 40% 为“中回收率”，大于等于 40% 为“高回收率”。

这是**估算**，不是 Steam 的实际收费规则实现，也不是可实现利润：
- Steam 大多数付费游戏只掉落约半套普通卡牌；闪卡在服务端识别后直接排除，不参与接口返回、掉落张数或回收率计算。具体掉落次数以玩家账号徽章页面为准。
- 匿名接口只能获取“游戏有哪些普通卡牌”和估算掉落张数，无法确认某个 Steam 账号的真实剩余掉落次数；后者需要登录态和徽章数据。
- 真实掉落概率和重复可能性、账户地区、卡牌流动性、买卖挂单、精度与最低手续费会产生偏差。
- 价格来自市场当前买家报价，非保证成交价。低流动性卡牌应谨慎对待。
- 某些游戏可能有交易或掉落限制；未处理免费游戏、钱包限制、交易限制及市场税费等特例。
- 游戏售价与卡牌报价统一使用 Steam 美区 USD；不使用外部汇率换算。
- Steam Wallet 余额不等同于可提现收入。

## 数据来源与接口风险

- [Steam Store Search](https://store.steampowered.com/search/?sort_by=Price_ASC&category1=998&cc=us)：美区公共商店搜索接口；无需 API Key，但不承诺稳定 SLA。
- [Steam Store appdetails](https://store.steampowered.com/api/appdetails?appids=413150&cc=us&l=en)：查询游戏名称、类型与美元售价；`data.type === "game"` 判断游戏本体，`data.categories` 中 `id === 29` 判断支持 Steam 交易卡牌。
- [Steam Community Market](https://steamcommunity.com/market/search?appid=753)：使用只读 `market/search/render` 获取普通卡牌列表，再通过 `priceoverview` 的 `currency=1`（USD）获取真实美元最低报价；服务端主动节流并缓存 5 分钟，遇限流或失败则保留错误状态，不制造数据或使用汇率替代。
- [Steam 官方卡牌说明](https://help.steampowered.com/en/faqs/view/70F3-F690-1013-237F)

## 工程结构

```text
app/
  api/deals/route.ts        games.csv 列表与服务端分页
  api/cards/route.ts        普通卡牌查询、节流与缓存
  api/steam/app/route.ts    Steam Store AppID 查询接口
  api/recommender/          LLM 推荐服务代理
  recommend/page.tsx        LLM 智能推荐页面
  watchlist/page.tsx        关注清单页面
  page.tsx / layout.tsx     Next.js App Router
components/
  Dashboard.tsx            筛选、榜单、详情抽屉与收藏
  RecommendationExplorer.tsx 混合推荐界面
  WorkspaceShell.tsx       共享侧栏、顶栏和工作区布局
  Icons.tsx                自带 SVG 图标组件
lib/
  analysis.ts              纯函数收益计算
  csvCatalog.ts            games.csv 流式解析与缓存索引
  steam.ts                 Steam Store / Community Market 服务端适配层
  types.ts                 数据模型
recommender/
  text.py                  分词与停用词（仅标准库）
  ranking.py               BM25、质量先验与 RRF 融合（仅标准库）
  clean.py                 games.csv 清洗与 39/40 列错位修复
  dataset_stats.py         数据集统计
  store.py / embeddings.py / chat.py   Qdrant、BGE-M3、DeepSeek 适配
  service.py               FastAPI 路由层
tests/
  math.test.mjs            前端纯函数单测
  python/                  Python 单测与 API 契约测试
scripts/bootstrap.ps1      一键环境初始化
```

分层规则、依赖方向与「新代码放哪里」的对照表见
[docs/project-structure.md](docs/project-structure.md)。

## 开发与测试

首次准备环境（建 `.venv`、装依赖、跑冒烟测试）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

日常检查：

```bash
npm run check            # typecheck + ruff + 前端单测 + Python 单测
npm run typecheck        # 仅 TypeScript 类型检查
npm test                 # 仅前端单测（tests/*.test.mjs）
npm run test:py           # 仅 Python 单测（tests/python）
npm run lint:py           # 仅 ruff
npm run test:acceptance   # 验收测试（需服务已启动，见下）
npm run data:stats        # 打印 games.csv 规模统计
npm run build             # 生产构建
```

### 验收测试

`scripts/acceptance_test.py` 按选题 Topic 1 的 5 项关键任务逐条校验运行中的系统，
每条检查都标注了它对应的要求编号（R1 数据采集 / R2 特征增强 / R3 数据管理 /
R4 混合检索 / R5 解释生成），另外覆盖错误码与延迟：

```powershell
docker compose up -d                          # 或本地 npm run recommend:api + npm run dev
python scripts/acceptance_test.py             # 全部通过时退出码为 0
python scripts/acceptance_test.py --verbose   # 打印样例数据与每步细节
```

脚本只用标准库，不需要安装任何依赖；`--skip-web` 可跳过 Next.js 相关检查。

`recommender/` 的 `text.py`、`ranking.py`、`clean.py`、`dataset_stats.py` 只依赖标准库，
不安装 torch 也能跑测试；API 契约测试在缺少 fastapi 时会自动跳过。
脚本执行前请先激活虚拟环境：`.\.venv\Scripts\Activate.ps1`。

## 项目归属说明

本仓库代码为 GameCollectionHelper。第三方框架和 API 的版权分别归属原项目。若未来实际使用了商业模板、开源项目或付费图形素材，应附上相应许可证和署名。项目目前不连接任何 Steam 账号，不收集任何个人 Steam 凭证。
