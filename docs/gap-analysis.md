# WORKPLACE 缺口分析（Gap Analysis）

> 生成时间：基于当前 `WORKPLACE/` 实测数据（下文所有数字均为实测，不是估算）。
> 对应课程要求：`CS5481` 项目，选题 **Topic 1 — LLM-Enhanced Hybrid Recommendation System**（中文译文见 `../../FILE/CS5481_Project_2026-1.zh.md`）。
> 对应参考实现：远程仓库 `https://github.com/Ellie2021141461073/GameCollectionHelper`（已拉取到本目录）。

---

## 0. 结论速览（TL;DR）

**好消息**：三大核心资产（数据、向量库、代码）都已具备，Topic 1 的 5 项关键任务在**实现层面**已经全部打通：

- `games.csv` 有 **13.01 万**行，其中 **45,936** 款游戏同时满足「评论数 ≥ 20」且「描述非空」，远超题目要求的 20,000 条下限。
- Qdrant 中已有 **20,000** 条**已完成 LLM 增强**的向量（1024 维、平均 10.5 个标签、中文摘要 0 条缺失）。
- 代码侧 BM25 + 向量 RRF 混合检索、LLM 解释、FastAPI + Next.js 前后端均已实现。

**必须补的东西集中在三处**：

1. **🔴 环境跑不起来**——没有 `node_modules`、没有 Python 虚拟环境（`fastapi`/`torch`/`sentence-transformers` 全缺）、BGE-M3 模型未下载，且 `.env.local` 指定 `EMBEDDING_DEVICE=cuda` 但机器上没有 CUDA 版 PyTorch。
2. **🟠 报告要的「实验与讨论」几乎没有素材**——没有评测集、没有消融实验、没有延迟基准、没有「增强前 vs 增强后」对比。题目明确要求报告含 experiments and discussions，这部分目前是空白。
3. **🟠 提交物缺失**——没有报告、没有幻灯片、没有**全体签名的贡献声明页**（缺这一页会 **desk reject**）；README 让用户去 GitHub Releases 下 `games.csv`，但**仓库 0 个 Release**。

下面逐项给出证据与补齐方案。

---

## 1. 现状盘点（实测）

### 1.1 目录结构

```text
PROJECT/
  FILE/
    CS5481_Project_2026-1.pdf         课程要求原文（7 页）
    CS5481_Project_2026-1.zh.md       中文全文翻译（本次生成）
  WORKPLACE/                          ← Git 仓库根目录（origin 已接远程）
    .git/                             本次初始化，main 跟踪 origin/main
    .env.local                        ← 含真实 API Key，已被 .gitignore 排除
    .env.example                      模板（来自远程）
    games.csv                         414.5 MB，已被 .gitignore 排除
    app/ components/ lib/ tests/      Next.js 15 + React 19 前端（来自远程）
    recommender/                      FastAPI + BGE-M3 + BM25 推荐服务（来自远程）
      data/                           ← 已被 .gitignore 排除（本地运行数据）
        qdrant/                       Qdrant 本地库：meta.json + collection/steam_games
    README.md  package.json  tsconfig.json  next.config.ts
```

> 本次已做的结构修正：原来向量库在 `WORKPLACE/qdrant/qdrant/`，但 `.env.local` 与三份文档都写着 `QDRANT_PATH=recommender/data/qdrant`，路径不一致会导致服务启动后**读不到集合**。现已移动到 `recommender/data/qdrant/`，并清除了过期的 `.lock`。

