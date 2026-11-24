# 推荐系统技术实现说明

本文逐模块讲解四个核心部分：**Qdrant 数据写入**、**相似检索**、**BM25 + 向量混合排序**、
**DeepSeek 推荐解释**。每一节都按同一条线索组织：

> **这项技术是什么 → 本项目怎么实现（含代码位置）→ 实测结果与设计取舍**

所有数字都来自本机实跑（30,000 条索引、RTX 4060、Qdrant `v1.20.2`、
`BAAI/bge-m3`、`CS5351/DeepSeek-V4-Flash`），可用 `docs/experiments/` 里的脚本复现。

---

## 0. 系统总览

```text
┌──────────────────────── 离线（一次性，可断点续跑） ─────────────────────────┐
│                                                                           │
│  games.csv 130,100 行                                                     │
│      │ recommender/clean.py        修复 39 表头 / 40 值错位              │
│      ▼                                                                    │
│  CleanGame ──► recommender/chat.py        DeepSeek：12 个标签 + 中文摘要  │
│           └─► recommender/embeddings.py   BGE-M3：1024 维归一化向量      │
│                        │                                                  │
│                        ▼  recommender/store.py + enrich_qdrant.py        │
│              Qdrant 集合 steam_games：point(id=AppID, vector, payload)   │
└───────────────────────────────────────────────────────────────────────────┘

┌──────────────────────── 在线（每次请求，毫秒级检索） ───────────────────────┐
│                                                                           │
│  ① 相似检索 /similar?q=<名称|AppID>                                       │
│       find_source() 解析出源物品 → 用它**已存的向量**查 top-50            │
│                                  → 用它 name+summary+tags 查 BM25 top-50  │
│                                                                           │
│  ② 文本检索 /search?q=<自然语言>                                          │
│       查询 → BGE-M3 向量 → Qdrant top-50                                  │
│       查询 → 分词 → BM25 top-50                                          │
│                              │                                            │
│                              ▼                                            │
│       ③ recommender/ranking.py    RRF 融合 + 质量先验 → 取前 N            │
│                              │                                            │
│                              ▼                                            │
│       ④ recommender/service.py    DeepSeek 批量生成推荐解释              │
└───────────────────────────────────────────────────────────────────────────┘
```

四个模块与课程要求的对应关系：

| 模块 | 对应要求 | 主要文件 |
| --- | --- | --- |
| Qdrant 数据写入 | 任务 2「特征增强」+ 任务 3「数据管理」 | `enrich_qdrant.py` `store.py` |
| 相似检索 | 任务 4 前半「给定物品 ID 检索 top-N 相似物品」 | `service.py` `ranking.py` |
| BM25 + 向量混合排序 | 任务 4 后半「关键词 + 向量混合排序」 | `ranking.py` `service.py` |
| DeepSeek 推荐解释 | 任务 5「解释生成」 | `service.py` `chat.py` |

---

## 1. Qdrant 数据写入

### 1.1 技术背景

**向量数据库**解决的是"按语义相似度检索"的问题：把每个物品编码成一个高维向量，
查询时按余弦相似度（或点积 / 欧氏距离）找最近的邻居。

Qdrant 的数据模型有四个概念：

| 概念 | 含义 | 本项目用法 |
| --- | --- | --- |
| collection | 一组同维度向量的集合，需声明维度与距离函数 | `steam_games`：1024 维、Cosine |
| point | 一条记录 = `id` + `vector` + 可选 `payload` | 一款游戏 |
| payload | 任意 JSON，随点存储，可建索引、可过滤 | 32 个结构化字段 |
| HNSW | 近似最近邻索引（分层可导航小世界图），用少量精度换数量级的查询加速 | Qdrant 默认内置 |

为什么不用 pgvector：本项目的检索需求是"向量 + 词法"两路，词法侧用内存 BM25 更直接；
Qdrant 自带 HNSW、payload 过滤与快照备份，省掉自己维护图索引的成本。
代价是引入了另一套存储，需要 `migrate_qdrant.py` 这类搬运工具。

