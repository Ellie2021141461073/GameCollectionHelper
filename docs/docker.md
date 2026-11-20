# 容器化运行（Docker Compose）

本仓库提供完整的容器编排：**Qdrant server + FastAPI 推荐服务 + Next.js 应用**。
与在宿主机上直接运行相比，容器模式的差别只有三点，见第 2 节。

---

## 1. 架构

```text
浏览器
  │
  ▼
web  (Next.js 15, :3000)  ── /api/recommender/* 代理 ──►  recommender (FastAPI, :8000)
  │                                                            │
  │ /api/deals 读 games.csv（只读挂载）                          ├── BGE-M3（CPU）生成查询向量
  │ /api/cards 直连 Steam Community                             ├── BM25（进程内倒排索引）
  ▼                                                            └──► qdrant (gRPC/REST, :6333)
host:3000                                                            20,000 条 1024 维向量
```

| 服务 | 镜像 | 端口 | 本地挂载 |
| --- | --- | --- | --- |
| `qdrant` | `qdrant/qdrant:v1.20.2`（287 MB） | 6333 / 6334 | 命名卷 `gamecollectionhelper-qdrant-storage` |
| `recommender` | `gamecollectionhelper/recommender:local`（1.95 GB） | 8000 | `./recommender/data/embeddings-bge-m3`（2.2 GB 模型权重） |
| `web` | `gamecollectionhelper/web:local`（850 MB） | 3000 | `./games.csv`（395 MB，只读） |

三个端口都只绑定 `127.0.0.1`，不对局域网暴露。

## 2. 与宿主机运行的差异

| 项 | 宿主机（`npm run recommend:api`） | 容器 |
| --- | --- | --- |
| Qdrant 模式 | 嵌入式 `local`，**单进程独占锁** | server 模式，可多进程/多机只读 |
| 向量存放 | `recommender/data/qdrant/storage.sqlite` | 命名卷 |
| 嵌入设备 | `.env.local` 的 `cuda` / `float16` | **CPU / float32**（默认无 GPU 直通） |
| `games.csv` | 仓库根目录直接读取 | 只读挂载进 `/app/games.csv` |
| BGE-M3 权重 | 本地缓存目录 | 同一目录挂载进容器，**不重复下载** |

> Docker Desktop 需要 NVIDIA Container Toolkit 才能把宿主机 GPU 交给 Linux 容器，
> 所以 compose 里固定 `EMBEDDING_DEVICE=cpu`。实测容器内首次 `/search`（含 CPU 加载模型）
> 51 s，温态 2.1–3.0 s，与宿主 CUDA 的 p50 2.45 s 基本持平——瓶颈在 LLM 解释调用，
> 不在嵌入。

## 3. 首次启动

### 3.1 准备向量数据（二选一）

**方式 A：导入发布页的快照（推荐，约 2 分钟）**

从 Release [data-v1](https://github.com/Ellie2021141461073/GameCollectionHelper/releases/tag/data-v1)
下载 `steam_games-30000-2026-11-20.snapshot`（247 MB，含 30,000 条向量与摘要），然后：

```powershell
docker compose up -d qdrant

curl.exe -X POST "http://127.0.0.1:6333/collections/steam_games/snapshots/upload?priority=snapshot" `
  -F "snapshot=@steam_games-30000-2026-11-20.snapshot"
```

`games.csv`（395 MB）同样从该发布页下载，放到仓库根目录。

**方式 B：自己重建（无需下载，约 4.5 小时）**

```powershell
docker compose up -d qdrant
$env:QDRANT_URL = "http://127.0.0.1:6333"
$env:DEEPSEEK_RPM = "40"
python -m recommender.enrich_qdrant --limit 30000 --min-reviews 20 --order-by reviews
```

> 旧版本的文档曾让你用 `python -m recommender.migrate_qdrant` 把「嵌入式库」搬进 server。
> 那个 2 万条的嵌入式库已删除，`migrate_qdrant` 现在只用于显式指定的 `--source`。
> 如果你手上还留着别的嵌入式库，仍然可以这样导入。

### 3.2 构建并启动应用

```powershell
docker compose up -d --build recommender web   # 首次构建约 6 分钟，之后走缓存
```

验证：

```powershell
docker compose ps                     # 三个服务都应为 healthy
curl http://127.0.0.1:8000/status     # documents 应为 20000
curl http://127.0.0.1:3000/api/recommender/status
```

完整的验收测试（按选题 5 项关键任务逐条校验，只用标准库）：

```powershell
python scripts/acceptance_test.py --verbose
```

然后打开 <http://localhost:3000>。

## 4. 常用命令

| 目的 | 命令 |
| --- | --- |
| 查看状态 | `docker compose ps` |
| 跟踪日志 | `docker compose logs -f recommender` |
| 停止（保留数据） | `docker compose down` |
| 停止并删除向量卷 | `docker compose down -v` |
| 重建单个服务 | `docker compose up -d --build recommender` |
| 重新迁移向量 | `python -m recommender.migrate_qdrant --reset` |
| 只看不传 | `python -m recommender.migrate_qdrant --dry-run` |
| 进容器排查 | `docker compose exec recommender python -c "import recommender.store as s; print(s.COLLECTION_NAME)"` |

## 5. 环境变量

- `env_file: .env.local` 是**可选**的（compose 的 `required: false`）。
  有该文件时会带上 `DEEPSEEK_API_KEY`，推荐结果会附带 LLM 生成的解释；
  没有时自动退回「共享标签」解释，服务照常工作。
- 容器专用变量在 compose 的 `environment:` 中显式覆盖，优先级高于 `env_file`，
  所以宿主机的 `EMBEDDING_DEVICE=cuda` 不会带进容器。

## 6. 已知限制

1. **模型权重靠宿主挂载**：`recommender/data/embeddings-bge-m3` 不存在时，
   容器首次启动会现场下载 2.2 GB（镜像已设 `HF_HUB_DISABLE_XET=1` 规避 Xet 报错）。
   想彻底不依赖宿主，可以把它换成命名卷并在 Dockerfile 里预下载。
2. **`web` 镜像包含 devDependencies**：为缩短构建时间没有做 prod-only 安装，
   镜像 850 MB。若要瘦身，加一个 `npm ci --omit=dev` 的 stage 即可。
3. **镜像不烘焙数据**：`games.csv`、向量库、模型都靠挂载或迁移，因此
   `docker compose up` 前必须已有这三样东西（见第 3 节）。
4. 首次 `/status` 在容器里约 74 s：要把 2 万条 payload 通过 HTTP 从 Qdrant 读出来
   并在内存里建 BM25 索引。属于冷启动成本，之后都是内存查询。
