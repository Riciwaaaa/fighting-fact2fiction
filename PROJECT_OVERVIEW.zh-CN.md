# Fighting Fact2Fiction — 项目总览（中文版）

> 本文件为 `PROJECT_OVERVIEW.md` 的中文翻译，仅供个人参考，未纳入 git 提交。

针对 **Fact2Fiction** 知识库投毒攻击，防御 **InFact** 事实核查系统——利用事实核查模型自身的
内部知识，结合**子命题级别的证据验证（sub-claim-level evidence verification）**防御机制。

- **攻击方（Fact2Fiction）：** 向某条 claim 的本地知识库中注入伪造的"证据"文档（URL 以
  `/created` 结尾），使基于检索的事实核查系统采信这些伪造证据，从而翻转其判决结果。
- **受害方（InFact）：** 一个基于问答（QA）的事实核查系统——将 claim 分解为若干子问题，
  针对每个子问题检索证据、作答，最后综合全文进行判决。
- **我们的防御机制：** 定位"无检索模型独立推理结果"与"被投毒的事实核查结果"产生分歧的位置，
  对可疑证据进行验证——真实事件会留下佐证性的背景痕迹（corroborating context），而伪造证据
  则没有；据此对未通过验证的证据予以否定，再交由 InFact 自身的判决模块重新裁决。

任务范围限定在 AVeriTeC 数据集的**二分类子集**（仅 Supported / Refuted 两种结果）。

---

## 1. 仓库目录结构

```
fighting-fact2fiction/
├── DEFAME/                     # InFact 实现 #1 —— 用于"干净知识库"相关工作 & benchmark 定义
│   ├── infact/                 #   事实核查核心库（eval、tools、modules、prompts）
│   ├── data/AVeriTeC/          #   数据集：dev.json、dev_binary.json、test/train.json
│   │   └── knowledge_base/     #   下载得到的知识库，约 48 GB（不纳入 git —— 见第 6 节）
│   ├── config/                 #   全局配置、模型注册表、API keys（key 已在 gitignore 中排除）
│   └── scripts/                #   DEFAME 入口脚本（averitec/evaluate.py、run.py）
│
├── Fact2Fiction/               # InFact 实现 #2（另一份独立拷贝）+ 攻击代码
│   └── src/
│       ├── infact/             #   事实核查核心库的第二份拷贝
│       ├── attack/             #   Fact2Fiction 投毒攻击本体（main.py、attack_utils.py）
│       │   ├── attack_results/ #     缓存的投毒产物（pkl 文件）（不纳入 git —— 可重新生成）
│       │   └── attack_cache/   #     缓存的 embedding                （不纳入 git —— 可重新生成）
│       ├── fc_results/         #   攻击前（干净状态）各模型的 InFact 报告
│       └── config/
│
├── baseline/                   # "model-only"（纯模型独立推理）事实核查的基础组件
│   ├── llm_client.py           #   OpenRouter 调用封装（call_glm）
│   ├── label_parser.py         #   判决字符串 → 标准化 label（支持二分类）
│   └── .env                    #   OPENROUTER_API_KEY（已在 gitignore 中排除）
│
├── experiments/                # 整个实验流水线（我们所有的工作）—— 见第 3、4 节
│   ├── *.py                    #   流水线脚本 + 分析脚本
│   └── runs/                   #   各次实验运行的输出结果（结果本身已纳入 git；见第 6 节）
│
└── PROJECT_OVERVIEW.md         # 本文件的英文原版
```

### 为什么会有两份 `infact`？
`DEFAME/infact` 与 `Fact2Fiction/src/infact` 是两个**几乎完全相同、但相互独立**的 Python
包，二者都以 `infact` / `config` 的包名导入。这两份代码**无法在同一个 Python 解释器进程中共存**
（包名会冲突）。因此整条流水线严格遵循"进程隔离"原则：

