# 贡献指南（Contributing）

本文约定本仓库的分支模型、提交信息格式与提交前检查。目标是让 8 个人的改动
可以并行推进，同时保持 `main` 随时可运行。

---

## 1. 分支模型

```text
feature-*  ──►  dev  ──►  main
（个人开发）    （集成）    （可运行 / 可演示）
```

| 分支 | 用途 | 规则 |
| --- | --- | --- |
| `main` | 可运行、可演示的版本 | 只能从 `dev` 合并；合并前 CI 必须全绿 |
| `dev` | 日常集成 | 功能分支合入这里，出问题在这里修 |
| `feature-*` | 个人或小组功能 | 从最新 `dev` 切出，合并前先 `git rebase dev` |

```bash
git switch dev
git pull --ff-only origin dev
git switch -c feature-recommend-eval
# ... 开发 ...
npm run check                 # 提交前必须全绿
git add -p                    # 分块暂存，避免把无关改动混进一个提交
git commit
git push -u origin feature-recommend-eval
```

> 当前远程的 `dev`、`feature-c`、`feature-f`、`feature-z` 都还停在同一个
> `Initial commit` 上，需要按上面的流程真正推进起来。

## 2. 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/)，标题行中文，
不加句号，50 字以内；正文用 `-` 列出「为什么改」和「改了什么」。

```text
<type>(<scope>): <简述>

- 动机或影响
- 实现要点
```

允许的 `type`：

| type | 用于 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 修 bug（正文写清触发条件与影响范围） |
| `refactor` | 不改变行为的结构调整 |
| `perf` | 性能优化 |
| `test` | 只增删测试 |
| `docs` | 文档与注释 |
| `style` | 格式化、import 顺序等 |
| `chore` | 工具链、依赖、配置 |
| `ci` | CI / 构建流水线 |

示例：

```text
fix(clean): 修复空列表单元格被解析成字面量标签的问题

- ast.literal_eval 对 "[]" 返回空列表，旧逻辑误判为解析失败
- 影响 games.csv 中 8,757 行 Tags 与 9,274 行 Genres
```

## 3. 提交前检查

```bash
npm run check
```

等价于依次执行：

| 步骤 | 命令 | 覆盖范围 |
| --- | --- | --- |
| 1 | `npm run typecheck` | TypeScript 类型 |
| 2 | `npm run lint:py` | ruff（`recommender/`、`tests/python/`） |
| 3 | `npm test` | 前端纯函数单测 |
| 4 | `npm run test:py` | Python 单测 + API 契约测试 |

只改了前端就跑前 3 步，只改了 Python 就跑第 2、4 步。CI 会把这三组都跑一遍。

首次准备环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

## 4. 绝对不要提交

以下内容已在 `.gitignore` 中排除，**不要用 `git add -f` 绕过**：

| 路径 | 原因 |
| --- | --- |
| `games.csv` | 395 MiB，超过 Git 单文件上限；通过 Release 或本地放置分发 |
| `recommender/data/` | Qdrant 向量库、BGE-M3 权重、嵌入缓存，均可重新生成 |
| `.env` / `.env.local` | **含真实 API Key**；只提交 `.env.example` |
| `node_modules/`、`.next/`、`.venv/` | 构建与依赖产物 |

提交前自查：

```bash
git status --short          # 确认没有意外的大文件
git diff --cached --stat    # 确认改动量合理（几十 KB，不是几百 MB）
```

如果误把密钥提交进历史，仅删除文件不够——需要从历史中清除并**立即轮换该 Key**。

## 5. 关于本地 Qdrant

本地嵌入式 Qdrant 是**单进程独占**的：同一时间只能有一个进程持有
`recommender/data/qdrant`。因此：

- 跑 `npm run recommend:enrich` 之前必须先停掉 `npm run recommend:api`；
- 两个人共用同一份 `recommender/data/` 无法并行调推荐服务；
- 需要并行时，最省事的做法是改用 server 模式：
  `docker compose up -d qdrant` + `python -m recommender.migrate_qdrant`，
  之后设 `QDRANT_URL=http://127.0.0.1:6333` 即可（见 [docs/docker.md](docs/docker.md)）；
  也可以连远程 Qdrant：设置 `QDRANT_URL` 与 `QDRANT_API_KEY`。

## 6. 代码放置规则

新增代码前先看 [docs/project-structure.md](docs/project-structure.md) 第 3 节。
最关键的一条：`recommender/` 下的 `text.py`、`ranking.py`、`clean.py`、
`selection.py`、`dataset_stats.py` **只能依赖标准库**，否则零依赖单测会失效。
容器编排（`docker/`、`docker-compose.yml`）属基础设施，不参与 Python 包依赖图。

## 7. 标签与数据发布

`games.csv`（395 MB）和向量库快照（247 MB）体积太大，不能进 git，
通过 **GitHub Release** 分发。约定：

- **一次数据修订 = 一个新 tag**，命名 `data-vN`（下一个是 `data-v2`）。
- **绝不移动已发布的 tag。** 移动会让"当时下载到的那份"无法复现，也让
  `data-v1` 究竟对应哪份数据变得不可考。要改数据就发 `data-v2`。
- tag 打在与该数据版本对应的**文档提交**上：README 的直链表、SHA256、
  数据概况都要已经在这个提交里。

标准流程（顺序有意义）：

```bash
# 1. 数据就绪后先算校验和，写进发布说明
sha256sum games.csv steam_games-*.snapshot

# 2. 先把文档提交推到分支（README 直链、数据概况）
git push origin feature-c

# 3. 显式建 tag 并推送 —— 不要用 gh release create --target 隐式建
git tag -a data-v2 -m "data-v2: 30,000 items, bge-m3 + DeepSeek-V4-Flash"
git push origin data-v2

# 4. 基于已有 tag 创建 release 并上传资产
gh release create data-v2 \
  --title "数据分发包：..." \
  --notes-file release-notes.md \
  games.csv steam_games-<date>.snapshot
```

为什么第 3 步要显式建 tag：若让 `gh release create --target <branch>` 隐式创建，
release 记录里的 `targetCommitish` 会存成**分支名**；分支一旦改名或删除，
这个字段就指向一个不存在的分支（`data-v1` 就留下了已删除的
`feature-engineering-baseline`）。先建 tag 再建 release 可以避开这一点。

> `data-v1` 当时由 `gh` 自动创建成轻量 tag；后续建议用 `git tag -a`（annotated），
> 能附带说明与署名。无需回溯修改 `data-v1`。