### 1.2 `games.csv` 实测

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 文件大小 | 414,500,269 B ≈ **395 MiB** | 超过 GitHub 单文件 100 MB 上限 → 不能入库 |
| 数据行数 | **130,100** | AppID 无重复 |
| 每行字段数 | **40 个值** | 但表头只有 **39 个标签** → 列错位（见 §2.1） |
| `About the game` 非空 | 121,343（93.3%） | 空值 8,757（6.7%） |
| 评论数 ≥ 20 | **46,018** | 推荐系统可用的「有效池」 |
| ≥20 评论 **且** 描述非空 | **45,936** | 这才是「有丰富描述」的可用集 |
| 描述 ≥ 200 字符 | 45,615 | |
| 描述 ≥ 1000 字符 | **28,310** | 高质量长描述子集 |
| 含 `Steam Trading Cards` | 11,765 | 卡牌功能相关 |
| 免费游戏（Price = 0） | 27,592 | |

**关键结论**：题目要求「至少 20,000 个物品 + 丰富描述」。当前已入库 20,000 条 ≈ 可用池（45,936）的 **43.5%**，还有 **2.5 万条**可扩展空间（README 里建议的 3 万条目标是合理的）。

### 1.3 Qdrant 向量库实测

| 指标 | 实测值 |
| --- | --- |
| 集合名 | `steam_games` |
| 点数 | **20,000** |
| 向量维度 / 距离 | 1024 / Cosine |
| `storage.sqlite` 大小 | 306,327,552 B ≈ **292 MiB** |
| 带 `llm_tags` 的点 | 20,000（**0 条缺失**） |
| 平均标签数 | **10.53** 个/条 |
| 带中文 `summary` 的点 | 20,000（**0 条空摘要**） |
| 增强来源 | `BAAI/bge-m3` + `CS5351/DeepSeek-V4-Flash` |
| 关键 payload 字段 | `app_id, name, summary, llm_tags, source_tags, genres, search_text, positive, negative, review_count, price, release_date, ...` |

**结论**：Topic 1 的「Feature Enrichment」与「Data Management」在数据层面**已经完成**，不是待办项。

### 1.4 运行环境实测

| 依赖 | 状态 | 结论 |
| --- | --- | --- |
| Node.js | v24.15.0 | ✅ 满足 README 的 22+ |
| npm | 11.12.1 | ✅ |
| `node_modules/` | **不存在** | 🔴 需 `npm install` |
| 系统 Python | **3.14.7** | 🔴 过新，`torch` / `sentence-transformers` 无对应 wheel |
| 独立 Python venv | **不存在** | 🔴 `fastapi`、`qdrant-client`、`openai` 均未安装 |
| GPU | **RTX 4060 Laptop** | ✅ 硬件具备，但缺 CUDA 版 PyTorch |
| BGE-M3 模型 | **不存在**（`recommender/data/models/bge-m3` 无文件） | 🟠 首次运行需从 HF 下载约 2.3 GB |
| `recommender/data/embeddings-bge-m3` 缓存 | **不存在** | 🟠 同上 |

### 1.5 Git 状态

- 本地仓库：本次已 `git init -b main`，`origin` 已指向 `https://github.com/Ellie2021141461073/GameCollectionHelper`，`main` 已跟踪 `origin/main`，代码文件已从远程完整拉取（46 个跟踪文件，工作区干净）。
- 远程仓库：`main` / `dev` / `feature-c` / `feature-f` / `feature-z` **5 个分支全部指向同一个 commit `3ad81a8`**（只有一次 "Initial commit"）。
- 远程 **Release 数量 = 0**，仓库 **无 LICENSE**、无仓库描述。
- `.gitignore` 已强化：`games.csv`、`.env.local`、`recommender/data`、`*.sqlite`、`qdrant/` 等全部排除（`git check-ignore` 已验证）。

---

## 2. 关键发现详解

### 2.1 🔴 原始 CSV 存在 39/40 列错位（已由代码兜底，但报告必须写明）

表头第 7 个标签 `DiscountDLC count` 实际对应**两个**字段（`Discount` 与 `DLC count`），因此：

- 表头 **39** 个标签 vs 数据行 **40** 个值；
- 任何「按表头名取列」的读法（例如 `pandas.read_csv` + `df["About the game"]`、或 Python `csv.DictReader`）都会**整体错位一列**，把 `About the game` 读到 `Full audio languages` 的位置。