### 1.2 一条 point 的结构

```python
PointStruct(
    id      = 413150,          # Steam AppID：天然唯一、可重复 upsert
    vector  = [float × 1024],  # BGE-M3 输出，已 L2 归一化（‖v‖≈1）
    payload = { 32 个字段 },
)
```

实测从库里取出 Stardew Valley 那条：

```text
id = 413150 | payload 字段数 = 32
  name             = Stardew Valley
  genres           = ['Indie', 'RPG', 'Simulation']
  llm_tags         = ['farming sim','life sim','pixel graphics','multiplayer','crafting', ...]  12 个
  review_count     = 886195
  enrichment_model = BAAI/bge-m3|CS5351/DeepSeek-V4-Flash
  search_text 长度  = 4,279 字符
  description 长度  = 3,750 字符
```

`payload` 由 `recommender/store.py: game_payload()` 组装，字段分四类：

| 类别 | 字段 | 用途 |
| --- | --- | --- |
| 身份 | `app_id` `name` `normalized_name` | 名称解析、去重、返回给前端 |
| 检索产物 | `llm_tags` `summary` `search_text` | BM25 索引来源、卡片展示、向量编码原料 |
| 结构化元数据 | `genres` `source_tags` `developers` `publishers` `release_date` `price` `discount` `categories` `website` `header_image` | 质量先验、过滤、前端渲染 |
| 热度与评价 | `positive` `negative` `review_count` `recommendations` `achievements` `peak_ccu` `estimated_owners_*` `average/median_playtime_*` | 质量重排、排序展示 |
| 追溯 | `description` `enrichment_model` | 复现与审计 |

两个刻意的设计：

- **完全反范式**：所有展示所需字段都塞进 payload。检索命中后直接渲染，不需要回表 join 一个关系库。
- **预拼 `search_text`**：`name + genres + source_tags + developers + publishers + description` 拼好后一起存。
  服务启动时直接拿它建 BM25 倒排索引，不必再解析描述（省掉启动期的一次全量文本处理）。

### 1.3 编码什么文本，比怎么编码更重要

向量不是直接编码原始描述，而是编码一段**拼装文本**（`enrich_qdrant.py: build_embedding_text`）：

```text
<游戏名>
<DeepSeek 生成的中文摘要>
Tags: <12 个 LLM 标签>
Genres: <类型>
Source tags: <Steam 官方标签>
Description: <原始描述前 4000 字符>
```

这样做换来的能力，用真实查询验证过：

| 查询 | 只编码英文描述会怎样 | 加上 LLM 摘要/标签后 |
| --- | --- | --- |
| `a relaxing puzzle game with beautiful art and no combat` | 需要描述里恰好出现 relax/puzzle/combat 等词 | 摘要里已经写着"宁静、无战斗、适合放松"，语义直接命中 |
| 中文查询「放松的拼图游戏」 | 英文描述无法跨语言匹配 | BGE-M3 多语言 + 中文摘要，可直接跨语言 |

实测该查询的 top-8 全是拼图/逻辑解谜类，且 BM25 分只有 11–17 —— 说明**主要靠语义通道命中**，
这正是"LLM 增强特征"这一项的实际价值。

### 1.4 批量写入与容错

`enrich_qdrant.py: process_batch()` 的批次结构：

```python
batch = 16（或 32）条游戏
  ├─ ThreadPoolExecutor(workers=4) 并行调 DeepSeek ← 网络 I/O，瓶颈在这里
  ├─ embed_documents(全部文本)                      ← 本地 GPU，一次批量前向
  └─ qdrant.upsert(points, wait=True)               ← 一次网络往返写完整批
```

四条工程约束（都是踩坑后加的）：