- **干净知识库 / benchmark 相关的一侧** → 运行在 `DEFAME/` 目录下（cwd + sys.path 均指向此处）。
- **攻击 / 被投毒知识库 / 重新判决相关的一侧** → 运行在 `Fact2Fiction/src/` 目录下。
- 两侧之间**只通过磁盘上的 JSON 文件通信**，绝不在同一进程内直接交互。

任何对共享的 benchmark / label 空间的修改（例如 `AVeriTeCBinary`）都必须**同时应用到两份拷贝**，
否则其中一份会过期失效、与另一份不一致。

---

## 2. 数据

- **AVeriTeC dev 集** = 500 条 claim，4 种 gold label（Supported / Refuted /
  Not Enough Evidence / Conflicting Evidence-Cherrypicking）。
- **`dev_binary.json`**（由 `experiments/make_binary_averitec.py` 生成）= 仅保留其中
  Supported/Refuted 的 427 条 claim，每条都携带一个 `orig_id` 字段，使其 claim id 仍然等于
  该条目在原始 `dev.json` 数组中的位置下标（这样才能让所有已缓存的投毒产物继续保持有效）。
- **`AVeriTeCBinary`** benchmark 类（在两份 `infact/eval/benchmark.py` 拷贝中均有定义）会加载
  `dev_binary.json`，并且只向判决模块（judge）提供 Supported/Refuted 两个选项。
- **攻击可用样本池 = 53 条 claim**：即在攻击发生**之前** InFact 就已经答对的那些二分类 claim
  （通过 `get_all_valid_claim_ids` 筛选得到）。所有实验都是在这 53 条的子集上进行的。

---

## 3. 流水线（共 4 个阶段）

每个阶段对应 `experiments/` 下的一个脚本；每个脚本读取上一阶段产出的 JSON，并将结果写入某次
运行目录（`experiments/runs/<run>/`）。默认的 `--results-dir` 指向
`runs/03_mimo_27claim_binary`（当前正在使用的这次运行）。

```
                 make_binary_averitec.py ──► DEFAME/data/AVeriTeC/dev_binary.json
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ 阶段 1  run_attacked_infact.py   （Fact2Fiction 环境）                              │
  │   对知识库投毒（使用缓存）→ 运行 InFact → 导出被攻击后的判决结果 + 采信的证据           │
  │   输出：runs/<run>/attacked_infact_dumps/{cid}.json                                │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ 阶段 2  infact_supplement.py     （DEFAME 环境）                                    │
  │   model-only 事实核查（evidence_rag_probe.factcheck_*）→ 判决 + 推理要点列表          │
  │   【一致性跳过闸门 skip-gate】：若 model-only 判决 == 被投毒判决，则到此为止             │
  │   否则继续检测 InFact 遗漏了哪些信息（gap detection）                                 │
  │   输出：runs/<run>/infact_supplement.jsonl                                          │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ 阶段 3  subclaim_defense.py      （Fact2Fiction 环境）   ← 防御机制本体               │
  │   A 逐条列出   InFact 的子命题 + 其采信证据  vs  model-only 的推理要点                 │
  │   B 对齐比对   逐条子命题标注：一致 / 冲突 / 未被model-only涉及                        │
  │   C 重要性筛选 剔除掉那些即便被推翻也不会改变最终判决的分歧点                           │
  │   D 提出验证角度 由 model-only 提出"侧面佐证型"的验证检索query                        │
  │   E 执行验证    对被投毒知识库检索 → 判定可信度：fabricated（伪造）/                   │
  │                doubtful（存疑）/ trustworthy（可信）                                │
  │                → 若有可信证据则据此重新作答，否则标记为 UNRESOLVED（无法确认）          │
  │   F 补充证据    为"确有必要"的遗漏要点补充新的问答对                                  │
  │   G 重新判决    交由 InFact 自身的 Judge 模块，对清洗后的问答内容重新裁决               │
  │   输出：runs/<run>/subclaim_defense/{cid}.json（完整的分阶段追踪记录 + 最终判决）      │
  └──────────────────────────────────────────────────┬───────────────────────────────┘
                                                     │
  ┌──────────────────────────────────────────────────┼───────────────────────────────┐
  │ 阶段 4  eval_table.py  +  analyze_defense.py                                       │
  │   eval_table.py     → 四系统对比表（Accuracy / F1 / Macro-F1）                       │
  │   analyze_defense.py → T1~T6 分析表（理论上限、防御成功率、伪造证据识别混淆矩阵、       │
  │                        与 model-only 的互补性分析、skip-gate 统计）                   │
  │   输出：runs/<run>/eval_table.{md,csv}、eval_predictions.csv、analysis.md、          │
  │         analysis_*.csv                                                             │
  └────────────────────────────────────────────────────────────────────────────────────┘
```