**实测佐证**：按表头名解析时「描述为空」被算成 **111,519 条（85.7%）**；按 `clean.py` 的 40 列映射解析时实际只有 **8,757 条（6.7%）**。差了 **10 万条**。

现状：`recommender/clean.py` 已内置 40 列常量 `CSV_COLUMNS` 修正，代码正确。**但这必须在报告的 Methodology 里写一段**——这是数据工程的实质工作量，且是评分点。

### 2.2 🟠 已增强只覆盖 43.5%，规模实验缺一环

- 20,000 / 45,936 = 43.5%。
- 报告如果想论证「LLM 增强的开销与收益随规模变化」，就需要至少两组规模（例如 20k vs 30k）对比。当前只有一组。

### 2.3 🟠 没有任何评测集与量化实验

代码里有 `recommender/smoke_test.py`，但它只验证「接口能通、返回非空」（3 条假数据、断言 status=200），**不是评测**。题目报告必须有 experiments and discussions，而目前缺：

- 查询集（自然语言查询 + 人工标注的相关物品）；
- 检索指标（Recall@k / NDCG@10 / MRR）；
- 三种检索模式对照：**纯 BM25** vs **纯向量** vs **RRF 混合**；
- RRF 融合参数 `k`、候选数、`k1`/`b` 的敏感性；
- 延迟基准：冷启动（首次加载 2.3 GB 模型）vs 热启动，P50 / P95；
- **LLM 增强前后**的检索质量差异（用原始 `search_text` 做 baseline）。

### 2.4 🟠 LLM Key 与网关依赖

`.env.local` 中：

```text
DEEPSEEK_BASE_URL=https://llm.cs.cityu.edu.hk/v1
DEEPSEEK_MODEL=CS5351/DeepSeek-V4-Flash
```

- 现有 20,000 条增强数据**依赖校内网关**生成，换到公网 `api.deepseek.com` 后模型名与输出会不一致 → 属不可复现风险，报告需说明「增强数据不可在无该网关时重跑」。
- `.env.local` 内含**真实 Key 明文**。虽然已被 `.gitignore` 排除（已用 `git check-ignore` 验证），但该 Key 曾出现在终端输出中，**建议轮换**，并在报告中说明 Key 只放服务端、且用 `.env.local` 而非 `NEXT_PUBLIC_*`。

### 2.5 🟠 README 指向不存在的 Release

`README.md` 第 21 行写「源码仓库不提交约 395 MB 的 `games.csv`。请从 GitHub Releases 下载」，但实测**远程 Release 数为 0**。助教或组员克隆后无数据可跑，属于交付物断链。

### 2.6 🟠 提交物三件套全缺

| 提交物 | 状态 |
| --- | --- |
| 项目报告（引言 / 方法 / 实验与讨论，正文 ≤ 6 页） | ❌ 不存在 |
| 15 分钟展示幻灯片（附在报告末尾） | ❌ 不存在 |
| 贡献声明 + 全体签名页（正文最后一页，不计入 6 页） | ❌ 不存在 → **缺失即 desk reject** |

另外 2026-10-18 的分组 deadline 与 2026-11-24 的提交 deadline 需要有组内排期。

### 2.7 🟡 工程化缺口