| 机制 | 为什么需要 |
| --- | --- |
| `id = app_id` | upsert 幂等；重跑不会产生重复点；断点续跑靠"已入库 id 跳过" |
| 单条失败只记 WARN 并跳过 | 一次 429 或一条畸形 JSON 不该中断跑了几小时的批次；失败的留待下次重跑 |
| `DEEPSEEK_RPM=40` 客户端限速 | 网关限制 **50 请求/分钟/成员**，且 **429 本身也吃配额**。不限速实测 26 条/分且 30% 丢弃；限速后 37 条/分、零丢弃 |
| `--dry-run` | 不调 API 就估出"要调多少次、多少 token"，避免误跑几万条 |

`process_batch()` 返回**实际写入的 AppID 列表**（不是批次大小），
这样 `known_ids` 只记录真正落库的条目，失败项下次还能被选中。

### 1.5 实测

| 指标 | 值 |
| --- | --- |
| 集合规模 | 30,000 points / 1024 维 / Cosine |
| 卷内占用 | 248 MB（Qdrant 服务端目录） |
| 增强吞吐 | **37 条/分钟**（受网关限速，非算力） |
| 单条成本 | 593 prompt + 130 completion tokens |
| 嵌入耗时 | 单条 0.04 s（GPU 预热后） |
| 迁移吞吐 | 811 点/秒（嵌入式 → server，纯搬运不重算） |

---

## 2. 相似检索（item → item）

### 2.1 技术背景

题目明确要求"不需要建模用户-用户交互，而是建模物品-物品相似度"。这是**基于内容的推荐
（content-based filtering）**：

- 协同过滤需要"用户 × 物品"评分矩阵，冷启动无解；
- 基于内容只需要物品自身的描述，任何新物品入库即可被推荐；
- 语义相似度由向量空间中的余弦距离度量：

$$\text{sim}(a, b) = \frac{a \cdot b}{\lVert a \rVert \, \lVert b \rVert}$$

因为写入前已经做了 L2 归一化（实测 $\lVert v \rVert = 0.999965 \approx 1$），
余弦相似度退化为点积，Qdrant 用 `Cosine` 距离时内部就是这个计算。

### 2.2 第一步：把用户输入解析成库里的一条记录

`service.py: find_source()`，四级匹配，逐级放宽：

| 级 | 规则 | 命中示例 |
| --- | --- | --- |
| 1 | 纯数字 → 当 AppID 直查 | `413150` |
| 2 | 归一化后精确匹配 `normalized_name` | `stardew valley` |
| 3 | 子串匹配，取名称最短的（避免"Deluxe Edition"抢先） | `stardew` |
| 4 | 模糊匹配：`difflib` 比值 ≥ **0.82** 且**首字符必须一致** | `stardew valey`（拼写错误） |

第 4 级那两个约束是修 bug 加上的：原实现 `cutoff=0.72`，
输入 `Stardew Valley` 会被解析成 **`Red Valley`**（比值 0.750），
于是返回了一款毫不相干游戏的邻居，用户看到的推荐与输入毫无关系。

> 归一化函数 `clean.normalize_name()` 在**入库时和查询时共用同一个实现**，
> 否则 `Dungeons & Dragons` 两侧会变成 `dungeons and dragons` vs `dungeons dragons`，永远匹配不上。

### 2.3 第二步：向量 + 词法双路召回，然后排除自身

```python
vector_results  = qdrant_search(state.client, source.vector, 50)   # 直接用库里的向量
lexical_results = state.bm25.search(query_tokens, 50)              # 用 name+summary+tags 组词
ranked = merge_rankings(..., exclude_id=source.app_id)             # 融合后剔除源物品
```

关键点：**相似检索不需要重新做 embedding**。源游戏的向量就在 payload 旁边，
直接取出来当查询向量即可，省掉一次模型前向（实测单条约 40 ms）。

但要诚实说明：这 40 ms 在 2–3 s 的总延迟里**不可见**——实测 `/similar` p50 2.37 s
与 `/search` p50 2.14 s 基本持平，因为两者的主要成本都是 LLM 解释调用，
而不是嵌入或检索。真正让 `/similar` 便宜的是"少一次 GPU 前向"，
这在批量离线场景（如给全库两两算相似）才有量级意义。

