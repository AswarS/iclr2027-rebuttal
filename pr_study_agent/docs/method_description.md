# 2. 方法流程

## 2.1 PR 解析

目标是从原始 PR 中提取结构化知识，建立"从具体代码修改到抽象设计能力"的映射。

### (1) PR Intent 分析

将 diff 拆解为语义级别的 Action——不按文件拆分，而按"行为目标"拆分。一个 Action 可能横跨多个文件，一个文件也可能包含多个 Action 的片段。每个 Action 代表一个完整的行为目标，包含动作描述、作用对象、重要性等级和对 PR 整体意图的贡献说明。

在此基础上，对 PR 进行深层抽象，提取两个关键认知维度：
- **root_cause**：本质问题模式。要求去除一切项目特定名词，抽象到"不同技术栈的人也能理解"的层次。
- **cognitive_error**：导致 bug 的思维模型缺陷。描述的不是代码缺陷本身，而是开发者在编写原始代码时持有的错误假设。

核心提示词结构如下：

```text
Your task has TWO parts:

### Part 1: Decompose into semantic actions
Decompose this PR into semantic actions — logical behavior units that each
accomplish one coherent goal. A single action may span multiple files, and
a single file may contain parts of multiple actions.

### Part 2: Deep abstraction — extract the essential problem
Perform 3 levels of "why" abstraction for root_cause:
  Level 0 (FORBIDDEN — too concrete): "Function X used value Y instead of Z"
  Level 1 (FORBIDDEN — still implementation-bound): "The right branch used a hardcoded default"
  Level 2 (BORDERLINE): "Symmetric binary operations had asymmetric handling"
  Level 3 (CORRECT — essential problem): "Code branches that should apply equivalent
    processing to equivalent inputs used a simplified assumption for some branches,
    which fails when input complexity exceeds the assumption"
```

输出为结构化 JSON，包含 actions 列表、action 间依赖关系、决策点、root_cause 和 cognitive_error。

### (2) 维度拆分

基于上一步的解析结果，判断该 PR 是否包含多个**独立可复用的设计知识**（思维模式），并据此拆分为多个 Dimension。拆分的核心原则：

- 每个维度只专注一种思维模式，对应一种独立的 root cause
- 维度之间可以独立触发——开发者可能遇到其中一个问题而不涉及另一个
- 维度之间可以独立复用——每个维度的推理模式脱离另一个仍然有价值

```text
Split ONLY when ALL of the following are true for each candidate skill:
1. Different root cause: Each skill addresses a fundamentally different
   design principle or cognitive error.
2. Independently triggerable: A developer could encounter one thinking
   problem without the other.
3. Independently reusable: The reasoning pattern of one skill is useful
   without the other.

Do NOT split when:
- The actions address different SYMPTOMS of the SAME root cause
- One part is purely a side-effect of the other
- Splitting would leave one skill without a coherent standalone thinking pattern
```

每个 Dimension 输出包含一个 label、关联的 action 索引列表，以及该维度特有的 root_cause。

---

## 2.2 原子技能生成

根据维度拆分的结果，每个 Dimension 被转化为一个标准化的原子技能（Atom Skill），作为后续聚合的基本单元。

### (1) 技能内容生成

每个原子技能包含以下结构：

- **Tags**（二维标签）：
  - `domain`：问题领域，结构化的 Bug 类别（如 `state-synchronization`、`concurrency`、`boundary-handling`）
  - `problem_pattern`：问题模式，导致 Bug 的底层逻辑缺陷（如 `implicit-assumption-violation`、`partial-propagation`）
- **指令式 Markdown 内容**，由 actions 演变而来，包含三个固定段落：
  - `Pattern Recognition`：什么可观测信号表明正在面对此类问题
  - `Root Cause`：底层结构性/认知性原因
  - `Solution Strategy`：具体的解决步骤指令

生成时要求内容**完全去项目化**——不得包含任何来自原始 PR 的文件名、类名、函数名，确保技能可跨项目复用。

```text
IMPORTANT:
- Content must contain ZERO project-specific nouns (no file names, class names,
  function names from the PR).
- State the pattern generically so it can apply to any similar situation.
```

### (2) 标签映射

生成的标签通过 Taxonomy 系统进行规范化映射：

```python
# 映射优先级：精确匹配 → 模糊匹配（编辑距离≤2 或子串包含）→ 标记为候选
for tag in candidates:
    if tag in valid_tags:          # 精确匹配 → 直接采纳
        accepted.append(tag)
    elif fuzzy_match(tag, valid):  # 模糊匹配 → 映射到最近的合法标签
        accepted.append(fuzzy)
    else:                          # 无匹配 → 保留 [CANDIDATE] 前缀，加入候选池
        accepted.append(f"[CANDIDATE] {tag}")
        add_to_candidate_pool(tag, dim)
```