| 项 | 状态 | 影响 |
| --- | --- | --- |
| Python 侧单元测试 | ❌ 无（`tests/` 只测 TS 的 `lib/`） | 清洗逻辑回归无保护 |
| `requirements.txt` 版本锁定 | 仅 `>=`/`<` 区间 | 复现性弱；建议导出 `requirements.lock` |
| Dockerfile / 部署脚本 | ❌ 无 | 附录里的 GCP 部署只能手写 |
| CI（GitHub Actions） | ❌ 无 | typecheck/build/test 靠手动 |
| LICENSE / 数据来源声明 | ❌ 无 | `games.csv` 来自 Steam 抓取数据（Kaggle 类数据集），报告需注明来源与许可 |
| 分支策略 | 5 分支同一 commit | 建议 `feature-*` → `dev` → `main` |
| Qdrant 并发限制 | 本地模式单进程锁 | 增强脚本与 API 不能同时跑（README 已提示） |
| `.gitattributes` | ❌ 无 | CRLF/大文件属性未规范 |

---

## 3. Topic 1 要求覆盖度矩阵

| # | 题目要求 | 实现状态 | 缺口 |
| --- | --- | --- | --- |
| 1 | 爬取清洗 **≥20,000** 条含丰富描述的物品 | 🟢 45,936 条可用，20,000 条已入库 | 报告需写清洗口径与列错位修复 |
| 2 | LLM 生成**结构化标签 + 摘要 + 向量** | 🟢 20,000 条全部完成 | 缺增强成本/耗时统计（token、调用次数） |
| 3 | 原始数据 + 元数据 + 向量存入**合适数据库** | 🟢 Qdrant（payload 含结构化元数据） | 需在报告中论证「为何不用 pgvector」；建议补一张存储层字段设计表 |
| 4 | 混合检索：**按 ID 找相似** + **自然语言查询**（BM25 + 向量） | 🟢 两者都已实现（RRF 融合） | 缺量化效果证明 |
| 5 | 每个结果生成**LLM 解释** | 🟢 已实现，且有「无 Key 时回退到标签解释」 | 缺解释质量的定性抽样展示 |
| 6 | （题目强调的）**低延迟** | 🟡 架构上具备（内存 BM25 + Qdrant 本地） | ❌ **完全没有测** |

---

## 4. 补齐清单（按优先级）

### 🔴 P0 —— 让系统能跑起来（预计 1–2 小时，主要耗时在下载）

1. **建 Python 3.11/3.12 虚拟环境**（不要用系统 3.14，`torch` 无 wheel）：

   ```powershell
   cd WORKPLACE
   py -3.12 -m venv .venv          # 若无 3.12，用 3.11
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r recommender\requirements.txt
   ```

2. **装 CUDA 版 PyTorch**（`.env.local` 写的是 `EMBEDDING_DEVICE=cuda` + `float16`，缺 CUDA 版 torch 会直接抛
   `EMBEDDING_DEVICE requests CUDA, but the installed PyTorch has no available CUDA device`）：

   ```powershell
   python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
   ```

   > 若只想先跑通，也可以把 `.env.local` 改成 `EMBEDDING_DEVICE=cpu` / `EMBEDDING_DTYPE=float32`。

3. **前端依赖**：

   ```powershell
   npm install
   npm run typecheck
   ```

4. **首次检索会下载 BGE-M3（约 2.3 GB）** 到 `recommender/data/embeddings-bge-m3`；建议提前手动预热一次。

5. **启动顺序**（本地 Qdrant 是单进程锁，必须先停 API 再跑增强）：

   ```powershell
   npm run recommend:api      # FastAPI :8000
   npm run dev                # Next.js :3000 → /recommend
   ```

6. **冒烟验证**：`http://127.0.0.1:8000/status` 应返回 `documents: 20000`、`vector_size: 1024`。

### 🟠 P1 —— 报告与实验必需（这是最大工作量，直接决定分数）

1. **建评测集**：新建 `recommender/eval/`，
   - `queries.jsonl`：**≥30 条**自然语言查询（例：`"a relaxing video game with beautiful art but no combat"`），每条标注 5–10 个相关 AppID（可先用 LLM 粗标 + 人工抽查）。
   - 另加 **≥20 组**「物品→相似物品」对，用于 item-item 推荐评测。
