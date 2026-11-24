# 项目结构（Project Structure）

本文档说明 `GameCollectionHelper` 的分层方式、依赖方向与代码放置规则。
新增代码前先读第 3 节的「放哪里」对照表。

---

## 1. 目录总览

```text
GameCollectionHelper/                  Git 仓库根（= WORKPLACE/）
├── app/                               Next.js App Router（页面与 API 路由）
│   ├── api/
│   │   ├── cards/route.ts             普通卡牌查询（Steam Community Market）
│   │   ├── deals/route.ts             games.csv 列表与服务端分页
│   │   ├── recommender/               推荐服务代理：_proxy.ts + search/similar/status
│   │   └── steam/app/route.ts         Steam Store AppID 查询
│   ├── recommend/page.tsx             /recommend 智能推荐页
│   ├── watchlist/page.tsx             /watchlist 关注清单页
│   ├── page.tsx  layout.tsx           首页与根布局
│   ├── globals.css  steam.css         全局样式
│   └── recommend/recommend.css        推荐页样式
├── components/                        React 客户端组件
│   ├── Dashboard.tsx                  总览：筛选、榜单、详情抽屉、收藏
│   ├── RecommendationExplorer.tsx     混合推荐界面
│   ├── WorkspaceShell.tsx             共享侧栏 / 顶栏 / 工作区布局
│   ├── CardThumb.tsx  Icons.tsx       缩略图与内联 SVG 图标
├── lib/                               前端与服务端共用的纯 TS 模块
│   ├── analysis.ts                    收益计算纯函数
│   ├── csvCatalog.ts                  games.csv 流式解析与进程内缓存索引
│   ├── dealPagination.ts              筛选 / 排序 / 分页纯函数
│   ├── steam.ts  steamParse.ts        Steam 接口适配与 HTML/价格解析
│   ├── steamCommunityHttp.ts          Windows PowerShell 传输回退
│   ├── http.ts                        请求工具
│   └── types.ts                       数据模型
├── recommender/                       Python 推荐服务
│   ├── text.py                        ① 分词与停用词（纯函数，仅标准库）
│   ├── ranking.py                     ② BM25 / 质量先验 / RRF 融合（纯函数，仅标准库）
│   ├── clean.py                       games.csv 清洗与 39/40 列错位修复（仅标准库）
│   ├── selection.py                   增强取样：按评论数挑选候选（仅标准库）
│   ├── dataset_stats.py               数据集统计（仅标准库，装依赖前即可跑）
│   ├── store.py                       ③ Qdrant 客户端与 payload 组装
│   ├── embeddings.py                  ③ BGE-M3 向量（懒加载 sentence-transformers）
│   ├── chat.py                        ③ DeepSeek / OpenAI 兼容客户端
│   ├── enrich_qdrant.py               离线增强流水线（LLM 标签 + 摘要 + 向量入库）
│   ├── migrate_qdrant.py              把嵌入式库搬到 Qdrant server（③，一次性运维）
│   ├── service.py                     ④ FastAPI 路由层
│   ├── smoke_test.py                  需要完整运行栈的端到端冒烟脚本
│   └── requirements.txt               运行期依赖
├── tests/
│   ├── math.test.mjs                  前端纯函数单测（node --test）
│   └── python/                        Python 单测（unittest）
│       ├── test_clean.py  test_text.py  test_ranking.py     仅标准库
│       ├── test_selection.py          取样逻辑（仅标准库）
│       └── test_service_api.py        FastAPI 契约测试（无 fastapi 时自动 skip）
├── scripts/
│   ├── bootstrap.ps1                  一键环境初始化
│   └── acceptance_test.py             验收测试（按题目 5 项要求逐条校验，仅标准库）
├── docker/
│   ├── recommender.Dockerfile         Python 3.12 + CPU torch + FastAPI
│   └── web.Dockerfile                 Next.js 三阶段构建
├── docker-compose.yml                 qdrant + recommender + web 编排
├── .dockerignore                      构建上下文排除（数据、密钥、缓存）
├── docs/
│   ├── gap-analysis.md                当前缺口与补齐清单
│   ├── docker.md                      容器化运行说明
│   └── project-structure.md           本文件
├── .github/workflows/ci.yml           CI：web / python-unit / python-api
├── pyproject.toml                     ruff 与 coverage 配置
├── requirements-dev.txt               仅 lint 与测试所需依赖
├── .editorconfig  .gitattributes      utf-8 + LF 约定
├── package.json                       npm 脚本入口
└── .env.example / .env.local          配置模板 / 本地真实配置（不提交）
```

不入库的运行期数据（见 `.gitignore`）：

```text
games.csv                                  395 MiB 原始数据
recommender/data/qdrant/                   向量库（本地 Qdrant 单进程模式）
recommender/data/models/bge-m3/            BGE-M3 模型权重
recommender/data/embeddings-bge-m3/        Hugging Face 缓存
```