词法侧的查询不是来自用户输入（相似检索没有用户文本），而是用源物品自己的
`name + summary + llm_tags + genres` 拼出来的，这样"同类型 + 同题材"的游戏在词法上也能命中。

### 2.4 实测

```
/similar?q=Stardew Valley   (AppID 413150，农场经营/生活模拟)

01  STORY OF SEASONS: Friends of Mineral Town   100.0%   vec=0.707  bm25=116.875
02  Coral Island                                 93.9%   vec=0.693  bm25=116.565
03  Fields of Mistria                            93.2%   vec=0.688  bm25=126.872
04  Orange Season                                92.5%   vec=0.691  bm25=132.691
05  Luma Island                                  92.3%   vec=0.686  bm25=126.532
```

Top-5 全部是同类作品，且向量分集中在 0.68–0.71（余弦相似度的典型可用区间，
0.9 以上通常只在重复条目上出现）。

---

## 3. BM25 + 向量混合排序（核心）

### 3.1 两路召回的分工

| | 向量检索 | BM25（词法） |
| --- | --- | --- |
| 特征 | BGE-M3 1024 维稠密向量 | 词频统计 + 逆文档频率 |
| 擅长 | 换措辞、跨语言、抽象语义（"放松无战斗"） | 精确词命中、专有名词（"ELDEN RING"、"wargame"） |
| 弱点 | 可能"语义漂移"，把风格相近但内容不同的东西拉进来 | 无法处理同义词、改写、跨语言 |
| 存储 | Qdrant HNSW 索引（持久化） | 内存倒排索引（进程内，启动时现建） |
| 召回首数 | 50 | 50 |

两路互补性非常强，实测前 10 条的平均 **Jaccard 重叠只有 0.092** —— 几乎不重样。
这就是混合检索的价值来源。

### 3.2 BM25 的数学与代码映射

Okapi BM25 的打分公式：

$$\text{score}(D, Q) = \sum_{t \in Q} \text{IDF}(t) \cdot \frac{f(t,D) \cdot (k_1 + 1)}{f(t,D) + k_1 \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$

`recommender/ranking.py` 直接对应公式的每一项：

```python
# IDF：ln(1 + (N - df + 0.5) / (df + 0.5))     ← 加 1 保证非负（词出现太频繁时不为负）
self.idf = {
    term: math.log(1 + (total - len(entries) + 0.5) / (len(entries) + 0.5))
    for term, entries in self.postings.items()
}

# 打分：饱和项 + 文档长度归一化
denominator = frequency + self.k1 * (
    1 - self.b + self.b * self.lengths[index] / max(1e-9, self.average_length)
)
scores[index] += idf * frequency * (self.k1 + 1) / denominator
```

两个超参的作用：

| 参数 | 取值 | 作用 |
| --- | --- | --- |
| $k_1$ | **1.5** | 词频饱和速度。越小越快饱和（词出现 3 次和 30 次差别不大），避免关键词堆砌刷分 |
| $b$ | **0.75** | 文档长度归一化强度。1 = 完全按长度惩罚长文档，0 = 不惩罚。描述长短差异大，取 0.75 折中 |

**中文分词的处理**：BM25 依赖词边界，中文没有空格。`text.py` 的处理是对 CJK 连续串
额外切**重叠二元组**：

```text
"一款舒适的农场模拟游戏"  →  一款舒适的农场模拟游戏（>4 字，整串丢弃）
                            + 一款 款舒 舒适 适的 的农 农场 场模 模拟 拟游 游戏（10 个 bigram）
```

小于等于 4 字的短串会额外保留整串，避免"模拟"这类短词被切碎后语义丢失。

### 3.3 为什么不能直接加权相加

两路分数量纲完全不可比：

| | 值域 | 实测典型值 |
| --- | --- | --- |
| 向量余弦 | [-1, 1] | 0.60 – 0.71 |
| BM25 | [0, +∞) | 11 – 133 |

- 直接归一化到 [0,1] 需要为每种检索器选归一化函数（min-max / z-score / sigmoid），
  而 min-max 对长尾极值敏感、z-score 假设分布，都是新的超参来源；
- 加权求和 `α·vec + β·bm25` 里的 α、β 又强依赖查询类型（专有名词查询 vs 抽象描述查询）。

**结论：用排名而不是分数做融合。**

### 3.4 RRF：Reciprocal Rank Fusion

$$\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + \text{rank}_r(d)}, \quad k = 60$$

