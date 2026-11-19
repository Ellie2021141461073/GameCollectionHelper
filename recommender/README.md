# GameCollectionHelper Recommender

独立于现有卡牌页面的 LLM 增强混合推荐系统。

## 架构

```text
games.csv
  → 清洗与字段修复
  → DeepSeek 标签 + 中文摘要
  → 本地 BGE-M3 Embeddings
  → Qdrant 向量数据库
  → FastAPI（BM25 + 向量 RRF 混合检索 + LLM 推荐解释）
  → Next.js /recommend
```

原有页面 `/`、卡牌接口和卡牌弹窗不参与、不依赖该模块。

## 1. 安装依赖

```powershell
cd E:\GameCollectionHelper
python -m pip install -r recommender\requirements.txt
```

在 `.env.local` 中配置：

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
EMBEDDING_LOCAL_PATH=recommender/data/models/bge-m3
EMBEDDING_CACHE_PATH=recommender/data/embeddings-bge-m3
EMBEDDING_DEVICE=cpu
QDRANT_COLLECTION=steam_games
QDRANT_PATH=recommender/data/qdrant
RECOMMENDER_API_URL=http://127.0.0.1:8000
```

推荐模块不会复用卡牌页面使用的 `OPENAI_API_KEY`。数据增强和推荐解释只读取
`DEEPSEEK_API_KEY`，避免其他功能的额度或 Key 配置混入推荐流程。

如果使用远程 Qdrant，设置 `QDRANT_URL` 和可选的 `QDRANT_API_KEY`。

## 2. 验证数据清洗

```powershell
python -c "from recommender.clean import iter_games; import itertools,json; [print(json.dumps(g.__dict__,ensure_ascii=False,default=str)) for g in itertools.islice(iter_games('games.csv'),5)]"
```

清洗模块会修复原始 CSV 的 39/40 列错位，并解析价格、评论、日期、平台、类型和标签。

## 3. LLM 增强并写入 Qdrant

先用 100 条验证效果与成本：

```powershell
python -m recommender.enrich_qdrant --limit 100 --min-reviews 20
```

扩展到 3 万条，并优先收录评论数最高的游戏：

```powershell
python -m recommender.enrich_qdrant --limit 30000 --min-reviews 20 --order-by reviews --workers 4 --batch-size 32
```

> **为什么建议 `--order-by reviews`**：`games.csv` 的行序基本上是随机的，默认的
> `--order-by file` 取前 N 行，实测 2 万条索引里评论数中位数只有 105，
> 且 Stardew Valley、Cyberpunk 2077 等知名作品都不在其中（Dota 2、CS2 恰好在）。
> 按评论数降序取样后，前 20 名就是 CS2 / PUBG / Dota 2 / GTA V / Terraria …，
> 演示效果与用户直觉一致。

任务会执行：

- DeepSeek Chat Completions 生成标签和中文摘要。
- 本地 Sentence Transformers BGE-M3 生成游戏向量，不需要 Embeddings API 或 OpenAI 额度。
- Qdrant 持久化元数据、摘要、标签和向量。

脚本支持断点续跑，已入库 AppID 会跳过。重建集合：

```powershell
python -m recommender.enrich_qdrant --reset --limit 100 --order-by reviews
```

BGE-M3 模型保存在 `recommender/data/models/bge-m3`。本地嵌入式 Qdrant 同一时间只允许一个进程占用数据库。运行增强脚本前需要停止推荐服务；如需同时读写，请配置远程 `QDRANT_URL`。

### 首次下载 BGE-M3 失败

新版 `huggingface_hub` 默认走 Xet 传输，在部分 Windows 环境会报
`OSError: I/O error ... (os error 5)`。关掉 Xet 后重试即可：

```powershell
$env:HF_HUB_DISABLE_XET = "1"
```

模型缓存在 `EMBEDDING_CACHE_PATH`（默认 `recommender/data/embeddings-bge-m3`），
下载完成后不再重复拉取。


## 4. 启动推荐服务

```powershell
npm.cmd run recommend:api
```

服务地址：

```text
http://127.0.0.1:8000/status
http://127.0.0.1:8000/similar?q=Stardew%20Valley
http://127.0.0.1:8000/search?q=cozy%20farming%20with%20building
```

## 5. 启动网站并访问新页面

```powershell
npm.cmd run dev
```

打开：

```text
http://localhost:3000/recommend
```

## 检索与解释

- 物品相似：源游戏向量 + BM25 词法候选，通过 Reciprocal Rank Fusion 融合。
- 自然语言搜索：查询向量 + BM25 候选，再通过 RRF 融合。
- 质量重排：结合贝叶斯好评率和推荐热度。
- LLM 解释：DeepSeek 一次请求批量解释当前推荐列表；未配置 DeepSeek Key 时自动退回共享标签解释。

## 成本建议

13 万条全部做 DeepSeek 标签和摘要增强会产生大量 Chat API 调用。BGE-M3 向量嵌入完全在本地运行，不产生 Embeddings API 费用。建议先处理 100 条，再处理满足 `review_count >= 20` 的约 3 万条。

## 常见问题

- `Qdrant collection contains no enriched vectors`：数据集尚未增强。配置
  `DEEPSEEK_API_KEY` 后先运行 5 条或 100 条增强命令，并访问 `/status` 确认
  `documents` 大于 0。
- `DEEPSEEK_API_KEY is required`：推荐增强不会回退到 OpenAI。将 DeepSeek Key
  写入 `.env.local` 后重新执行命令。
- 增强时报本地 Qdrant 被占用：先停止 `npm.cmd run recommend:api`，再运行增强；
  服务启动后本地 Qdrant 会持有数据库锁。
- 首次搜索很慢：配置了本地 BGE-M3 时，首次搜索需要将约 2.3 GB 模型载入内存，
  后续请求会复用已载入模型。

## 部署到 GCP Compute Engine

推荐配置为 Ubuntu 22.04/24.04、4 vCPU、16 GB 内存和至少 50 GB 磁盘。
BGE-M3 可以在 CPU 上运行，16 GB 内存更适合同时加载模型和 3 万条向量。

1. 创建 Compute Engine VM，开放 HTTP/HTTPS 防火墙规则。`8000` 仅保留给本机
   Next.js 代理，不直接对公网开放。
2. 使用 SSH 或 `gcloud compute scp` 上传项目，不要上传 `.env.local` 中的任何 Key；
   在服务器上单独创建 `.env.local`。
3. 安装 Node.js 22、Python 3.10+，执行 `npm ci` 和
   `python -m pip install -r recommender/requirements.txt`。
4. 先停止 API，执行少量增强并检查 `/status`，再扩展到 3 万条。使用本地 Qdrant
   时，增强进程和推荐 API 不能同时持有数据库。
5. 执行 `npm.cmd run build`，用 `npm start` 启动网站，用进程管理器或 systemd
   分别托管 Next.js 与 `recommend:api`。
6. 生产环境将 `RECOMMENDER_API_URL` 保持为同机地址
   `http://127.0.0.1:8000`，由 Next.js 的服务端路由访问 FastAPI。
