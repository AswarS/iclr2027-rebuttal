## Problem Description

When iterating over multi-dimensional structures (matrices, grids, 2D arrays), nested loops sometimes derive the inner loop's upper bound from the outer loop's index variable rather than from the structure's actual dimension along that axis. This works correctly when the structure is square (both dimensions are equal), but causes out-of-bounds access when the structure is non-square — specifically when one dimension exceeds the other (e.g., a "tall" matrix with more rows than columns). The core issue is that the loop bound implicitly assumes the structure is square, conflating an index from one axis with a valid bound for another axis.

## Root Cause Analysis

The underlying principle is **square-assumption bias**: when implementing logic that involves diagonal, triangular, or band-structure properties, developers mentally model the structure as square. In a square matrix, a row index `i` is always a valid column index, so using `i` as an upper bound for column iteration appears correct. However, for a non-square structure (e.g., a 4×2 matrix), when the row index exceeds the number of columns, using `row_index` as a column bound produces an index that is physically out of range for that axis. The semantic constraint ("iterate over columns below/above the diagonal") and the physical constraint ("iterate only over valid column indices") are conflated into a single expression that only satisfies both when the structure happens to be square.

## Solution Strategy

### 识别信号
- 观测到的现象: `IndexError` 或越界访问异常，仅在结构为"高型"（行数大于列数）时触发，而在方阵或"宽型"（列数大于行数）情况下运行正常。
- 回归表现：此前对方阵有效的功能在接收非方阵输入时崩溃。
- 代码气味：嵌套循环中，内层循环的上界直接使用外层循环的索引变量，而未引用被迭代轴的实际维度。

### 解决步骤
1. **定位所有嵌套循环**，找出内层循环上界由外层循环索引变量推导而来（而非由结构在该轴上的实际尺寸决定）的位置。
2. **使用 `min()` 钳制内层循环上界**，取索引推导值与该轴实际尺寸的较小值。例如，将 `range(row_index)` 改为 `range(min(row_index, num_columns))`，确保语义约束（如"对角线以下的列"）和物理约束（有效列索引）同时被满足。
3. **针对所有形状组合编写测试用例**：方阵、宽型（列多于行）、高型（行多于列），以及退化情况（单行、单列、空结构）。
4. **排查同族函数中的类似模式**：如果上三角判定存在此缺陷，应同步检查下三角、Hessenberg 型、带状结构等所有涉及对角线或三角区域迭代的谓词函数。

### Why This Works

内层循环的上界必须同时尊重两个约束：逻辑约束（例如"对角线以下的列索引"）和物理约束（该轴上的有效索引范围）。取两者的最小值（`min`）是最简洁且语义不变的修正方式——它不改变对方阵的行为，同时在非方阵情况下自然截断越界访问。这本质上是一种**维度边界钳制（dimension-bound clamping）**策略：任何跨轴推导的索引都必须被目标轴的实际尺寸所钳制。

## Boundary Cases
- **方阵（N×N）**：修复前后行为应完全一致，`min(i, N)` 始终等于 `i`，无功能变化。
- **宽型矩阵（行少于列，如 2×4）**：外层循环提前结束，内层上界始终在列范围内，通常不触发 bug，但仍需验证语义正确性。
- **高型矩阵（行多于列，如 4×2）**：这是核心触发场景，当 `row_index ≥ num_columns` 时，未钳制的上界会越界。
- **单行矩阵（1×N）**：内层循环上界为 `min(0, N) = 0`，循环体不执行，需确认这符合预期语义。
- **单列矩阵（N×1）**：内层循环上界始终被钳制为 1，需验证对角线逻辑在此退化情况下的正确性。
- **空结构（0×N 或 N×0）**：外层或内层循环不执行，需确保不抛出异常且返回合理默认值。

## PR Examples
- sympy__sympy-12454