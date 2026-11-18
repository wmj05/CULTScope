# CULTScope 阶段 3.5.1：大规模电影数据源规划与项目现状审计

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0（规划稿） |
| 日期 | 2026-11-18 |
| Git 基线 | `main` @ `1587c48`（工作区干净） |
| 文档性质 | 只读审计 + 规划，**不包含任何数据下载、迁移或实现** |
| 适用范围 | 阶段 3.5.2 – 3.5.5 的实施依据 |

**事实标注约定**

- ✅ 表示本次已在当前工作区实际读取文件、执行只读命令后确认。
- ⚠️ 表示依赖外部官方文档，本次环境未联网核实，实施前必须人工确认。
- 本文不虚构任何数据规模、许可条款或 API 限额。所有涉及外部数据源的数字，除结构性字段名外均带 ⚠️。

---

## 1. 审计方法与边界

### 1.1 本次实际执行的操作

| 类型 | 操作 |
| --- | --- |
| Git | `git status --porcelain`、`git log -1`、`git branch --show-current` |
| 目录 | 遍历仓库根目录、`backend/`、`backend/data/*`、`backend/scripts/`、`backend/tests/` |
| 文件 | 读取 `main.py`、`api/movies.py`、`services/movie_service.py`、`core/config.py`、前端 `api/http.js`、`api/cult.js`、`App.vue`、`vite.config.js`、`requirements.txt`、`.gitignore` |
| 数据 | 统计各 CSV/JSON 的字节数与行数（只读） |
| 测试 | 运行既有后端 unittest 与前端测试（不改动数据） |

### 1.2 本次明确未做的事

- 未下载 IMDb / MovieLens / TMDb 任何数据。
- 未修改 `backend/data/knowledge/` 与 `backend/data/candidates/` 中任何文件。
- 未修改 FastAPI 路由、Vue 组件、既有清洗脚本。
- 未安装任何依赖。
- 未执行 `git add / commit / push`。
- 未联网访问 IMDb、GroupLens、TMDb 官方页面，因此所有外部事实均标注 ⚠️。

---

## 2. 仓库结构与数据现状

### 2.1 顶层结构（✅）

```
CULTScope/
├── .gitignore
├── .venv/                     # 本地虚拟环境（已忽略）
├── .screenshots/              # 本地截图（已忽略）
├── backend/
│   ├── app/                   # FastAPI 应用
│   ├── data/                  # 数据层（raw / processed / knowledge / candidates）
│   ├── scripts/               # 数据获取、清洗、校验、审核脚本
│   ├── tests/                 # unittest 测试
│   └── requirements.txt
├── frontend/                  # Vue 3 + Vite + ECharts
└── docs/                      # 本次新建，仅存放规划文档
```

- 根目录**没有** `README.md`，也**没有**课程报告或技术设计文档（✅ 已用 `**/*.md` 检索，仅有 `backend/data/knowledge/review_worksheet_3.2A.md` 与 `backend/data/candidates/cult_candidate_promotion_precheck_batch01.md` 两份数据侧说明）。
- 结论：阶段 3.5 的“大规模数据分析”在此前**没有书面规划**，本文是首份规划文档（✅）。

### 2.2 `backend/data` 实际规模（✅ 实测字节数与行数）

| 目录 | 文件 | 大小 | 行数（含表头） | 说明 |
| --- | --- | --- | --- | --- |
| raw | `movies_raw.json` | 800,099 B | 22,311 | 15 部种子电影的 TMDb 原始响应（多行 JSON） |
| raw | `.gitkeep` | 0 B | 0 | 占位 |
| processed | `cult_movies.csv` | 13,010 B | 16 | 15 部种子清洗前中间结果 |
| processed | `cult_movies_clean.csv` | 13,562 B | 16 | 15 部种子最终清洗结果，**FastAPI 唯一数据源** |
| processed | `match_report.csv` | 698 B | 13 | 12 条匹配记录 |
| knowledge | `cult_seed.csv` | 1,924 B | 13 | 12 条正式 seed |
| knowledge | `cult_sources.csv` | 3,214 B | 12 | 11 条来源 |
| knowledge | `cult_criteria.csv` | 3,029 B | 9 | 8 条 Cult 判定标准 |
| knowledge | `movie_criterion_evidence.csv` | 5,617 B | 18 | 17 条标准证据 |
| knowledge | `cult_tags.csv` | 7,301 B | 23 | 22 个标签定义 |
| knowledge | `movie_cult_tags.csv` | 1,489 B | 9 | 8 条已确认影片标签 |
| knowledge | `movie_cult_tag_candidates.csv` | 2,672 B | 14 | 13 条待审标签候选 |
| knowledge | `review_log.csv` | 17,922 B | 32 | 31 条审核日志 |
| knowledge | `seed_identity_map.csv` | 1,076 B | 13 | 12 条身份映射 |
| knowledge | `review_worksheet_3.2A.md` | 7,810 B | 80 | 3.2A 审核工作表 |
| knowledge | `.review.lock` | 1 B | 1 | 运行时锁（已 gitignore） |
| candidates | `cult_candidates_batch01.csv` | 9,544 B | 21 | 20 部候选 |
| candidates | `cult_candidate_identity_batch01.csv` | 9,588 B | 21 | 20 条身份核对（19 confirmed + 1 needs_review） |
| candidates | `cult_candidate_sources_batch01.csv` | 15,432 B | 39 | 38 条来源（20 主来源 + 18 第二来源） |
| candidates | `cult_candidate_review_batch01.csv` | 2,923 B | 21 | 20 条审核记录 |
| candidates | `cult_candidate_review_packets_batch01.csv` | 12,318 B | 21 | 20 条审核资料包（`human_*` 全空） |
| candidates | `cult_candidate_promotion_precheck_batch01.md` | 7,426 B | 45 | dry-run 预检报告 |

**关键结论（✅）**

1. 现有 raw 层只有 0.8 MB 的 TMDb JSON，约等于“15 部电影详情缓存”，**不是大规模数据集**。
2. processed 层只有 15 行，前端仪表盘展示的就是这 15 部电影，页面已明确声明为样本。
3. knowledge 层 12 部正式 Cult 影片；candidates 层 20 部候选；两者结构与字段完整、稳定。
4. **项目当前不存在 IMDb / MovieLens 数据，也不存在任何跨源 ID 对照表或 analytics 聚合层。**

### 2.3 三类数据的物理位置（✅）

| 数据类别 | 位置 | 写入方 | 读取方 |
| --- | --- | --- | --- |
| 正式 Cult 知识库 | `backend/data/knowledge/` | `review_knowledge.py`（带事务与哈希链） | `cult_service.py` |
| Cult 候选审核 | `backend/data/candidates/` | `build_candidate_review_packets.py`、`validate_candidate_*.py` | 校验脚本、人工审核 |
| 普通大规模电影数据 | **尚不存在** | — | — |

三者目前已经物理隔离；本规划要求未来新增的 analytics 层**不得写入前两者**。

---

## 3. 代码与功能审计

### 3.1 后端目录与职责（✅）

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口，`CORS` 中间件，注册 `movies` 与 `cult` 路由，`/` 与 `/api/health` |
| `backend/app/api/movies.py` | `/api/movies`、`/api/movies/stats` |
| `backend/app/api/cult.py` | `/api/cult/*` 只读知识库接口 |
| `backend/app/services/movie_service.py` | 读取 `data/processed/cult_movies_clean.csv`，内存计算统计 |
| `backend/app/services/cult_service.py` | 只读加载 `data/knowledge/*.csv` |
| `backend/app/services/review_store.py` | 知识库人工审核事务、临时目录、锁、哈希链 |
| `backend/app/schemas/` | Pydantic 响应模型 |
| `backend/app/core/config.py` | `pydantic-settings`，从 `backend/.env` 读取 |