候选池中出现次数 ≥ 3 的标签会被自动晋升为正式标签，实现 taxonomy 的渐进式演化。

### (3) 反向 LLM 验证

为确保生成的技能确实捕获了有效的问题解决模式，采用"反向验证"机制：

1. **推导阶段**：将原始 Bug 描述（Problem Statement）和刚生成的原子技能喂给一个全新的 LLM 对话，要求它纯粹根据技能的指导推导出 3-5 步解决方案——不允许参考实际代码修复。

2. **对比阶段**：通过 LLM-as-Judge 方法，将推导出的方案与 ground truth patch 进行策略级对比。评判标准是**策略方向是否一致**，而非实现细节是否相同（不惩罚抽象方案缺少具体性）。

```text
NOTE: Approach A is abstract (derived from a reusable pattern). Approach B is
concrete (actual code changes). They should align at the STRATEGY level even if
they differ in specificity. Do NOT penalize Approach A for being more abstract.

- "similarity": 0.0-1.0, strategic alignment (NOT surface-level detail match)
- "consistent": true if core reasoning and strategy direction align (similarity >= 0.6)
```

3. **修正阶段**：若对比结果不一致（similarity < 0.6），系统根据差异反馈自动修正技能内容，然后保存到 Skill Pool。

验证通过后，使用本地 Embedding 模型（all-MiniLM-L12-v2）为技能内容计算语义向量，供后续聚合阶段使用。

---

## 2.3 Skill 聚合

### (1) 分层存储结构

将 Skill Pool 中的原子技能自底向上聚合为完整的三层知识体系，以披露式注入（progressive disclosure）的方式组织：

| 层级 | 名称 | 内容 | 粒度 |
|------|------|------|------|
| Layer 1 | General (SKILL.md) | 跨领域通用原则 | 最抽象 |
| Layer 2 | Domain (domain.md) | 领域级设计原则 | 中等 |
| Layer 3 | Scenario (scenario.md) | 具体问题场景模式 | 最具体 |

### (2) 聚合规则（自底向上）

**Layer 3 → Scenarios**：按 `domain` 标签分组后，使用 Embedding 余弦相似度进行语义聚类（阈值 ≥ 0.8），将同簇的原子技能通过 LLM 合并为一个场景文件。

```python
# 聚类算法：贪心单遍扫描
for i in range(n):
    if assigned[i]: continue
    cluster = [i]
    for j in range(i + 1, n):
        if assigned[j]: continue
        sim = cosine_similarity(emb_i, emb_j)
        if sim >= threshold:  # 默认 0.8
            cluster.append(j)
            assigned[j] = True
    clusters.append(cluster)
```

**Layer 2 → Domain**：从每个 domain 下的所有 scenario 中抽象出领域级原则，由 LLM 归纳生成。

**Layer 1 → General**：收集所有 domain 的原则，由 LLM 进行跨域分析，将反复出现的共性模式提升为通用经验。

### (3) Skill 压缩（预算控制）

为避免知识库无限膨胀，每层设置独立上限：

```yaml
budget:
  scenario_max_per_domain: 15   # Layer 3: 每个 domain 最多 15 个 scenario
  domain_max_entries: 10        # Layer 2: 每个 domain 最多 10 条原则
  skill_max_entries: 8          # Layer 1: 最多 8 条通用原则
```

各层的压缩策略不同：

- **Layer 3**（最容易膨胀）：采用确定性算法硬控制。当 scenario 数量超过上限时，反复找到余弦相似度最高的两个 scenario 进行 LLM 合并，直到满足预算。

```python
# 贪心层次聚类压缩
while len(clusters) > max_count:
    # 找到语义最相近的一对
    best_sim, best_i, best_j = -1.0, 0, 1
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            sim = cosine_similarity(clusters[i].embedding, clusters[j].embedding)
            if sim > best_sim:
                best_sim, best_i, best_j = sim, i, j
    # LLM 合并为一个
    merged = llm_merge([clusters[best_i], clusters[best_j]])
    clusters.remove(best_i, best_j)
    clusters.append(merged)
```

- **Layer 2 & 1**（天然数量可控）：通过 Prompt 指令约束 LLM 输出数量（如 `"abstract 3-8 domain-level principles"`），属于软控制。