`ranking.py` 实现（向量路和词法路各累加一次）：

```python
item["rrf"] += 1 / (rrf_k + rank)     # 向量榜第 rank 名
item["rrf"] += 1 / (rrf_k + rank)     # 词法榜第 rank 名
```

数值直觉（k=60）：

| 情况 | 得分 |
| --- | --- |
| 两榜都第 1 | 1/61 + 1/61 = **0.0328** |
| 只在向量榜第 1 | 1/61 = **0.0164** |
| 两榜都第 10 | 2/71 = 0.0282 |
| 向量第 1 + 词法第 50 | 1/61 + 1/110 = 0.0255 |

即"两路都被认可"严格优于"单路排得很靠前"，这正是我们要的互补效应。
`k=60` 是 Cormack et al. (2009) 的经典取值，起"阻尼"作用：k 越大，名次差距的影响越平缓。

### 3.5 质量先验：把"评价好"作为微弱加分项

$$\text{hybrid\_score} = \text{RRF} + 0.004 \times Q(\text{payload})$$

$$Q = 0.8 \times \underbrace{\frac{\text{pos} + 40 \times 0.8}{\text{pos} + \text{neg} + 40}}_{\text{贝叶斯平滑好评率}} + 0.2 \times \underbrace{\min\left(1, \frac{\ln(1+\text{recs})}{12}\right)}_{\text{对数阻尼热度}}$$

三个设计考虑：

| 设计 | 原因 |
| --- | --- |
| 贝叶斯平滑（先验 40 条、均值 0.8） | 3 条全好评的游戏不该有 100% 好评率。平滑后它会被拉到 0.8 附近，和"千条好评"的差距被合理压缩 |
| 对数阻尼 | 推荐数从 1 万到 100 万，直觉上差距不该是 100 倍 |
| 权重只有 **0.004** | RRF 单项量级是 0.016–0.033，0.004 只能改变**同分附近**的名次。既起到"同分时好评优先"的稳定作用，又不会盖掉检索相关性 |

`match_percent = hybrid_score / 最高分 × 100`，所以 Top-1 恒为 100%，其余是相对值。
前端展示的百分比是**相对置信度**，不是绝对概率 —— 报告里应如实说明。

### 3.6 消融实验：三路对比

做法：`/search` 增加 `retrieval=hybrid|vector|bm25`，单路模式**关闭质量重排**
（`quality_weight=0.0`），否则质量分会重排单路结果，比较的就不再是检索能力。

10 条查询 × 3 种模式，k=10，30,000 条库：

| 指标 | BM25 only | Vector only | **Hybrid (RRF)** |
| --- | --- | --- | --- |
| Hit@10 | 1.000 | 1.000 | 1.000 |
| **Precision@10** | 0.920 | 0.820 | **0.940** |
| Recall@10 | 0.920 | 0.820 | **0.940** |
| **MRR@10** | 1.000 | 1.000 | 0.950 |
| nDCG@10 | 0.929 | 0.836 | **0.938** |
| p50 延迟 | 2.78 s | 3.09 s | 2.73 s |

Jaccard 重叠（前 10 条）：**BM25 ∩ Vector = 0.092**、BM25 ∩ Hybrid = 0.288、Vector ∩ Hybrid = 0.278。

三点解读：

