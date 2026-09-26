## Problem Description

Aggregation functions (`max()`, `min()`, `sum()`, `reduce()`, etc.) applied to dynamically-populated collections fail catastrophically when the collection is empty at runtime. This pattern emerges when a code path that performs aggregation is activated by configuration (e.g., a callable attribute exists, a feature flag is set), but the data the aggregation operates over is populated independently and may legitimately be empty. Existing error handling often covers type-related failures (e.g., incompatible types in comparison) but neglects the degenerate empty-input case, creating a blind spot that manifests as an unhandled `ValueError` or `TypeError`.

## Root Cause Analysis

The fundamental issue is **conflating capability configuration with data availability**. Developers implicitly assume that if a code path is reachable (because a method is defined, a setting is enabled, or a feature is configured), then the data required by that code path will necessarily be present. In reality, these are two independent dimensions:

- **Configuration dimension**: Whether the aggregation logic is activated (e.g., a model admin defines `date_hierarchy`, a class has a `get_ordering()` method).
- **Data dimension**: Whether the collection being aggregated contains any elements at runtime.

Aggregation functions like `max()` and `min()` have a mathematical precondition — the input set must be non-empty, because there is no identity element for `max`/`min` over arbitrary types. When this precondition is violated, Python raises `ValueError: max() arg is an empty sequence`. The developer never explicitly validated this precondition because they assumed the configuration gate was sufficient to guarantee non-empty data.

A secondary trap is **incomplete exception handling**: when a `try/except` block already exists to catch one failure mode of the aggregation (e.g., `TypeError` for incompatible types), developers feel the call is "protected" and don't consider that a different exception type can escape from the same call site under different degenerate conditions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ValueError: max() arg is an empty sequence` 或类似的聚合函数异常在生产环境中出现
  - 异常仅在数据为空时触发，属于边界回归（regression-on-edge-case）
  - 已有的 `try/except` 块捕获了其他异常类型（如 `TypeError`），但未覆盖空集合情况
  - 崩溃发生在功能已正确配置但数据尚未填充（或已被清空）的场景中

### 解决步骤
1. **审计所有聚合调用点**：在代码库中搜索 `max(`, `min(`, `sum(`, `reduce(` 等聚合函数，识别所有操作于动态大小集合的调用。
2. **分析集合的数据来源**：对每个调用点，追溯集合的填充逻辑，判断其是否可能在运行时为空。特别关注集合填充与聚合触发条件是否真正耦合——如果它们由不同的配置或运行时条件控制，则空集合是合法的运行时状态。
3. **优先使用内置默认参数**：对于支持 `default` 参数的聚合函数（如 `max(iterable, default=None)`），直接使用该参数处理空集合情况。这比捕获异常更精确地表达意图，且不会掩盖不相关的同类型异常。
4. **无内置默认时显式前置检查**：若聚合函数不支持 `default` 参数（如 `functools.reduce`），在调用前显式检查集合是否为空，并提供合理的回退值。
5. **验证回退值的下游兼容性**：确保选择的默认值（如 `None`）对所有下游消费者都是合法输入。检查后续代码是否对聚合结果做了非空假设（如属性访问、算术运算），必要时在下游也添加空值保护。

### Why This Works

使用 `default=` 参数在**数据源头**以声明式方式处理空集合，而非通过异常恢复机制。这遵循了"显式优于隐式"的原则：

- **精确性**：`default=` 仅在集合为空时生效，不会意外捕获由数据损坏、类型错误等引起的同类型异常。
- **意图清晰**：代码明确表达了"空集合是预期的合法状态，其结果应为某个默认值"，而非"出错了，我们来恢复"。
- **解耦配置与数据**：承认功能激活和数据可用性是独立维度，使代码在零数据场景下也能优雅降级。

## Boundary Cases
- **集合始终由外部输入决定**：即使当前业务逻辑"保证"非空，外部数据源（数据库查询、API 响应、用户输入）的结果集大小不受代码控制，必须防御性处理。
- **默认值的语义传播**：当 `default=None` 被返回后，下游代码可能对结果执行 `.attribute` 访问或算术运算，导致 `AttributeError` 或 `TypeError`，需要端到端验证回退路径。
- **多层聚合嵌套**：外层聚合的输入来自内层聚合的结果，若内层返回默认值，外层的集合可能变为全部是默认值或部分为默认值，需确保语义正确。
- **并发场景下的集合清空**：集合在检查非空与执行聚合之间被其他线程清空（TOCTOU），此时 `default=` 参数比前置检查更安全，因为它是原子性的。
- **空集合与单元素集合的行为差异**：`max([x])` 返回 `x` 本身，但 `max([], default=y)` 返回 `y`——确保这两种情况在业务逻辑中都被正确处理。

## PR Examples
- **django__django-16255**: Django admin 的 `date_hierarchy` 功能在 `ModelAdmin` 上配置了日期层级字段，但当查询集为空时，对空结果集调用 `max()` 抛出 `ValueError`。修复方式为在聚合调用中添加 `default=None` 参数，使空数据集场景优雅降级。