### 3.2 FastAPI 当前数据加载方式（✅）

- **文件直读**：`movie_service.py` 中 `CLEAN_CSV = backend/data/processed/cult_movies_clean.csv`，每次请求 `pd.read_csv(..., encoding="utf-8-sig")`。
- **无缓存、无数据库、无分页**：`list_movies()` 每次全量读取 15 行后在内存过滤；`get_stats()` 每次重算。
- **无大数据承载能力**：当前实现假设文件只有十几行。若直接把千万级数据塞进该文件，前端 10 秒超时与进程内存都会崩溃。
- `config.py` 中存在 `mysql_host / mysql_user / ...` 配置项，但 `requirements.txt` **没有任何数据库驱动**，可判定为“预留但未启用”（✅）。
- `movie_service` 内置 `SAMPLE_NOTE`，前端 `App.vue` 同步展示“仅人工选定样本，不代表整体趋势”的声明（✅）。

### 3.3 API 清单（✅）

| 方法 | 路径 | 数据源 | 参数 | 返回要点 |
| --- | --- | --- | --- | --- |
| GET | `/` | 常量 | — | 名称、版本、状态 |
| GET | `/api/health` | 配置 | — | 是否配置 TMDb Token（不回显） |
| GET | `/api/movies` | `processed/cult_movies_clean.csv` | `decade`、`genre` | `movies[]` 15 部样本 |
| GET | `/api/movies/stats` | 同上 | — | `sample_size`、`sample_label`、`note`、年代/类型分布、评分散点、筛选项 |
| GET | `/api/cult/movies` | `knowledge/*.csv` | 筛选参数 | 正式知识库列表 |
| GET | `/api/cult/movies/{seed_id}` | 同上 | — | 单片详情 |
| GET | `/api/cult/movies/{seed_id}/evidence` | `movie_criterion_evidence.csv` | `include_pending` | 标准证据 |
| GET | `/api/cult/movies/{seed_id}/tags` | `movie_cult_tags.csv` 等 | `include_candidates` | 标签 |
| GET | `/api/cult/criteria` | `cult_criteria.csv` | — | 标准字典 |
| GET | `/api/cult/tags` | `cult_tags.csv` | — | 标签字典 |
| GET | `/api/cult/stats` | `knowledge/*.csv` | — | 知识库统计 |

### 3.4 前端数据接口（✅）

- `frontend/src/api/http.js`：`axios.create({ baseURL: '/api', timeout: 10000 })`。**10 秒超时是大数据接口的硬约束**。
- `frontend/src/api/cult.js`：封装 7 个 `/cult/*` 只读接口，并做错误文案映射（503/404/422）。
- `frontend/src/App.vue`：仪表盘调用 `/movies/stats` 与 `/movies`，使用 `DecadeBarChart.vue`、`GenreBarChart.vue`、`RatingScatterChart.vue` 三个 ECharts 组件；按 `hash` 路由切换看板与知识库。
- `frontend/vite.config.js`：`/api` 代理到 `http://127.0.0.1:8000`。
- 结论：前端当前**没有任何**调用大规模数据接口的逻辑，也没有分页/懒加载机制（✅）。

### 3.5 脚本清单（✅ 实际列出）

| 脚本 | 大小 | 职责（按文件名与既有阶段结论） |
| --- | --- | --- |
| `fetch_tmdb.py` | 12,362 B | 按 `seed_movies.csv` 调用 TMDb，产出 `raw/movies_raw.json` |
| `tmdb_client.py` | 4,845 B | TMDb HTTP 客户端封装 |
| `clean_movies.py` | 7,533 B | 原始 JSON → `processed/cult_movies.csv`、`cult_movies_clean.csv`、`match_report.csv` |
| `seed_movies.csv` | 1,239 B | 15 部种子片单 |
| `build_seed_identity_map.py` | 28,614 B | 构建正式 seed 身份映射 |
| `validate_knowledge.py` | 31,410 B | 知识库 schema/外键/一致性校验 |
| `review_knowledge.py` | 7,738 B | 知识库人工审核与事务写入 |
| `validate_cult_candidates.py` | 12,037 B | 候选数据校验 |
| `validate_candidate_sources.py` | 18,986 B | 候选来源校验 |
| `validate_candidate_identity.py` | 17,138 B | 候选身份校验 |
| `build_candidate_review_packets.py` | 22,006 B | 审核资料包生成（原子写入、人工字段保护） |
| `precheck_candidate_promotion.py` | 21,652 B | 8 项只读 dry-run 预检 |

- 所有脚本均为**一次性全量运行**的命令行脚本，没有参数化的数据源抽象，也没有 manifest/版本记录机制（✅）。
- 现有脚本**没有**任何 IMDb 或 MovieLens 相关代码（✅）。

### 3.6 依赖与测试体系（✅）