---

## 2. 依赖方向（唯一需要守住的原则）

```text
app/ ─────────────► lib/                    （页面与路由只能用 lib 的纯函数）
app/api/recommender ──HTTP──► recommender/service.py

service.py ──► ranking.py, text.py, clean.py, store.py, embeddings.py, chat.py
enrich_qdrant.py ──► clean.py, selection.py, store.py, embeddings.py, chat.py
migrate_qdrant.py ──► store.py（仅读常量）

ranking.py / text.py / clean.py / selection.py / dataset_stats.py
    ↑ 只允许标准库，禁止 import qdrant_client / openai / fastapi / torch
```

规则与理由：

1. **纯逻辑层（`text` / `ranking` / `clean` / `selection` / `dataset_stats`）不得引入第三方依赖。**
   这是 `npm run test:py` 能在没有 torch、没有 Qdrant 的机器上跑完的原因，
   也是 CI 的 `python-unit` job 故意不执行 `pip install` 的原因。
2. **I/O 层（`store` / `embeddings` / `chat`）只做外部系统适配**，
   不写业务排序逻辑，方便在测试里整体 mock。
3. **`service.py` 只做「解析入参 → 调用纯函数 → 拼响应」**，不再自己实现算法。
   历史上 BM25 与 RRF 都写在这个文件里，导致无法单测，已重构到 `ranking.py`。
4. **`embeddings.py` 懒加载 sentence-transformers**：模块 import 不应该拉起 torch，
   否则 `service` 的契约测试也必须安装 2.5 GB 依赖。

---

## 3. 新代码放哪里

| 你要加的东西 | 放这里 | 备注 |
| --- | --- | --- |
| 新的检索 / 排序 / 融合算法 | `recommender/ranking.py` | 纯函数，必须能进 `test_ranking.py` |
| 新的分词或归一化规则 | `recommender/text.py` | 改完同步更新 `test_text.py` |
| 新的 CSV 字段解析 | `recommender/clean.py` | 注意 39 表头 / 40 值的列错位 |
| 新的外部服务调用（DB、模型、HTTP） | `recommender/` 下的新模块 | 不要写进 `service.py` |
| 新的 HTTP 路由 | `recommender/service.py` | 业务逻辑留在纯函数里 |
| 新的前端页面 | `app/<route>/page.tsx` | 布局复用 `components/WorkspaceShell.tsx` |
| 新的 Next.js API 路由 | `app/api/<name>/route.ts` | 与 Python 服务交互时复用 `app/api/recommender/_proxy.ts` |
| 前端纯计算逻辑 | `lib/*.ts` | 纯函数，配套 `tests/*.test.mjs` |
| 一次性运维脚本 | `scripts/` | SQL / 迁移 / 批处理，不要放 Python 包内 |
| 说明文档 | `docs/` | 不要堆在仓库根目录 |

---

## 4. 数据流

```text
games.csv
  │  recommender.clean.iter_games()        修复 39/40 列错位、过滤 demo 与低评论数
  ▼
CleanGame
  │  recommender.enrich_qdrant               DeepSeek 生成 llm_tags + 中文 summary
  │                                          BGE-M3 生成 1024 维向量
  ▼
Qdrant 集合 steam_games（payload 含全部结构化元数据）
  │  recommender.service.load_state()        一次性读入内存，构建 BM25 倒排索引
  ▼
/similar?q=…   →  向量 top-50 + BM25 top-50  →  RRF(k=60) + 质量先验  →  LLM 解释
/search?q=…    →  查询向量 top-50 + BM25 top-50 →  同上
  ▼
app/api/recommender/*  （Next.js 服务端代理）  →  /recommend 页面
```

`/`（总览）与 `/watchlist` 只依赖 `games.csv` 与 Steam 实时接口，**不依赖推荐服务**，
推荐服务挂掉不影响卡牌与总览功能。

---

## 5. 常用命令

| 命令 | 作用 |
| --- | --- |
| `powershell -File scripts\bootstrap.ps1` | 建 `.venv`、装 dev 依赖、装 npm 包、跑冒烟测试 |
| `npm run check` | typecheck + ruff + 前端单测 + Python 单测（四项全绿才算通过） |
| `npm run test:py` / `npm run lint:py` | 单独跑 Python 单测 / ruff |
| `npm run data:stats` | 打印 `games.csv` 规模统计（仅标准库） |
| `npm run recommend:enrich -- --limit 100` | 小批量验证 LLM 增强 |
| `npm run recommend:api` / `npm run dev` | 启动 FastAPI（:8000）与 Next.js（:3000） |

> 本地 Qdrant 是单进程模式：跑 `recommend:enrich` 前必须先停掉 `recommend:api`。