2. **建基准脚本** `recommender/evaluate.py`：
   - 三种模式对照：`bm25 only` / `vector only` / `rrf hybrid`；
   - 指标：Recall@5、Recall@10、NDCG@10、MRR；
   - 消融：`rrf_k ∈ {10, 60, 100}`、BM25 `k1/b`、候选数；
   - 基线：`llm_tags/summary` 置空（只用原始 `search_text`）→ 证明 **LLM 增强有用**。
3. **延迟基准**：冷启动（模型加载）与热启动分别测 P50/P95/P99，至少 100 次查询；结果直接进报告的 latency 表。
4. **规模实验**：把增强集从 20,000 扩到 30,000（`--limit 30000 --min-reviews 20`），对比召回质量与构建耗时。
5. **写报告**：引言 / 方法 / 实验与讨论 + 参考文献（题目给了 3 篇，必引；另补 BGE-M3、Qdrant、RRF 原论文）+ 附录（代码结构、运行说明、提示词全文）。
6. **做 15 分钟幻灯片**：建议 12 页（问题 → 架构图 → 数据 → 清洗 → 增强 → 混合检索 → 解释 → 实验表 → 消融 → 局限 → 展望）。
7. **贡献声明页**：单独一页，列每个人的贡献与百分比，**全员手写签名**，放在正文最后一页、幻灯片之前。

### 🟡 P2 —— 工程与交付质量

1. 补 `LICENSE`（如 MIT）与「数据来源与许可」段落（`games.csv` 出处、抓取时间、字段含义）。
2. 补 `docs/`：架构图、字段字典、提示词存档、API 示例响应。
3. 补 Python 测试：`tests/test_clean.py`（列错位、日期/价格解析、列表解析）、`tests/test_service.py`（RRF 融合、tokenize 中英文）。
4. `requirements.txt` 导出锁定版本（`pip freeze > requirements.lock`）。
5. 加 `Dockerfile` + `docker-compose.yml`（Next.js + FastAPI + Qdrant server 模式），解决单进程锁问题。
6. 加 GitHub Actions：`npm run typecheck && npm run build && npm test`。
7. **发布 Release 并上传 `games.csv` 与 `qdrant` 数据包**，让 README 的第 21 行不再是死链。
8. 分支规范：`feature-*` → `dev` → `main`；当前 5 个分支同一 commit，需要真实分工 commit。
9. 补 `.gitattributes`（`* text=auto`、`*.csv binary`）。
10. **轮换 `.env.local` 中的 API Key**，并在 `.env.example` 里明确「必须使用校内网关还是公网」。

---

## 5. 建议执行顺序

```text
① P0 环境（venv + CUDA torch + npm install + 预热模型）
      ↓ 能启动、/status 显示 20000
② P1-1/P1-2 评测集 + evaluate.py  ← 最关键，报告的核心素材
      ↓ 拿到 BM25 / 向量 / RRF 三组指标
③ P1-3/P1-4 延迟基准 + 3 万条规模实验
      ↓
④ P1-5/P1-6/P1-7 报告 → 幻灯片 → 贡献声明页
      ↓
⑤ P2 工程收尾（License / docs / tests / Release / CI）
```

---

## 6. 本次已完成的操作

| # | 操作 | 结果 |
| --- | --- | --- |
| 1 | 解析并翻译课程 PDF（7 页） | 生成 `FILE/CS5481_Project_2026-1.zh.md` |
| 2 | 在 `WORKPLACE/` 初始化 Git 仓库（`main` 分支） | `.git/` 已建立 |
| 3 | 连接远程 `origin` 并拉取全部 5 个分支 | 46 个跟踪文件已落地 |
| 4 | 设置 `main` 跟踪 `origin/main` | `git branch -vv` 可验证 |
| 5 | 修正 Qdrant 路径：`qdrant/qdrant/` → `recommender/data/qdrant/` | 与 `.env.local` 及三份文档一致 |
| 6 | 清除过期 `.lock` | 避免本地 Qdrant 误判占用 |
| 7 | 强化 `.gitignore` | `games.csv` / `.env.local` / `recommender/data` / `*.sqlite` 均已排除，`git check-ignore` 验证通过 |
| 8 | 提交 `.gitignore` 与本分析文档 | 本地 commit（**未 push**，见下） |