`backend/requirements.txt`：

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pandas==2.2.3
requests==2.32.3
python-dotenv==1.0.1
pydantic-settings==2.7.1
httpx==0.28.1
```

- 测试：`backend/tests/` 下 7 个文件（`test_candidate_identity`、`test_candidate_sources`、`test_cult_api`、`test_cult_candidates`、`test_knowledge`、`test_review_packets`、`test_seed_identity_map`），本阶段回归 169 项 OK；前端 7 项通过。
- **无 pytest**，统一使用标准库 `unittest`；测试全部使用临时目录，不触碰生产数据。
- 无 pyarrow / fastparquet / duckdb / sqlalchemy / pymysql。
- 结论：新增数据分析能力应在现有依赖内完成；任何新依赖都必须单独获得批准（✅）。

### 3.7 `.gitignore` 审计（✅）

现有规则覆盖：Python 缓存、`.venv`、`.env*`、`frontend/node_modules`、`frontend/dist`、`*.log`、`*.tmp`、`.screenshots/`、`backend/data/.review_txn/`、`backend/data/knowledge/.review.lock`。

**缺口（高风险）**：

| 缺口 | 后果 |
| --- | --- |
| 未忽略 `backend/data/raw/` 下的大文件 | 800 KB 的 JSON 已入库；未来 GB 级 IMDb/MovieLens 文件会被 `git add .` 误提交 |
| 未忽略 `*.tsv.gz` / `*.gz` / `*.zip` | IMDb 压缩包可直接进入版本库 |
| 未区分 `processed` 中的大文件与小样本 | 未来 analytics 产物可能无差别入库 |
| 未忽略 `backend/data/analytics/`（目录尚不存在） | 新层没有默认保护 |

> 结论：**3.5.2 的第一步必须先补 `.gitignore`，再下载数据**，否则存在污染仓库与 GitHub 的实质风险。

---

## 4. 实现状态判定

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| TMDb 单部电影抓取（15 部种子） | 已实现 | `fetch_tmdb.py`、`tmdb_client.py`、`raw/movies_raw.json` |
| 清洗与类型/年代/评分统计 | 已实现 | `clean_movies.py`、`movie_service.py`、三个 ECharts 组件 |
| 正式 Cult 知识库（12 部） | 已实现 | `knowledge/*.csv` + `cult_service.py` + `/api/cult/*` |
| 候选审核流程（20 部） | 已实现 | `candidates/*.csv` + 4 个校验/生成脚本 + 预检报告 |
| 人工审核字段保护与原子写入 | 已实现 | 3.4.6.1 / 3.4.6.2 的 `merge_human_fields`、`_atomic_replace` |
| 大规模普通电影数据层 | **尚未实现** | 无 IMDb/MovieLens 文件、无 analytics 目录、无相关脚本 |
| 跨源 ID 对照（IMDb ↔ TMDb ↔ MovieLens） | **尚未实现** | 仅有 `seed_identity_map.csv`（12 条，仅正式库内部） |
| 数据 manifest / 血缘记录 | **尚未实现** | 无 manifest、无来源日期、无 SHA-256 记录 |
| 大数据 API（分页/预聚合） | **尚未实现** | `/api/movies` 全量读 15 行，无分页参数 |
| 数据库持久化 | **部分实现（仅配置）** | `config.py` 有 MySQL 配置，无驱动、无迁移、无使用 |
| `.gitignore` 数据保护 | **部分实现** | 覆盖运行时文件，未覆盖大规模数据 |
| 自动化测试 | 已实现 | 169 + 7 项通过 |
| README / 课程报告 / 技术设计文档 | **尚未实现** | 仓库内无 README、无报告 |
| CI（GitHub Actions 等） | 无法确认 | 仓库内无 `.github/`，但未检查远端配置 |
| 教师对数据规模/许可的具体要求 | **无法确认** | 无课程文档可查 |

---

## 5. 三个数据源评估

### 5.1 IMDb 非商业公开数据集

#### 5.1.1 候选文件与必要性

| 文件 | 主要字段 | 对 CULTScope 的价值 | 必要性 |
| --- | --- | --- | --- |
| `title.basics.tsv.gz` | `tconst, titleType, primaryTitle, originalTitle, isAdult, startYear, endYear, runtimeMinutes, genres` | 作品主表：类型、年代、片长、类型标签 | **必需** |
| `title.ratings.tsv.gz` | `tconst, averageRating, numVotes` | 全量评分与投票数，做评分分布/年代趋势 | **必需** |
| `title.akas.tsv.gz` | `titleId, ordering, title, region, language, types, attributes, isOriginalTitle` | 多语言片名、地区版本，可用于中文片名补充与同名消歧 | **可选**（建议 3.5.2 后再评估） |
| `title.crew.tsv.gz` | `tconst, directors, writers` | 导演/编剧维度分析（作者论） | **非必需**（体积大、需再关联 `name.basics`，延后） |
| `title.principals.tsv.gz` | 演员/职员明细 | 演员网络分析 | 本阶段不需要 |
| `title.episode.tsv.gz` | 剧集父子关系 | 剔除剧集时可用 | 非必需（用 `titleType` 即可过滤） |

#### 5.1.2 关键工程事实

- **主键**：`tconst`，格式为 `tt` + 数字（通常 7–8 位，随时间增长）。字符串主键，必须按字符串保存，**不能转 int 后丢失前导零语义**。
- **缺失值**：IMDb 用字面量 `\N` 表示空值，`pandas.read_csv` 必须显式 `na_values="\\N"`，同时 `quoting=csv.QUOTE_NONE`，否则含引号片名会解析错位。
- **非电影条目**：`titleType` 包含 `movie / tvMovie / short / tvSeries / tvEpisode / video / videoGame / tvMiniSeries / tvSpecial / ...`。建议主分析只取 `movie`，`tvMovie` 单独标记，绝不混入。
- **成人内容**：`isAdult` 需保留字段并默认过滤，避免课程展示出现不当内容。
- **年份缺失**：`startYear` 为 `\N` 的记录（未上映/待定）需单独计数，不应直接丢弃而不记录。
- **无 IMDb → TMDb 映射**：IMDb 数据集不提供 TMDb ID，跨源关联必须依赖 MovieLens `links.csv` 或 TMDb 侧返回的 `imdb_id`（见 5.2、5.3）。
- **版本更新**：IMDb 数据集为**周期性全量替换**，不做增量 diff。同一 `tconst` 的评分、投票数会变化；旧片可能因合并/清理而消失。因此**必须记录下载日期与文件 SHA-256**，并把“数据快照版本”写入 manifest，否则分析结果不可复现。
- **规模**：千万级 title 记录、压缩包 GB 级（⚠️ 精确行数与体积以官方 datasets 页面当日为准）。
- **许可**：IMDb 数据集仅限个人与非商业用途，要求保留来源标注并遵守其使用条款（⚠️ 条款全文与当前措辞需在 IMDb datasets 官方页面核实）。**真实 IMDb 数据的使用范围、公开展示（含课程演示、截图、前端页面）及再分发（含上传到公开仓库、网盘或部署环境）必须单独评估官方条款**；在完成评估前，原始数据不得进入 Git，派生数据仅限本地分析与课程内部使用，课程报告需附来源声明。

#### 5.1.3 结论

以 `title.basics` + `title.ratings` 作为**大规模普通电影数据的主干**，理由是：字段稳定、主键稳定、覆盖全年代、可离线批量处理、无需 API Key、不依赖网络稳定性。`akas` 与 `crew` 在 3.5 阶段不进入必需路径。

### 5.2 MovieLens

#### 5.2.1 版本选择

| 版本 | 规模量级 | 适用场景 | 风险 |
| --- | --- | --- | --- |
| `ml-latest-small` | 约 10 万条评分、约 9 千部电影、数百用户（⚠️ 以官方 README 为准） | 开发调试、单元测试夹具、快速验证链接逻辑 | 用户数少，行为分析统计效力弱 |
| `ml-25m` | 约 2500 万条评分、约 16 万用户、约 6 万部电影（⚠️ 以官方 README 为准） | 课程项目的正式行为分析：评分时间趋势、用户活跃度、类型偏好 | 内存与运行时间上升；需分块读取与 dtype 优化 |
| `ml-32m` / `ml-20m` 等 | 其他历史版本（⚠️ 未核实是否仍提供） | 一般不需要 | 版本混乱 |

**推荐**：以 **`ml-25m` 作为正式分析数据集**，`ml-latest-small` 仅作为**开发与测试夹具**（`tests/fixtures/` 中的手工小样本，或本地临时目录），不入库。理由：

1. 25M 的评分量足以支撑“评分行为随时间变化”“类型偏好”“长尾分布”等课程分析，且仍是单机 Pandas 可处理的范围（分块 + `int32/float32` 后内存约数百 MB 级）。
2. `latest-small` 用户规模过小，做时间序列或用户行为结论容易被质疑。
3. 25M 与 IMDb 的链接覆盖率更高，便于构建跨源对照。

> 若课程机器内存不足 8 GB，退回 `ml-latest-small` 并把分析口径改为“方法演示”，需在报告中显式说明——这是**人工决策点 D1**。

#### 5.2.2 文件用途

| 文件 | 字段 | 用途 | 注意 |
| --- | --- | --- | --- |
| `movies.csv` | `movieId, title, genres` | 电影主表 | 年份只能从 `title` 末尾 `(YYYY)` 解析；有少量无年份条目；`genres` 用 `|` 分隔，含 `(no genres listed)` |
| `ratings.csv` | `userId, movieId, rating, timestamp` | 用户评分行为 | 显式 0.5–5.0 半星评分；`timestamp` 为 Unix 秒；用户已匿名化 |
| `links.csv` | `movieId, imdbId, tmdbId` | **跨源关联的核心** | `imdbId` 是纯数字（无 `tt` 前缀），需补零至至少 7 位再加 `tt`；超过 7 位保留全部数字，**不截断**；`tmdbId` 可能为空 |
| `tags.csv` | `userId, movieId, tag, timestamp` | 用户自由标签 | 文本噪声大，非必需；与 `cult_tags.csv` 的受控词表**不可混用** |

#### 5.2.3 评分口径（关键区分）

- MovieLens 的 `rating` 是**单个匿名用户对电影的打分行为**（0.5–5.0），代表偏好与行为。
- IMDb 的 `averageRating` 是**平台汇总加权平均**（1.0–10.0），代表群体评价结果。
- TMDb 的 `vote_average` 是**另一套汇总口径**（0–10）。
- **三者量纲、总体、生成机制均不同，禁止直接平均、拼接或换算后混用**。分析层必须分表存储，并在图表标题/注释中标明口径。

#### 5.2.4 许可与规模

- GroupLens 数据用于研究/教学，要求引用其指定文献并遵守使用条款（⚠️ 具体条款、是否允许再分发需核实官方 README）。
- 数据为**历史快照**（25M 约对应 2019 年前后的评分），与当前 IMDb 快照**不同期**，跨源比较必须注明“非同期”。

### 5.3 TMDb

| 维度 | 评估 |
| --- | --- |
| 现有流程 | `fetch_tmdb.py` + `tmdb_client.py` 已能按标题/年份检索并缓存原始 JSON，产出 `tmdb_id`、`imdb_id`、中文片名、类型、预算/票房 |
| 可复用点 | ① 为少量重点影片补充中文元数据；② 通过 `external_ids` 获取 `imdb_id` 做**高置信度**关联；③ 校验 IMDb 侧缺失的片长/类型 |
| 不适合做主干 | 需要 API Key、受速率限制、网络不稳定、无法一次性获得全量数据；逐条抓取千万级条目不可行（⚠️ 当前速率限制与政策需核实，历史上曾为约 40 次/10 秒） |
| 是否必需 | **否**。IMDb + MovieLens 足以支撑 3.5 的定量分析；TMDb 降级为**可选增强**，仅对已链接的少量记录做补充 |
| 来源标注 | 需在报告/页面标注 TMDb 来源（⚠️ 官方要求的英文声明措辞需核实，常见为 “This product uses the TMDB API but is not endorsed or certified by TMDB.”） |
| 缺失处理 | `budget`/`revenue` 为 0 时按未知处理（现有 `budget_known`/`revenue_known` 已实现该逻辑），不得当作真实 0 |

### 5.4 综合对比

| 维度 | IMDb 数据集 | MovieLens 25M | TMDb API |
| --- | --- | --- | --- |
| 获取方式 | 直接下载压缩包 | 直接下载压缩包 | REST API + Key |
| 主键 | `tconst` | `movieId` | `tmdb_id` |
| 覆盖 | 全年代、全类型（含剧集） | 约 6 万部、偏主流/经典 | 全球，含中文 |
| 评分性质 | 平台汇总均值 | 用户逐条行为 | 平台汇总均值 |
| 离线可用 | 是 | 是 | 否 |
| 网络依赖 | 仅下载时 | 仅下载时 | 每次请求 |
| 与现有项目契合 | 高（补全普通电影层） | 高（补行为维度） | 中（已有客户端，但规模受限） |
| 主要风险 | 体积大、许可限制、快照漂移 | 快照老旧、ID 需补零、许可限制 | 限额、网络、密钥管理 |
| 建议角色 | **主干元数据 + 汇总评分** | **行为评分层** | **可选增强** |

---

## 6. 推荐数据架构

### 6.1 目录分层（与现有结构兼容）

```
backend/data/
├── raw/                          # 原始文件，只读，永不修改
│   ├── tmdb/movies_raw.json      # 现有（保持不动）
│   ├── imdb/                     # 新增，整目录 gitignore
│   │   ├── title.basics.tsv.gz
│   │   └── title.ratings.tsv.gz
│   └── movielens/                # 新增，整目录 gitignore
│       └── ml-25m/*.csv
├── processed/                    # 标准化、一对一映射后的中间层
│   ├── cult_movies_clean.csv     # 现有（保持不动）
│   └── large/                    # 新增，整目录 gitignore
│       ├── imdb_titles_movies.csv
│       ├── imdb_ratings.csv
│       ├── movielens_movies.csv
│       ├── movielens_ratings.csv
│       ├── movielens_links.csv
│       ├── id_crosswalk.csv
│       ├── id_crosswalk_conflicts.csv
│       └── id_crosswalk_unmatched.csv
├── analytics/                    # 新增：只存放小型聚合结果，不整目录忽略
│   ├── decade_distribution.csv
│   ├── genre_distribution.csv
│   ├── rating_distribution.csv
│   ├── votes_distribution.csv
│   ├── ratings_over_time.csv
│   └── link_coverage_summary.json
├── knowledge/                    # 现有，禁止任何 3.5 脚本写入
└── candidates/                   # 现有，禁止任何 3.5 脚本写入

docs/
└── data_manifests/               # 新增：纳入 Git 的数据血缘清单
    ├── manifest_imdb_title.basics.json
    ├── manifest_imdb_title.ratings.json
    └── manifest_movielens.json
```

**目录命名理由**

- `processed/large/` 用子目录而不是直接平铺，避免与现有 15 行 `cult_movies_clean.csv` 混淆。
- **manifest 不放在被整目录忽略的 `raw/imdb/` 或 `raw/movielens/` 中**，统一放 `docs/data_manifests/` 并纳入 Git；否则会出现“要求提交但被忽略”的矛盾。
- `raw/` 与 `processed/large/` 整目录 gitignore；`analytics/` **不整目录忽略**，只允许清单中的小体积聚合文件入库，新增文件必须经人工批准（白名单机制），避免宽泛规则让大文件意外入库。
- 不引入数据库：现有依赖无驱动，且课程项目用 CSV 足以支撑；是否引入 SQLite/MySQL 列为人工决策点 D4。

### 6.2 表设计

#### 6.2.1 `processed/large/imdb_titles_movies.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tconst` | string | 主键，`tt` + **至少 7 位**数字；按原始字符串保存，不补零、不截断 |
| `title_type` | string | 保留原值（`movie` / `tvMovie` …） |
| `primary_title` | string | 原始片名 |
| `original_title` | string | 原始语言片名 |
| `is_adult` | bool | 默认全为 false（过滤后） |
| `start_year` | int（可空） | 起始年 |
| `end_year` | int（可空） | 结束年（电影一般为空） |
| `runtime_minutes` | int（可空） | 片长 |
| `genres` | string | `|` 分隔，保留 IMDb 原值 |
| `ingest_date` | date | 快照日期 |

- 唯一键：`tconst`
- 关联键：`tconst`
- 过滤规则：默认仅 `title_type == "movie"` 且 `is_adult == 0`；`tvMovie` 单独输出或加标记，不混入主表。
- ID 规则：`tconst` 允许 `tt` 后 7 位及以上数字，**不因超过 7 位而截断或重新编号**。

#### 6.2.2 `processed/large/imdb_ratings.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tconst` | string | 主键 + 外键 → `imdb_titles_movies.tconst` |
| `average_rating` | float | 1.0–10.0 |
| `num_votes` | int | ≥ 1 |
| `ingest_date` | date | 快照日期 |

- 唯一键：`tconst`
- 过滤规则：**评分表严格按已保留的 `imdb_titles_movies.tconst` 过滤**，不属于保留主表的评分（剧集、短片、成人内容、重复 ID 等）一律排除。
- 质量规则：`average_rating` ∈ [1,10]；`num_votes` > 0；孤儿 `tconst` 必须为 0。
- 统计要求：被排除的评分记录数必须写入报告与 manifest 的 `excluded_rows` / `excluded_breakdown`，不允许静默丢弃。

#### 6.2.3 `processed/large/movielens_movies.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `movie_id` | int | 主键（MovieLens `movieId`） |
| `title` | string | 原始标题（含年份） |
| `release_year` | int（可空） | 从标题末尾括号解析 |
| `genres` | string | `|` 分隔 |

- 唯一键：`movie_id`
- 解析规则：只取**最后一个**形如 `(YYYY)` 的括号；解析失败记为 NULL 并计入质量报告，禁止丢弃。

#### 6.2.4 `processed/large/movielens_ratings.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | int32 | 匿名用户 ID |
| `movie_id` | int32 | 外键 → `movielens_movies.movie_id` |
| `rating` | float32 | 0.5–5.0 |
| `rated_at` | datetime | 由 `timestamp` 转换（UTC） |
| `rating_year` | int | 派生列，便于聚合 |

- 唯一键：`(user_id, movie_id)`（MovieLens 每个用户对每部电影仅一条评分）
- 质量规则：`rating` ∈ {0.5, 1.0, …, 5.0}；时间戳在合理区间；无孤儿 `movie_id`。

#### 6.2.5 `processed/large/id_crosswalk.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `crosswalk_id` | string | 内部主键（如 `xw_000001`，稳定、可复现） |
| `tconst` | string（可空） | IMDb ID |
| `movielens_movie_id` | int（可空） | MovieLens ID |
| `tmdb_id` | int（可空） | TMDb ID |
| `match_method` | string | `movielens_links` / `tmdb_external_ids` / `manual` |
| `match_confidence` | string | `high` / `medium` / `manual` |
| `verified_at` | date | 核对日期 |
| `note` | string | 备注 |

- 唯一键：`crosswalk_id`；同时对 `tconst`、`movielens_movie_id`、`tmdb_id` 建**唯一性约束**（允许 NULL，但不允许一 ID 多行）。
- **禁止**：使用片名模糊匹配自动合并；`match_method` 不允许出现 `fuzzy_title`。

#### 6.2.6 审计表

| 表 | 字段 | 用途 |
| --- | --- | --- |
| `id_crosswalk_conflicts.csv` | `conflict_id, tconst, movielens_movie_id, tmdb_id, conflict_type, left_source, right_source, detected_at` | 一 ID 对应多条、ID 指向不同影片等冲突，**只记录不自动修复** |
| `id_crosswalk_unmatched.csv` | `source, source_id, title, year, reason, detected_at` | 无法关联的记录，保留供人工处理 |

#### 6.2.7 `analytics/*`（聚合结果）

| 文件 | 粒度 | 主要列 |
| --- | --- | --- |
| `decade_distribution.csv` | 十年 | `decade, movie_count, share` |
| `genre_distribution.csv` | 类型 | `genre, movie_count, share` |
| `rating_distribution.csv` | 0.5 分箱 | `rating_bucket, movie_count` |
| `votes_distribution.csv` | 对数分箱 | `votes_bucket, movie_count` |
| `ratings_over_time.csv` | 年 | `year, movie_count, mean_imdb_rating, mean_votes` |
| `movielens_behavior.csv` | 年 | `year, rating_count, active_users, mean_rating` |
| `link_coverage_summary.json` | 汇总 | `imdb_movies, movielens_movies, linked, link_rate, conflicts` |

> 聚合表必须**自带口径字段**（`source`、`snapshot_date`、`rating_scale`），并在 API 与前端文案中展示，禁止跨源平均。

### 6.3 关联与血缘规则

1. **关联优先级**
   - P1：`links.csv` 的 `imdbId` 补零后与 IMDb `tconst` 精确相等。补零规则为：数字左侧补零至**至少 7 位**，超过 7 位时保留全部数字，再加 `tt` 前缀；**任何情况下都不截断**（例如 `114709` → `tt0114709`，`12345678` → `tt12345678`）。
   - P2：TMDb `external_ids.imdb_id` 与 `tconst` 精确相等（仅对已抓取的少量记录）。
   - P3：`links.csv` 的 `tmdbId` 与现有 TMDb 数据的 `tmdb_id` 精确相等。
   - P4：人工审核（`match_method=manual`，必须有 `verified_at` 与备注）。
   - **不存在 P5**：不做标题相似度、拼音、翻译匹配。
2. **一对多处理**：同一 `tconst` 对应多个 `movieId` 时，全部写入 `id_crosswalk_conflicts.csv`，`id_crosswalk.csv` 中该 `tconst` 置空或标记，等待人工裁决。
3. **血缘**：每次摄取生成 **两份** manifest（`title.basics` 与 `title.ratings` 各一份），写入 **`docs/data_manifests/`** 并纳入 Git（不放进被忽略的 `raw/`）。结构如下：
   ```json
   {
     "source": "imdb",
     "dataset": "title.basics",
     "official_url": "https://datasets.imdbws.com/title.basics.tsv.gz",
     "downloaded_at": null,
     "sha256": "...",
     "file_bytes": 0,
     "raw_rows": 0,
     "retained_rows": 0,
     "excluded_rows": 0,
     "filter_rules": ["titleType == 'movie'", "isAdult == '0'"],
     "script_version": "0.1.0",
     "git_commit": "1587c48",
     "ingest_date": "YYYY-MM-DD",
     "excluded_breakdown": {},
     "output_file": "imdb_titles_movies.csv",
     "output_sha256": "...",
     "output_rows": 0
   }
   ```
   - `downloaded_at` 未知时必须为 `null`，不得伪造；`sha256`、`file_bytes`、行数必须由实际输入文件计算。
   - 评分表 manifest 额外体现“按保留主表过滤”的规则与被排除数量。
4. **可复现性**：同一 manifest + 同一脚本必须产出字节一致的 processed 文件（除 `ingest_date` 外），测试中用 SHA-256 断言。

### 6.4 与 knowledge / candidates 的隔离

| 规则 | 说明 |
| --- | --- |
| 单向只读 | 3.5 的任何脚本**只读** `knowledge/` 与 `candidates/`（若需要对照），**绝不写入** |
| 禁止晋升 | 不得因某片出现在 IMDb/MovieLens 而将其标记为 Cult；不得自动写入 `cult_seed.csv` 或候选表 |
| 禁止回填 | 不得把大规模数据字段（如 IMDb 评分）写入 `knowledge/*.csv` 的既有列 |
| 独立 API 前缀 | 新增接口统一使用 `/api/analytics/*`，与 `/api/movies`、`/api/cult/*` 并列，不改变后者行为 |
| 独立测试 | 新增测试文件，不修改现有 7 个测试文件的断言 |
| 完整性校验 | 每阶段结束校验 `knowledge/` 与 `candidates/` 全部 CSV 的 SHA-256 与基线一致 |

### 6.5 存储格式

- 3.5.2 – 3.5.5 **统一使用 CSV（UTF-8，无 BOM 或 `utf-8-sig` 与现有一致）**，理由：零新依赖、可直接用 Excel 检查、与现有代码风格一致。
- Parquet 能把 25M 评分从约 GB 级压到数百 MB 并显著提速，但需要 `pyarrow`，属于**新依赖**，列为人工决策点 D3。
- 大文件读取统一使用 `chunksize` + 显式 `dtype`，避免一次性载入。

---

## 7. 阶段 3.5.2 – 3.5.5 实施计划

> 以下为**规划**，本次不实施。所有命令以仓库根目录为工作目录、Windows PowerShell 5.1 为准。PowerShell 5 不支持 `&&`，多命令用 `;` 或分行。

### 7.1 阶段 3.5.2：IMDb 摄取与标准化

**目标**：建立可复现的 IMDb 原始层与标准化层，产出普通电影主表与评分表，并记录完整 manifest。

**前置（必须最先做）**
- 更新 `.gitignore`：新增
  ```
  backend/data/raw/imdb/
  backend/data/raw/movielens/
  backend/data/processed/large/
  *.tsv.gz
  *.zip
  ```
  **不要**忽略 `backend/data/analytics/`（其白名单文件需要入库），也不要忽略整个 `backend/data/raw/`（现有 TMDb 小样本仍被跟踪）。
- 保留 `backend/data/raw/.gitkeep` 与各新目录的 `.gitkeep`（若需要版本库保留空目录）。
- 用 `git check-ignore -v` 验证：raw/imdb、raw/movielens、processed/large 应命中；`docs/data_manifests/`、`backend/data/analytics/` 与现有 TMDb 文件不应命中。

**输入**
- `https://datasets.imdbws.com/title.basics.tsv.gz`（⚠️ URL 与当前可用性需核实）
- `https://datasets.imdbws.com/title.ratings.tsv.gz`

**输出**
- `backend/data/raw/imdb/title.basics.tsv.gz`、`title.ratings.tsv.gz`（原始，只读）
- `backend/data/processed/large/imdb_titles_movies.csv`
- `backend/data/processed/large/imdb_ratings.csv`
- `docs/data_manifests/manifest_imdb_title.basics.json`（纳入 Git，不放进被忽略目录）
- `docs/data_manifests/manifest_imdb_title.ratings.json`

**拟新增脚本**
| 脚本 | 职责 |
| --- | --- |
| `backend/scripts/download_imdb.py` | 下载、SHA-256、大小校验，写 manifest；支持 `--check-only` 只校验已有文件 |
| `backend/scripts/ingest_imdb.py` | 流式读取 `tsv.gz`，过滤 `titleType` 与 `isAdult`，规范化 `\N`，输出两张表与两份 manifest；`--dry-run` 只统计不写盘 |
| `backend/tests/test_imdb_ingest.py` | 用小样本夹具测试过滤、缺失值、幂等性 |

**数据质量检查（脚本内断言 + 报告）**
1. `tconst` 在 `imdb_titles_movies` 中唯一；重复 ID 只保留首条并计数。
2. `imdb_ratings.tconst` ⊆ `imdb_titles_movies.tconst`（孤儿率 = 0）。
3. `average_rating` ∈ [1,10]；`num_votes` > 0；非法评分与票数被排除并计数。
4. **评分表排除量必须可核对**：`excluded_rows = raw_rows - retained_rows`，并在 `excluded_breakdown` 中给出“非保留电影 / 非法评分 / 非法票数 / 重复 / 畸形行”。
5. `start_year` 分布合理（如 1870–当前年+5），异常年份计数入报告。
6. `runtime_minutes` 缺失率、`genres` 缺失率、`isAdult` 过滤数量入报告。
7. `titleType` 分布表入报告，确认 `movie` 占比与 `tvMovie` 数量。
8. 重复运行输出 SHA-256 一致（除 `ingest_date`）。

**自动化测试**
- 夹具：10–20 行手工 TSV，覆盖 `\N`、引号、`tvSeries`、`short`、`isAdult=1`、评分缺失。
- 断言：过滤规则、字段类型、唯一键、孤儿检查、`--dry-run` 不写盘、重复运行幂等。
- 回归：全部既有测试保持 169 项通过。

**验收标准**
- `imdb_titles_movies.csv` 行数 > 10 万（⚠️ 以实际下载为准），字段与 6.2.1 完全一致。
- `imdb_ratings.csv` 与主表孤儿率为 0，且排除量在 manifest 中可核对。
- manifest 位于 `docs/data_manifests/`，含 `official_url`、`downloaded_at`（未知为 null）、SHA-256、文件字节数、原始/保留/排除行数、过滤规则、脚本版本、git commit。
- `knowledge/` 与 `candidates/` 的所有 CSV SHA-256 与基线一致。

**兼容性要求**
- 不新增 Python 依赖（`gzip`、`csv`、`pandas` 均已有）。
- 不修改 `movie_service.py`、`/api/movies`、Vue 任何文件。
- 不触碰 `processed/cult_movies_clean.csv`。

**Windows / PowerShell 执行方式**

```powershell
# 1) 确认环境
python --version
$env:PYTHONUTF8 = "1"

# 2) 下载（脚本内部做 SHA-256 与大小校验）
python backend\scripts\download_imdb.py

# 3) 只统计，不写盘
python backend\scripts\ingest_imdb.py --dry-run

# 4) 正式生成（本地生成，不提交）
python backend\scripts\ingest_imdb.py

# 5) 手工核对哈希
Get-FileHash backend\data\raw\imdb\title.basics.tsv.gz -Algorithm SHA256

# 6) 跑测试
python -m unittest discover -s backend\tests -t backend -v
```

> 注：`tar.exe`/`Expand-Archive` 不用于 `.tsv.gz`；pandas 可直接读 gzip，避免解压占用额外磁盘。

---

### 7.2 阶段 3.5.3：MovieLens 摄取与跨源 ID 对照

**目标**：建立 MovieLens 行为评分层，并与 IMDb 建立**可审计**的 ID 对照；所有冲突与未匹配记录留痕。

**输入**
- `ml-25m.zip`（⚠️ 官方下载地址与许可需核实）
- 3.5.2 产出的 `imdb_titles_movies.csv`

**输出**
- `backend/data/raw/movielens/ml-25m/*.csv`（原始）
- `docs/data_manifests/manifest_movielens.json`（纳入 Git）
- `backend/data/processed/large/movielens_movies.csv`
- `backend/data/processed/large/movielens_ratings.csv`
- `backend/data/processed/large/movielens_links.csv`
- `backend/data/processed/large/id_crosswalk.csv`
- `backend/data/processed/large/id_crosswalk_conflicts.csv`
- `backend/data/processed/large/id_crosswalk_unmatched.csv`

**拟新增脚本**
| 脚本 | 职责 |
| --- | --- |
| `backend/scripts/download_movielens.py` | 下载 zip、校验 SHA-256、解压到 `raw/movielens/ml-25m/`，写 `docs/data_manifests/` 清单 |
| `backend/scripts/ingest_movielens.py` | 解析 `movies.csv` 年份、genres 规范化、`ratings.csv` 时间戳转换与 dtype 优化、`links.csv` 补零 |
| `backend/scripts/build_id_crosswalk.py` | 按 P1→P4 优先级构建对照；冲突与未匹配分别落盘；不写 knowledge/candidates |
| `backend/tests/test_movielens_ingest.py` | 夹具测试年份解析、补零、唯一键、孤儿 |
| `backend/tests/test_id_crosswalk.py` | 冲突检测、一对多、无模糊匹配、幂等 |

**数据质量检查**
1. `movie_id` 唯一；`rating` ∈ {0.5,…,5.0}；`user_id` 非空。
2. `ratings.movie_id` ⊆ `movies.movie_id`，孤儿率 = 0。
3. `links.imdbId` 补零至至少 7 位后匹配 `tt\d{7,}`；8 位及以上 ID 完整保留，无法补零或格式异常的计数入报告。
4. 对照覆盖率：`linked_movielens / total_movielens`，写入 `link_coverage_summary.json`。
5. 唯一性：`id_crosswalk` 中 `tconst`、`movielens_movie_id`、`tmdb_id` 各自不得重复（NULL 除外）。
6. 冲突：同一 `tconst` 多个 `movieId`、同一 `movieId` 多个 `tconst`，全部进入 `id_crosswalk_conflicts.csv`。
7. 年份解析失败率、`genres` 为空率入报告。

**自动化测试**
- 年份解析：`"Toy Story (1995)"` → 1995；`"Foo (2000) (II)"` → 2000；无年份 → NULL。
- `imdbId=114709` → `tt0114709`。
- 一对多冲突必须被检测，不得自动选中其中一条。
- 幂等：连续运行两次输出字节一致。
- 回归：既有 169 项 + 3.5.2 新增测试全部通过。

**验收标准**
- 对照表无重复主键、无孤儿、无 `fuzzy` 方法。
- 冲突表与未匹配表均生成且行数与报告一致。
- `knowledge/`、`candidates/` SHA-256 不变。
- 报告明确给出链接覆盖率与“非同期快照”声明。

**兼容性要求**
- 不修改现有 TMDb 流程；`fetch_tmdb.py` 仅在未来需要 P2 时复用其客户端，不改变其行为。
- 不新增依赖（zip 解压用标准库 `zipfile`）。

**PowerShell 执行方式**

```powershell
python backend\scripts\download_movielens.py
python backend\scripts\ingest_movielens.py --dry-run
python backend\scripts\ingest_movielens.py
python backend\scripts\build_id_crosswalk.py --report
python -m unittest discover -s backend\tests -t backend -v
```

---

### 7.3 阶段 3.5.4：analytics 聚合层与数据质量报告

**目标**：在标准化层之上生成小体积聚合表，并产出可复核的质量报告；为后续 API 提供稳定契约。

**输入**
- 3.5.2 / 3.5.3 的 `processed/large/*.csv`

**输出**
- `backend/data/analytics/decade_distribution.csv`
- `backend/data/analytics/genre_distribution.csv`
- `backend/data/analytics/rating_distribution.csv`
- `backend/data/analytics/votes_distribution.csv`
- `backend/data/analytics/ratings_over_time.csv`
- `backend/data/analytics/movielens_behavior.csv`
- `backend/data/analytics/link_coverage_summary.json`
- `backend/data/analytics/quality_report_3_5.md`

**拟新增脚本**
| 脚本 | 职责 |
| --- | --- |
| `backend/scripts/build_analytics.py` | 生成全部聚合表；`--dataset imdb|movielens|all`；`--dry-run` |
| `backend/scripts/report_data_quality.py` | 汇总各层行数、缺失率、冲突数、覆盖率，输出 Markdown |
| `backend/tests/test_analytics.py` | 用手工小样本断言分布总和、分箱边界、口径字段 |

**数据质量检查**
1. 年代分布总和 = 主表行数（允许 `unknown` 桶，且必须显式存在）。
2. 类型分布为“多标签计数”，总和 ≥ 主表行数，需在字段中注明 `multi_label=true`。
3. 评分分布分箱边界：`[0,5), [5,6), …, [9,10]`，总和 = 有效评分数。
4. 投票数对数分箱：`0, 1–9, 10–99, 100–999, 1k–9.9k, 10k–99k, ≥100k`。
5. 时间序列年份连续（缺失年份补 0 并标记）。
6. 每张聚合表必须含 `source`、`snapshot_date`、`rating_scale`。

**自动化测试**
- 小样本（如 6 部电影）逐项断言数值。
- 断言 IMDb 与 MovieLens 结果**不合并**、不出现跨源平均列。
- 断言输出不含 `knowledge/` 或 `candidates/` 的任何 ID。
- 幂等性与回归。

**验收标准**
- 所有聚合表可被纯标准库 CSV 读取，单文件 < 1 MB。
- 质量报告列明：原始行数、标准化行数、过滤数、缺失率、冲突数、覆盖率、生成时间、git commit。
- 报告包含“数据来源与许可”章节（含 ⚠️ 待核实项）。

**兼容性要求**
- 不修改任何现有 API 与前端。
- 不修改 `knowledge/`、`candidates/`、`processed/cult_movies_clean.csv`。

**PowerShell 执行方式**

```powershell
python backend\scripts\build_analytics.py --dataset all --dry-run
python backend\scripts\build_analytics.py --dataset all
python backend\scripts\report_data_quality.py
python -m unittest discover -s backend\tests -t backend -v
```

---

### 7.4 阶段 3.5.5：只读 analytics API、展示接入方案与阶段验收

**目标**：在不破坏现有接口的前提下，提供只读大数据分析 API 与前端接入方案；完成阶段验收与文档收口。

**输入**
- `backend/data/analytics/*.csv`

**输出**
- 新增 `backend/app/api/analytics.py`（前缀 `/api/analytics`）
- 新增 `backend/app/services/analytics_service.py`（读取聚合 CSV，带进程内缓存）
- 新增 `backend/app/schemas/analytics.py`
- 新增 `backend/tests/test_analytics_api.py`
- 更新 `docs/phase_3_5_data_engineering_plan.md` 的“实施结果”章节（后续阶段回填）
- 前端接入方案（**本阶段仅设计，不强制实现**；若实现，必须新增独立页面与独立 `api/analytics.js`）

**建议端点（只读、参数受限）**
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/analytics/summary` | 总影片数、年份范围、链接覆盖率、快照日期 |
| GET | `/api/analytics/decades` | 年代分布 |
| GET | `/api/analytics/genres` | 类型分布（`limit` 默认 20） |
| GET | `/api/analytics/ratings` | IMDb 评分分布 |
| GET | `/api/analytics/votes` | 投票数分布 |
| GET | `/api/analytics/timeline` | 逐年影片数/均分/投票 |
| GET | `/api/analytics/behavior` | MovieLens 年度评分行为（与 IMDb **分区展示**） |

**数据质量检查 / 测试**
1. 响应 schema 与聚合 CSV 字段一一对应。
2. 所有端点只读，不触发任何写入。
3. 参数非法（如 `limit > 100`）返回 422。
4. 接口响应时间 < 300 ms（聚合表小，内存缓存后应远低于此）。
5. 保持 `/api/movies`、`/api/cult/*` 行为不变（回归测试）。
6. 前端 `axios` 10 秒超时下，所有响应 < 1 s。

**验收标准**
- 现有 169 项后端测试全部通过，新增测试通过。
- `/api/movies`、`/api/cult/*` 的响应结构与字段与 3.4 基线一致。
- `knowledge/`、`candidates/` SHA-256 不变。
- 文档补齐：数据来源、快照日期、许可声明、口径说明、复现步骤。
- 前端若接入，必须新增页面，且页面标题明确“普通电影数据，不代表 Cult 身份”。

**兼容性要求**
- 不重写现有路由与组件；只新增文件。
- 不新增依赖。
- API 版本号从 `0.2.0` 升至 `0.3.0` 属于可选，需人工确认。

**PowerShell 执行方式**

```powershell
python -m unittest discover -s backend\tests -t backend -v
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000   # 在 backend 目录下
npm test --prefix frontend
```

---

## 8. 统一质量与测试策略

| 维度 | 规则 |
| --- | --- |
| 测试框架 | 标准库 `unittest`，不引入 pytest |
| 测试数据 | 一律放 `backend/tests/fixtures/` 或 `tempfile.TemporaryDirectory()`，禁止读取生产 CSV 做写测试 |
| 生产数据保护 | 每个阶段结束计算 `knowledge/`、`candidates/`、`processed/cult_movies_clean.csv` 的 SHA-256，与基线比对 |
| 幂等性 | 同一输入连续运行两次，输出字节一致（时间字段除外） |
| 原子写入 | 新脚本写文件沿用 3.4.6.2 的 `mkstemp → fsync → 回读校验 → os.replace` 模式（仅必要处） |
| 失败处理 | 任何校验失败必须非零退出码，并在报告中标明失败项 |
| 编码 | 输出统一 UTF-8；读取沿用 `utf-8-sig` 兼容现有文件 |
| 日志 | 不写 `*.log` 到仓库；控制台输出 + 可选 `--report` 生成 Markdown |

---

## 9. 风险清单

| 编号 | 风险 | 影响 | 缓解 | 阶段 |
| --- | --- | --- | --- | --- |
| R1 | `.gitignore` 未覆盖大规模数据 | GB 级文件误提交，GitHub 仓库污染 | 3.5.2 第一步补规则并验证 `git status` | 3.5.2 |
| R2 | 磁盘空间不足（IMDb 解压后数 GB + MovieLens） | 中途失败、数据不完整 | 直接读 `.tsv.gz` 不解压；下载前检查剩余空间 | 3.5.2/3.5.3 |
| R3 | 内存不足（25M 评分全量载入） | 进程崩溃 | `chunksize` + `int32/float32` + 分块聚合 | 3.5.3 |
| R4 | IMDb 快照漂移 | 结果不可复现 | manifest 记录 SHA-256/日期；分析报告注明快照 | 3.5.2 |
| R5 | MovieLens 与 IMDb 非同期 | 结论失真 | 报告中显式声明，时间序列分开呈现 | 3.5.4 |
| R6 | 评分口径混用 | 学术性错误 | 三源分表、聚合表带 `rating_scale` 字段 | 3.5.4 |
| R7 | 仅靠片名合并导致错误关联 | ID 污染 | 只允许精确 ID 匹配；冲突入审计表 | 3.5.3 |
| R8 | 误把普通电影当作 Cult | 违反数据边界 | 3.5 脚本对 `knowledge/`、`candidates/` 只读；测试断言不写入 | 全程 |
| R9 | 现有 `/api/movies` 被大数据替换 | 前端 10s 超时/崩溃 | 新增 `/api/analytics/*`，旧接口不动 | 3.5.5 |
| R10 | 许可/署名缺失 | 课程合规问题 | 报告与页面加来源声明；实施前核实条款 | 3.5.2–3.5.5 |
| R11 | TMDb 网络不稳定 | 补充流程失败 | TMDb 非必需，失败可跳过 | 后续 |
| R12 | 前端未适配大数据 | 展示卡顿 | 只读预聚合表；必要时分页/懒加载 | 3.5.5 |

---

## 10. 未核实事项（实施前必须人工确认）

| 编号 | 事项 | 原因 | 核实方式 |
| --- | --- | --- | --- |
| U1 | IMDb datasets 当前下载地址、文件体积、行数、更新频率 | 本次未联网 | 打开 `datasets.imdbws.com` 当日页面并截图记录 |
| U2 | IMDb 非商业使用条款全文与署名要求 | 本次未联网 | 阅读官方 datasets 页面 Terms |
| U3 | MovieLens `ml-25m` 当前是否仍提供、精确规模、许可条款 | 本次未联网 | 阅读 GroupLens 数据集 README 与 license |
| U4 | TMDb 当前速率限制与商用/非商用条款 | 本次未联网；历史限额可能已变化 | 阅读 TMDb 官方文档与 FAQ |
| U5 | TMDb 官方要求的署名英文措辞 | 可能调整 | 官方 FAQ / Attribution 页面 |
| U6 | 课程对数据规模、许可、报告格式的具体要求 | 仓库内无课程文档 | 询问授课教师/助教 |
| U7 | 是否允许引入 `pyarrow`（Parquet） | 新依赖需批准 | 与课程/项目负责人确认 |
| U8 | 远端 GitHub 是否已有 CI 配置 | 仅检查了本地 `.github` 不存在 | 查看远端仓库 Settings/Actions |

---

## 11. 需人工决策的问题

| 编号 | 问题 | 选项 | 建议 |
| --- | --- | --- | --- |
| D1 | MovieLens 采用哪个规模 | ① `ml-25m` 正式 + `latest-small` 测试；② 仅 `latest-small` | ①（若内存 < 8 GB 则退 ②，并在报告注明） |
| D2 | 是否引入 `title.akas` | ① 暂不引入；② 3.5.2 后引入用于中文片名 | ①，等基础链路稳定后再评估 |
| D3 | 是否引入 Parquet | ① 继续 CSV；② 新增 `pyarrow` | ①（零新依赖）；确有性能瓶颈再议 |
| D4 | 是否引入数据库 | ① 继续文件层；② SQLite；③ MySQL | ①，课程项目规模不需要数据库 |
| D5 | TMDb 的角色 | ① 可选增强；② 大规模必需 | ①，避免网络与限额风险 |
| D6 | 是否新增 `/api/analytics/*` | ① 新增独立前缀；② 扩展现有 `/api/movies` | ①，避免破坏前端契约 |
| D7 | 前端是否在 3.5.5 接入新页面 | ① 仅设计不实现；② 新增独立页面 | ①，先保证后端与数据质量 |
| D8 | `raw/` 与 `processed/large/` 是否完全不入库 | ① 完全忽略；② 仅入库 manifest 与聚合结果 | ①+②：忽略大文件，提交 manifest 与 `analytics/` |

---

## 12. 本次只读检查记录

| 检查 | 结果 |
| --- | --- |
| `git status --porcelain` | 无输出（工作区干净） |
| `git log -1 --oneline` | `1587c48 feat: complete cult candidate data engineering and review pipeline` |
| `git branch --show-current` | `main` |
| 根目录 | `.git`、`.screenshots`、`.venv`、`backend`、`frontend`、`.gitignore`（无 README） |
| `docs/` | 检查前不存在，本次新建并仅写入本文件 |
| 数据文件 | 22 个（含 `.gitkeep`、`.review.lock`），规模见 2.2 |
| 脚本 | 12 个 Python 脚本 + 1 个种子 CSV |
| 测试 | 后端 7 个测试文件，169 项通过；前端 7 项通过 |
| 外部网络 | 未访问任何数据源官网 |
| 数据写入 | 未修改任何 `knowledge/`、`candidates/`、`processed/`、`raw/` 文件 |

---

## 13. 附：阶段 3.5 完成后应达到的状态（目标态摘要）

1. `raw/imdb/` 与 `raw/movielens/` 存有原始压缩包且被 git 忽略；对应 manifest 位于 `docs/data_manifests/` 并纳入 Git。
2. `processed/large/` 有 IMDb 电影主表、IMDb 评分表、MovieLens 电影/评分/链接表、ID 对照表与两张审计表。
3. `analytics/` 有 7 份小体积聚合结果，每份带口径与快照字段，且仅白名单文件入库。
4. 新增 `/api/analytics/*` 只读接口，现有接口零变更。
5. `knowledge/` 与 `candidates/` 的 SHA-256 与 3.4 基线完全一致。
6. 质量报告与本文档共同构成可复现的数据工程记录。

---

## 14. 3.5.2A 修订记录（2026-11-18）

本节只记录对**规划方案**的修正，不改变第 2–4 节已确认的历史审计事实。

| 编号 | 原方案不一致 | 修正结果 |
| --- | --- | --- |
| C1 | manifest 计划放在 `raw/imdb/`，但该目录被整目录忽略，无法提交 | manifest 统一改放 `docs/data_manifests/`，并纳入 Git；`raw/` 只存原始文件 |
| C2 | 3.5.1 的 `.gitignore` 预置规则包含 `backend/data/analytics/`，与“小型聚合表可入库”冲突 | 取消整目录忽略；改为显式白名单 + 人工批准，新增聚合文件不自动入库 |
| C3 | MovieLens `imdbId` 固定按 `tt%07d` 补零，8 位 ID 会被截断或错配 | 改为补零至至少 7 位，超过 7 位保留全部数字，禁止截断；匹配正则改为 `tt\d{7,}` |
| C4 | 评分表过滤规则未写明“按保留主表过滤”，排除量可能静默丢失 | 明确按 `imdb_titles_movies.tconst` 过滤，并在 manifest 记录 `excluded_rows` 与 `excluded_breakdown` |
| C5 | IMDb 许可只写了“非商业使用”，未覆盖公开展示与再分发 | 新增独立评估要求：使用、公开展示、再分发均须核实官方条款；评估前原始数据不得入库 |

**3.5.2A 已落地内容**（不属于规划修订，仅记录状态）

- `.gitignore` 已增加 `backend/data/raw/imdb/`、`backend/data/raw/movielens/`、`backend/data/processed/large/`、`*.tsv.gz`、`*.zip`，未忽略整个 `raw/` 与 `analytics/`。
- 新增 `backend/scripts/ingest_imdb.py`（流式 gzip TSV、`--dry-run`、原子输出、输出路径保护、manifest）。
- 新增 `backend/tests/test_imdb_ingest.py`（19 项小样本测试）。
- 未下载真实 IMDb/MovieLens 数据，未修改任何现有数据、API 或前端。