1. **融合有效**：Precision 0.940 高于任一单路；两条互补榜单取长补短。
2. **有代价**：MRR 从 1.000 掉到 0.950 —— 融合偶尔把语义近邻排到词法精确命中之前。
   这是 RRF 的固有取舍，报告应如实写出。
3. **延迟没有变差**：2.73 s 与单路持平，因为瓶颈是 LLM 解释调用（2–3 s），
   而检索本身只有 ~0.3 s。多一路召回的边际成本可忽略。

**局限（必须声明）**：相关集是用 genres / source_tags / llm_tags / summary 的**关键词规则**
判定的代理标签。这些词面同时也在 BM25 的索引里，因此结果**系统性偏向 BM25**；
向量路 0.820 有一部分是"语义相关但用词不同"被判成不相关。
无偏数字需要人工标注 query-document 对，这一步尚未完成。

### 3.7 其他实测性能

| 场景 | 耗时 |
| --- | --- |
| 冷启动 `/status`（拉 3 万条 payload + 建 BM25） | 43–64 s |
| `/search` 检索本身（命中解释缓存） | **0.30 s**（p50） |
| `/search` 冷查询（含 GPU 嵌入 + LLM 解释） | **2.14 s**（p50） |
| `/similar` | 2.37 s（p50） |

BM25 索引不落盘是刻意的：3 万条 `search_text` 现建只要几秒（相对总启动时间），
省掉一套需要与 Qdrant 同步的持久化索引，也避免了"两套索引不一致"的故障模式。

---

## 4. DeepSeek 推荐解释

### 4.1 技术背景

题目要求"对每个检索出的物品，用 LLM 生成一段简短说明，解释它为什么与查询或所选物品匹配"。

学术上这叫 **grounded explanation（有据可依的解释）**：解释必须基于检索到的元数据，
而不是模型自由发挥，否则会出现解释与推荐理由脱节（幻觉）的情况。

三种实现路线的取舍：

| 路线 | 成本 | 质量 | 本项目选择 |
| --- | --- | --- | --- |
| 模板拼接（共享标签） | 0 | 机械、重复 | ✅ 作为**兜底** |
| 逐条调用 LLM | N 次/请求 | 最好 | ❌ 成本随 N 线性增长 |
| **整批一次调用** | **1 次/请求** | 好 | ✅ 主路径 |

### 4.2 Prompt 契约

`service.py: explain_results()` → `chat.py: create_json_completion()`：

```text
system: Explain why each Steam game is recommended. Use only supplied metadata.
        Return JSON: {"items":[{"app_id":123,"reason":"one concise Chinese sentence"}]}

user  : {"query": "a relaxing puzzle game...",
         "source": {"name":..., "summary":..., "tags":[...]},
         "recommendations": [{"app_id":..., "name":..., "summary":..., "tags":[...]}, ...]}
```

调用参数：

| 参数 | 值 | 原因 |
| --- | --- | --- |
| `temperature` | 0.2 | 解释要稳定，但完全 0 会让措辞过于模板化 |
| `response_format` | `{"type": "json_object"}` | 强约束输出结构，省掉正则抽取 |
| `extra_body` | `{"thinking": {"type": "disabled"}}` | DeepSeek 专有：关闭思维链以降低延迟与 token |
| 每次请求调用次数 | **1** | 8–10 条结果一次批量解释 |

### 4.3 三层降级，保证永不空返回

| 层 | 触发条件 | 行为 |
| --- | --- | --- |
| 1 正常 | LLM 返回合法 JSON | 使用模型给的理由 |
| 2 部分缺失 | 某个 `app_id` 没出现在返回里 | 该条用 `fallback_reason()`：取源物品与结果的**共享标签**，套模板「与当前游戏共享 X, Y 等特征，并同时命中词法与语义检索。」 |
| 3 完全失败 | 未配置 Key / 网络异常 / JSON 解析失败 | 全部走模板，接口照常 200，只是解释变机械 |