> **未执行**：`git push`。远程 `main` 已有团队提交，本地新增分支内容需要你先确认再推送。
> 推送命令：`git push origin main`（需要 GitHub 凭据）。

---

## 7. 工程化进展（本轮更新）

### 7.1 环境（P0）已全部打通

| 项 | 之前 | 现在 |
| --- | --- | --- |
| 前端依赖 | 未安装 | `npm install` 完成（26 个包） |
| Python 环境 | 无 venv，系统 Python 3.14 | `.venv` = **3.12.13**，`requirements-dev.txt` 已装 |
| PyTorch | 缺失 | **2.6.0+cu124**，`torch.cuda.is_available() == True` |
| sentence-transformers | 缺失 | 5.7.0 |
| BGE-M3 权重 | 未下载 | 已缓存 `recommender/data/embeddings-bge-m3`（2.27 GB） |
| Qdrant 路径 | `qdrant/qdrant` | `recommender/data/qdrant`（与 `.env.local` 一致） |

### 7.2 服务已对真实数据端到端跑通（实测）

| 检查 | 结果 |
| --- | --- |
| `GET /status` | `ready=true`、`documents=20000`、`vector_size=1024`、`device=cuda` |
| `GET /similar?q=496350` | 200，源 `Supipara - Chapter 1…`，返回 NEKOPARA Vol.4 / Yukikoi Melt 等同类 |
| `GET /search?q=a relaxing video game…` | 200，返回拼图/治愈类小游戏，中文解释由 DeepSeek 生成 |
| 冷启动 `/status` | 27–30 s（读 2 万点 + 建 BM25 索引） |
| 冷启动首次 `/search` | 42.8 s（含模型入显存） |
| 温态 `/search`（n=10） | min 1.98 s / **p50 2.45 s** / p95 7.19 s |

> 温态波动主要来自 LLM 解释调用（校内网关），检索本身在百毫秒级。

### 7.3 已完成的工程改造

| 类别 | 内容 |
| --- | --- |
| 结构 | 从 `service.py` 拆出 `text.py` / `ranking.py`（纯函数、零依赖）；新增 `selection.py` |
| 测试 | **64 个用例**：clean / text / ranking / selection 仅用标准库；13 个 FastAPI 契约用例 |
| 质量 | ruff（E/F/W/I/B/UP/C4/SIM/RET/PTH，行宽 100）全绿；`zip(strict=)`、`Path.open` 等统一 |
| 工具链 | `pyproject.toml`、`.editorconfig`、`.gitattributes`、`requirements-dev.txt` |
| 脚本 | `scripts/bootstrap.ps1`（优先用 uv，支持 `-Full` 装重型运行栈） |
| 容器化 | `docker-compose.yml` + `docker/*.Dockerfile` + `recommender/migrate_qdrant.py`，已实跑验证（见 §9） |
| CI | `.github/workflows/ci.yml`：web / python-unit（零依赖）/ python-api 三个 job |
| 文档 | `docs/project-structure.md`、`docs/docker.md`、`CONTRIBUTING.md`、README 开发章节 |
| 一句话检查 | `npm run check`（typecheck + ruff + 前端单测 + Python 单测） |

### 7.4 仍然待办

| 项 | 说明 |
| --- | --- |
| 重建索引 | 现索引缺少热门游戏（见 §8.1），需 `--order-by reviews --reset` 重跑，成本约 3 万次 LLM 调用 |
| 评测集与 `evaluate.py` | Recall@k / NDCG 与 BM25/向量/RRF 消融；属报告素材，本轮按要求跳过 |
| Release 上传 `games.csv` | README 第 21 行的下载链接目前是死链 |
| LICENSE | 属法务决策，未擅自添加 |