**对比的四个系统**（每条 claim 均对齐为标准化 label）：
`model_only`（纯模型独立推理）· `infact`（干净未投毒版本，在该样本集上等价于 gold label）·
`f2f_poisoned_infact`（被投毒的 InFact）· `subclaim_verified_poisoned_infact`（我们的防御机制）。

---

## 4. 脚本速查（均在 `experiments/` 目录下）

| 脚本 | 所属阶段 | 运行环境 | 作用 |
|---|---|---|---|
| `make_binary_averitec.py` | 数据准备 | 任意 | 生成 `dev_binary.json` |
| `run_attacked_infact.py` | 1 | Fact2Fiction | 运行被投毒的 InFact，导出被攻击后的判决 + 证据 |
| `evidence_rag_probe.py` | 2（库函数）| DEFAME | model-only 事实核查：分两次调用（先输出纯推理要点列表 → 判决，再单独生成检索query） |
| `infact_supplement.py` | 2 | DEFAME | model-only 判决 + gap 检测 + 一致性跳过闸门 |
| `poisoned_kb.py` | 3（库函数）| Fact2Fiction | 重建被投毒的逐条 claim 知识库（重新拟合 KNN 索引 + 磁盘缓存） |
| `subclaim_defense.py` | 3 | Fact2Fiction | 子命题证据验证防御机制本体（A~G 各阶段） |
| `rejudge_assisted.py` | （旧方案）| Fact2Fiction | 已被淘汰的"文档级证据合并"防御方案 |
| `eval_table.py` | 4 | 任意（需 sklearn） | 四系统指标对比表 |
| `analyze_defense.py` | 4 | 任意 | T1~T6 分析表 + 对应 CSV |
| `combine_results.py` | 旁支 | 任意（需 sklearn） | baseline 100 条 claim 的合并对比 CSV |
| `combine_all_runs.py` | 旁支 | 任意 | 跨全部 4 次运行的长表格式（long-format）CSV |
| `combine_run03_wide.py` | 旁支 | 任意 | 第 03 次运行的逐 claim 宽表格式（wide-format）CSV |

**解释器要求：** 任何涉及知识库 / embedding / sklearn 的脚本，都必须使用
`/home/ubuntu/.venv312/bin/python3.12`（仅限 CPU）运行。纯 JSON 处理的脚本
（`analyze_defense`、`combine_*`）可用普通 `python3` 运行。

### 关键机制说明
- **两次调用式 model-only**（`evidence_rag_probe.py`）：第一次调用只输出纯粹的原子化推理要点
  列表 + 一个判决（不带任何叙述性的辩护性文字）；第二次调用再为每条要点单独生成一个检索
  query。这样可以避免"既要推理又要写检索词"这两件事互相干扰、拖累推理质量。
- **一致性跳过闸门**（`canon()`，定义在 `infact_supplement.py` / `subclaim_defense.py` 中）：
  如果 model-only 的判决已经与被投毒的判决一致，那就说明没有什么需要纠正的 → 直接跳过整个
  防御流程，原样保留原判决。