第 3 层是 `try/except` 包住整个调用，异常时返回 `fallback`。这样推荐功能不会因为
LLM 网关抖动而整体不可用 —— 这是可用性优先的取舍，报告里可作为鲁棒性设计来写。

### 4.4 缓存

```python
cache_key = json.dumps([query_text, source.get("app_id"), [每条结果的 app_id]], sort_keys=True)
```

命中条件：**查询文本 + 源物品 + 结果列表完全相同**。效果：

| | 首次查询 | 相同查询第二次 |
| --- | --- | --- |
| `/search` | 2.14 s | **0.30 s** |
| 差异来源 | GPU 嵌入 + LLM 解释 | 只有检索 |

这也解释了一个测量陷阱：如果不区分"冷/热"，同一批查询连跑两次会得到 0.15 s 的假象，
把 LLM 成本完全藏起来。`scripts/acceptance_test.py` 的延迟测试因此给每条查询加一次性
nonce，强制走冷路径。

### 4.5 怎么证明解释真的来自 DeepSeek

两条相互独立的证据：

**证据 A：网关配额计数**（最硬）

```text
探针 A 之后 remaining = 43
/search 之后 remaining = 41      （探针 B 自身占 1）
=> 一次 /search 消耗网关请求数 = 1
```

`explain_results()` 每次请求只批量调用一次，所以"1 次请求 = 1 次网关调用"正好对上。
若走本地模板回退，这个计数不会变化。

**证据 B：文本不是模板**

回退文案是固定的两句。实测 5 条解释中**命中回退模板的数量 = 0**，且内容随查询变化：

```text
1. 这是一款轻松的后末日生存模拟游戏，玩家在废弃屋顶上种植作物、建造基地，并指挥机器人自动完成杂务，无压力环境适合放松。
2. 这款农场模拟游戏让玩家从零开始建立农场，种植果蔬、饲养动物，整体节奏轻松，适合休闲经营。
3. 在这款轻松的农场商店模拟游戏中，玩家经营农场商店，无时间限制，适合短时间游玩，放松身心。
```

### 4.6 成本

| 项 | 值 |
| --- | --- |
| 单次解释请求 | 1 次 completion（8–10 条结果一起） |
| 输入（估算，未单独打点） | 每条候选的 name + summary + tags，合计约 200–400 tokens |
| 输出（估算） | 每条约 20–40 字中文，总 200–400 tokens |
| 网关速率上限 | 50 请求/分钟/成员（实测），解释调用与增强共用这一额度 |

> 上述 token 数是按返回文本长度估的，未在网关侧单独计量。
> 增强流水线的 token 是**实测**的（`[USAGE]` 行）：每条约 593 prompt + 130 completion。

因为一次请求只调一次，解释的成本与"返回结果条数"几乎无关，
这使 `/search?limit=10` 与 `limit=3` 的 LLM 开销基本一致。

---

## 5. 一次 `/search` 的完整时序

```text
客户端  /search?q=a relaxing puzzle game...&limit=8
  │
  ├─1─ 分词 tokenize(q)                          text.py
  ├─2─ BGE-M3 嵌入查询向量                        embeddings.py
  ├─3─ Qdrant 余弦检索 top-50                     service.py
  ├─4─ BM25 倒排检索 top-50                       ranking.py
  ├─5─ RRF 融合 + 质量重排 → 取前 8               ranking.py
  ├─6─ DeepSeek 批量解释（命中缓存则跳过）         service.py   ← 主要成本
  └─7─ 组装响应：摘要/标签/双路分数/match%        service.py
```

只有两个耗时点是实测的，其余未单独打点，不做编造：

| 观测点 | 实测值 | 说明 |
| --- | --- | --- |
| 端到端，解释命中缓存 | **0.29–0.30 s**（p50，30k 库） | 第 1–5 步 + 第 7 步；含 HTTP 与 JSON 序列化 |
| 端到端，冷查询（GPU 嵌入 + LLM 解释） | **2.14 s**（p50） | 上一行 + 第 2 步 + 第 6 步 |
| 单条文本 GPU 嵌入 | **0.04 s** | `pipeline_demo.py` 预热后计时 |