---

## 8. 本轮新发现的三个问题

### 8.1 索引样本代表性差（已修复，见 §10）

- **实测**：20,000 条索引里 `review_count` 中位数 **105**、p99 51,033；
  **Stardew Valley(413150) 与 Cyberpunk 2077(1091500) 不在索引内**，
  而 Dota 2(570)、CS2(730) 恰好在。
- **原因**：`iter_games` 按 `games.csv` 行序取前 2 万条，等于随机抽样。
- **修复**：`enrich_qdrant --order-by reviews` 按评论数挑选候选，分两批补齐到
  30,000 条，详见 §10。
- **顺带修掉的阻塞项**：4 并发会撞上网关 **50 请求/分钟/成员** 的限流，
  30% 调用被 429 丢弃。已加 `DEEPSEEK_RPM` 客户端限速，限速后 **零 429**。

### 8.2 `find_source` 会把游戏名替换成别的游戏（已修复）

- `cutoff=0.72` 时 `"Stardew Valley"` 被解析成 `"Red Valley"`
  （SequenceMatcher 比值 0.75），于是返回了另一款游戏的邻居。
- 已改为 `cutoff=0.82` **且首字符必须一致**：容忍拼写错误，不接受换词替代；
  查不到时返回 404 并在详情里给出索引规模。已补 3 个回归用例。

### 8.3 首次下载 BGE-M3 会因 Xet 传输失败（已记录绕法）

- 现象：`OSError: I/O error ... (os error 5)`，发生在 `huggingface_hub` 的 Xet 下载路径。
- 绕法：`$env:HF_HUB_DISABLE_XET = "1"` 后重试，实测 1280 MB / 20 s 下载成功。
- 已写入 `recommender/README.md` 的「首次下载 BGE-M3 失败」小节。

---

## 9. 容器化（本轮完成并实跑验证）

此前因本机无 Docker 而搁置的容器化已完成。Docker Desktop 4.99.0 装好后，
`docker compose up` 全栈实测通过。

### 9.1 组成

| 服务 | 镜像 | 体积 | 说明 |
| --- | --- | --- | --- |
| `qdrant` | `qdrant/qdrant:v1.20.2` | 287 MB | server 模式，命名卷持久化 |
| `recommender` | 自建（python:3.12-slim + CPU torch） | 1.95 GB | `QDRANT_URL` 指向 qdrant，模型权重为宿主挂载 |
| `web` | 自建（node:22-slim 三阶段） | 850 MB | `games.csv` 只读挂载，`RECOMMENDER_API_URL` 指向 recommender |

### 9.2 迁移：嵌入式 → server

嵌入式模式把全部数据放在单个 `storage.sqlite`，server 读不了，因此新增
`recommender/migrate_qdrant.py`：按 256 条一批把 id / vector / payload 原样重传，
**不重新嵌入、不调用 LLM**。

实测：**20,000 点在 24.7 s 内完成（811 点/s）**，源与目标计数一致。

### 9.3 端到端实测（容器内）

| 检查 | 结果 |
| --- | --- |
| 三容器健康状态 | `qdrant` / `recommender` / `web` 全部 `healthy` |
| `GET /status` | 200，`documents=20000`、`vector_size=1024`、`device=cpu` `float32` |
| `GET /similar?q=496350` | 200，6.3 s，返回 NEKOPARA Vol.4 / Yukikoi Melt 等 |
| `GET /search?q=a relaxing puzzle…` | 200，首次 51.1 s（含 CPU 加载模型），结果与宿主一致 |
| 温态 `/search` | 3.02 s / 2.13 s |
| web → api 代理 | 200，0.23 s |
| `GET /api/deals` | 200，13.3 s，`totalItems=9516`（11,049 款可筛选），证明 395 MB CSV 挂载生效 |