- **重要性筛选闸门**（第 C 阶段）：只有当"解决某个分歧点确实可能改变最终判决"时，才会去验证
  它；其余的分歧一律在产生任何昂贵调用之前就被剔除。
- **侧面佐证式检索**（第 D、E 阶段）：验证用的检索 query 会去探查该断言**周边**的信息
  （是否有独立信源报道、当事人后续的反应、该断言理应引发的争议或批评、事实核查媒体的
  报道等）——真实事件会留下这类痕迹，而伪造内容则不会。如果检索不到任何佐证，就判定为
  `fabricated`（伪造）。这一步检索是针对**被投毒后**的知识库进行的（这更符合现实情况：
  一个已被部署的系统本来就无法访问一份"干净"的语料库）。
- **所有 prompt** 均按照 InFact 自身的文风撰写（参见
  `Fact2Fiction/src/infact/prompts/{judge,propose_queries,pose_questions_json}.md`）。

---

## 5. 各次实验运行记录（`experiments/runs/`）

详见 `experiments/runs/README.md`。简要汇总如下：

| 运行目录 | claim 数量 | 使用模型 | 备注 |
|---|---|---|---|
| `01_deepseek_10claim` | 10 | deepseek-v4 | 最早期版本，model-only 为单次调用式，已被淘汰 |
| `02_mimo_27claim_4class` | 27 | mimo-v2.5-pro | 二分类改造之前；使用"文档级证据合并"防御方案（效果不佳） |
| `03_mimo_27claim_binary` | 53 | mimo-v2.5-pro | **当前 / 最终版本** —— 二分类 + 子命题验证防御 |
| `04_results_baseline_100claim` | 100 | 4 个模型 | 攻击前 vs 攻击后的基线对比（独立的旁支实验） |

**当前核心结果（第 `03` 次运行，N=53）：** 子命题验证防御机制将被投毒后 InFact 的准确率
从 **0.642 提升到 0.868**（与 model-only 纯推理持平），且**没有出现任何"越修越错"的回退情况**；
在全部 78 条经过验证的子命题中，伪造证据识别达到 **100% 召回率、0% 误判率**。完整数据见
`runs/03_mimo_27claim_binary/analysis.md`。

---

## 6. 哪些内容纳入了版本控制，哪些没有

**已纳入 git（体积小，且是真正的实验记录）：**
- 全部代码（`experiments/*.py`、`baseline/`、两份 `infact` 核心库、攻击代码）
- 体积较小的数据集 JSON（`dev.json`、`dev_binary.json`、`test.json`、`train.json`）
- 体积较小的攻击前报告（`Fact2Fiction/src/fc_results/`）
- **`experiments/runs/` 下的全部运行结果**（判决结果、追踪记录、各类表格——总计约 13 MB）

**已在 gitignore 中排除（体积大 / 可重新生成 / 属于下载资源 —— 绝不能提交）：**
- `DEFAME/data/AVeriTeC/knowledge_base/` —— 下载得到的知识库，约 48 GB（其中单个文件最大
  可达 11 GB；远超 GitHub 单文件 100 MB 的上限）
- `Fact2Fiction/src/attack/attack_results/` + `attack_cache/` —— 约 1.1 GB 的投毒产物 /
  embedding 缓存
- `DEFAME/out/`、`Fact2Fiction/src/out/`、`baseline/results/` —— 可重新生成的输出结果
- 密钥文件（`baseline/.env`、`DEFAME/config/api_keys.yaml`）、`__pycache__/`、虚拟环境目录

经验法则：**提交代码 + 体积较小的结果文件**（它们才是我们实验发现的真实记录）；
**永远不要提交那个几十 GB 的知识库或投毒缓存**——它们要么是下载得到的、要么可以随时重新生成，
提交上去只会超出 GitHub 的限制。
