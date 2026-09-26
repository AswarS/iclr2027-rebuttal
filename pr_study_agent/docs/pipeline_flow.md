# PR-SKILL Pipeline Flow

```mermaid
flowchart TD
    %% Input
    INPUT[/"input.jsonl (PR Dataset)"/]
    TAXONOMY[("taxonomy.json<br/>domain / problem_pattern")]

    %% Stage 1
    subgraph S1["Stage 1: PR 语义解构 (Decompose)"]
        S1_PARSE["解析 PR 元数据<br/>repo, patch, problem_statement"]
        S1_INTENT["LLM → 提取 intent / root_cause /<br/>cognitive_error / decision_points"]
        S1_ACTIONS["LLM → 语义动作列表<br/>(type, importance, target, contribution)"]
        S1_DIM["LLM → 维度划分<br/>按 action 聚类为 Dimensions"]
        S1_PARSE --> S1_INTENT --> S1_ACTIONS --> S1_DIM
    end

    %% Stage 2
    subgraph S2["Stage 2: 原子技能补丁化 (Patch Gen)"]
        S2_GEN["LLM → 生成 SkillPatch<br/>Pattern Recognition / Root Cause / Solution Strategy"]
        S2_TAG["Taxonomy 映射 tags<br/>exact → fuzzy → [CANDIDATE]"]
        S2_VAL_GEN["LLM → 从 patch 推导解决方案"]
        S2_VAL_CMP["LLM → 对比 ground truth patch<br/>判断 similarity & consistency"]
        S2_REFINE{"consistent?"}
        S2_REFINE_YES["validated = true"]
        S2_REFINE_NO["LLM → 修正 patch content"]
        S2_EMB["LocalEmbedder → 计算 embedding"]
        S2_SAVE[/"保存到 patch_pool/"/]

        S2_GEN --> S2_TAG --> S2_VAL_GEN --> S2_VAL_CMP --> S2_REFINE
        S2_REFINE -->|Yes| S2_REFINE_YES --> S2_EMB
        S2_REFINE -->|No| S2_REFINE_NO --> S2_EMB
        S2_EMB --> S2_SAVE
    end

    %% Stage 3
    subgraph S3["Stage 3: 分层归纳合并 (Consolidate)"]
        direction TB

        subgraph S3_P1["Phase 1: Patches → Scenarios"]
            S3_LOAD["加载全部 patches"]
            S3_GROUP["按 domain tag 分组"]
            S3_CLUSTER["Embedding cosine 聚类<br/>(threshold ≥ 0.8)"]
            S3_MERGE["LLM → 合并同簇 patches"]
            S3_BUDGET{"clusters > scenario_max?"}
            S3_COMPRESS["贪心合并最相似 pair<br/>直到 ≤ budget"]
            S3_SCENARIO[/"写入 scenario.md"/]

            S3_LOAD --> S3_GROUP --> S3_CLUSTER --> S3_MERGE --> S3_BUDGET
            S3_BUDGET -->|Yes| S3_COMPRESS --> S3_SCENARIO
            S3_BUDGET -->|No| S3_SCENARIO
        end

        subgraph S3_P2["Phase 2: Scenarios → Domain Principles"]
            S3_READ_S["读取 domain 下所有 scenario"]
            S3_ABSTRACT_D["LLM → 抽象领域原则<br/>(≤ domain_max_entries)"]
            S3_WRITE_D[/"写入 domain.md"/]
            S3_READ_S --> S3_ABSTRACT_D --> S3_WRITE_D
        end

        subgraph S3_P3["Phase 3: Cross-domain → General"]
            S3_COLLECT["收集所有 domain 原则"]
            S3_ABSTRACT_G["LLM → 跨域通用原则<br/>(≤ skill_max_entries)"]
            S3_WRITE_G[/"写入 SKILL.md"/]
            S3_COLLECT --> S3_ABSTRACT_G --> S3_WRITE_G
        end

        S3_P1 --> S3_P2 --> S3_P3
    end

    %% Post
    PROMOTE["Taxonomy: 自动晋升候选标签<br/>(count ≥ 3 → 正式标签)"]

    %% Connections
    INPUT --> S1
    S1 --> S2
    TAXONOMY -.->|提供 allowed tags| S2_TAG
    S2_TAG -.->|[CANDIDATE] 回写| TAXONOMY
    S2 --> S3
    S3 --> PROMOTE
    PROMOTE -.-> TAXONOMY

    %% Output
    subgraph OUTPUT["输出: 三层知识库"]
        direction LR
        O_SKILL["SKILL.md<br/>通用原则 (≤8)"]
        O_DOMAIN["domain.md<br/>领域原则 (≤10/domain)"]
        O_SCENARIO["scenario.md<br/>具体模式 (≤15/domain)"]
        O_SKILL --- O_DOMAIN --- O_SCENARIO
    end

    S3 --> OUTPUT

    %% Budget annotation
    subgraph BUDGET_CFG["预算配置"]
        direction LR
        B1["skill_max_entries: 8"]
        B2["domain_max_entries: 10"]
        B3["scenario_max_per_domain: 15"]
    end

    BUDGET_CFG -.-> S3

    %% Styling
    classDef stage fill:#e8f4fd,stroke:#2196F3,stroke-width:2px
    classDef decision fill:#fff3e0,stroke:#FF9800,stroke-width:2px
    classDef storage fill:#e8f5e9,stroke:#4CAF50,stroke-width:2px
    classDef config fill:#fce4ec,stroke:#E91E63,stroke-width:1px

    class S1,S2,S3 stage
    class S2_REFINE,S3_BUDGET decision
    class S2_SAVE,S3_SCENARIO,S3_WRITE_D,S3_WRITE_G,OUTPUT storage
    class TAXONOMY,BUDGET_CFG config
```