### 9.4 容器模式带来的改进与代价

- **改进**：Qdrant 从嵌入式单进程锁改为 server 模式，增强脚本与 API 可以同时运行，
  多人共用一份数据也不必串行（详见 `CONTRIBUTING.md` §5）。
- **代价**：容器内没有 GPU 直通，嵌入退到 CPU；但实测温态延迟 2.1–3.0 s，
  与宿主 CUDA 的 p50 2.45 s 基本持平，瓶颈在 LLM 解释而非嵌入。
- **冷启动**：容器内首次 `/status` 需 74 s（2 万条 payload 走 HTTP + 建 BM25），
  比宿主的 27 s 慢，属冷启动成本。

完整操作说明见 [docs/docker.md](docker.md)。

---

## 10. 索引重建记录（按评论数取样，25,110 → 30,000）

### 10.1 第 1 批：+5,000 条

| 指标 | 实测 |
| --- | --- |
| 规模 | 20,110 → **25,110**（+5,000，0 失败） |
| 耗时 | **8,215 s = 2 h 17 m** |
| 速率 | **36.5 条/分钟**（1.64 s/条） |
| LLM 调用 | 5,000 次 |
| prompt tokens | **2,964,542**（593/条；`--dry-run` 估 534，偏低 11%） |
| completion tokens | **649,969**（130/条，中文摘要） |
| 嵌入 | 本地 GPU，不出网、不计费 |
| 429 限流 | **0**（`DEEPSEEK_RPM=40` 生效后；未限速时约 30% 被丢弃且速率更低） |

取样方式：`--order-by reviews` 从「未入库且评论数 ≥20」的候选里取评论数最高的
5,000 条，因此补进来的正是此前缺的知名作品。

### 10.2 效果验证

重建前 `q=Stardew Valley` 返回 404；重建后全部命中，且同类召回合理：

| 查询 | 召回的前三 |
| --- | --- |
| Stardew Valley | STORY OF SEASONS: Friends of Mineral Town / Fields of Mistria / Coral Island |
| Cyberpunk 2077 | RoboCop: Rogue City / Deus Ex: GOTY / The Ascent |
| ELDEN RING | ELDEN RING NIGHTREIGN / YAR: Forgotten Throne / Lords of the Fallen |
| Black Myth: Wukong | Black Myth: Wukong Benchmark Tool / The Crown of Wu / Monkey King Simulator |
| The Witcher 3 | Requiem / The Witcher: Enhanced Edition / Vampire: The Masquerade - Redemption |

### 10.3 数据事实：54 条没有描述

- 扩到 25,110 条后，全库扫描发现 **54 条（0.215%）`description` 为空**，
  这是 `games.csv` 的 `About the game` 单元格本身缺失，不是流水线问题。
- 其中包含 The Witcher 3 这类热门条目：它们仍有按 name/genres/source_tags
  生成的 LLM 标签与摘要，删除会损失演示价值，因此保留。
- 验收测试的 R1 断言随之从「每条都非空」改为「≥98% 非空」，并在脚本注释里写明原因。

### 10.4 第 2 批：+4,890 条（至 30,000）

按 36.5 条/分钟估算约 **134 分钟**、约 **3.5 M tokens**。

### 10.5 规模上限的现实约束

瓶颈是网关速率而不是 token 预算：

| 规模 | 预计耗时 |
| --- | --- |
| 25,000（第 1 批后） | — |
| 30,000（当前目标） | +2.2 h |
| 46,018（全部达标池） | 约 9.5 h，且推荐容器内存预计 ~5.9 GB / 虚拟机 7.4 GB，偏紧 |

若后续要扩到 46k，应先给 Docker 虚拟机加内存（或改回嵌入式 + 单进程），
并向课程方申请提高 `team_member` 的请求配额。