由此可推出：**第 6 步（LLM）约占冷查询总耗时的 85% 以上**，
第 1–5 步加序列化合计约 0.3 s。要降延迟，优化点在解释环节（缓存、异步补解释），
而不在检索。

### 已知的性能优化点

缓存命中时仍要 0.3 s，比"纯检索"的预期（毫秒级）高一个量级，原因是
`service.py` 每次请求都做了两次 **O(n) 的全库遍历**：

```python
lexical_ids=[document.app_id for document in state.documents],            # 30,000 次
payloads={document.app_id: document.payload for document in state.documents},  # 30,000 次
```

这是为了让 `merge_rankings` 与 `SearchState` 解耦（可单测）而付的代价。
改进方向：把这两份字典在 `load_state()` 时构建一次、挂在 `SearchState` 上复用。
预计能把缓存命中的端到端延迟压到几十毫秒。当前未做，因为 0.3 s 对交互式演示足够。

---

## 6. 参数速查

| 参数 | 值 | 位置 | 含义 |
| --- | --- | --- | --- |
| 向量维度 / 距离 | 1024 / Cosine | `store.py` | 集合配置，与 BGE-M3 输出一致 |
| `BM25_K1` | 1.5 | `ranking.py` | 词频饱和速度 |
| `BM25_B` | 0.75 | `ranking.py` | 文档长度归一化强度 |
| `RRF_K` | 60 | `ranking.py` | RRF 阻尼常数 |
| `QUALITY_WEIGHT` | 0.004 | `ranking.py` | 质量先验权重 |
| `QUALITY_PRIOR_COUNT` / `MEAN` | 40 / 0.8 | `ranking.py` | 贝叶斯先验 |
| `POPULARITY_SCALE` | 12 | `ranking.py` | 热度对数阻尼系数 |
| 每路召回首数 | 50 | `service.py` | 融合前的候选规模 |
| 模糊匹配阈值 | 0.82 + 首字符一致 | `service.py` | 防止换词替代不同游戏 |
| 嵌入批大小 | 4（GPU）/ 8（CPU） | `.env.local` | 显存与吞吐折中 |
| 嵌入最大长度 | 1024 tokens | `.env.local` | 超长描述截断 |
| 增强并发 / 批次 | 4 / 16 | CLI | 受网关限速约束 |
| `DEEPSEEK_RPM` | 40 | `.env.local` | 客户端限速（网关上限 50） |
| 解释温度 | 0.2 | `chat.py` | 稳定性 vs 措辞多样性 |

---

## 7. 参考文献

1. Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval.*
   Cambridge University Press. —— BM25、倒排索引、TF-IDF 的理论基础
2. Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). *Reciprocal rank fusion outperforms
   condorcet and individual rank learning methods.* SIGIR. —— RRF 的原始论文，k=60 的出处
3. Robertson, S., & Zaragoza, H. (2009). *The probabilistic relevance framework: BM25 and beyond.*
   Foundations and Trends in Information Retrieval, 3(4), 333-389. —— BM25 参数 k1/b 的概率解释
4. Chen, J., et al. (2024). *BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity
   Text Embeddings Through Self-Knowledge Distillation.* arXiv:2402.03216. —— 本项目所用嵌入模型
5. Malkov, Y. A., & Yashunin, D. A. (2020). *Efficient and robust approximate nearest neighbor
   search using Hierarchical Navigable Small World graphs.* IEEE TPAMI. —— Qdrant 的 HNSW 索引
6. Lewis, P., et al. (2020). *Retrieval-augmented generation for knowledge-intensive NLP tasks.*
   NeurIPS 33. —— "解释/答案必须基于检索内容"的方法论来源
7. Qdrant Documentation. https://qdrant.tech/documentation/ —— payload / snapshot / 集合配置
