## Problem Description

This pattern occurs when code uses a **positional heuristic** to assign semantic meaning to a data element — such as "the first expression statement in a module body is a docstring" — but only checks the element's **position** and **general category** (e.g., it is a constant/literal) without verifying its **specific concrete type** (e.g., that the constant is a `str`). The element is then passed to an operation valid only for the assumed type (e.g., substring search, string slicing), causing a `TypeError` or other crash when the actual value is an integer, boolean, bytes literal, or any other type that legally occupies the same structural position.

The core mistake is **conflating structural position with type identity**: because a particular position is *usually* occupied by one type, the developer implicitly assumes it *always* is, omitting the type guard that would complete the predicate.

## Root Cause Analysis

Syntactic position **constrains but does not determine** semantic type. A grammar or schema typically allows multiple types in any given slot — for example, Python's AST permits any constant expression as the first statement in a module body, not just string literals. The position is a *necessary* condition for a role like "docstring," but not a *sufficient* one; the type check completes the logical predicate.

The cognitive trap is a **narrowed mental model**: developers associate a position so strongly with one type (because that's the overwhelmingly common case) that they forget other types can legally appear there. This is an implicit assumption violation where the code's invariant is stricter than the actual grammar allows. When an uncommon-but-valid value occupies the position, the unchecked assumption propagates a wrong-typed value into downstream operations that crash.

## Solution Strategy

### 识别信号
- 观测到的现象: `TypeError` 或 `AttributeError` 崩溃，发生在对从特定结构位置提取的值执行类型特定操作时（如对非字符串值调用 `in` 子串搜索、`.split()`、`.startswith()` 等）。
- 崩溃仅在目标位置出现非典型但合法的值类型时触发（如整数字面量出现在通常放置字符串的位置）。
- 代码路径中存在基于位置的条件判断（如 `if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)`），但缺少对 `.value` 具体类型的进一步检查。

### 解决步骤
1. **审计所有位置启发式逻辑**：找到代码中根据元素在结构中的位置赋予其语义角色的每一处。列出该启发式对匹配元素类型所做的全部隐含假设。
2. **在位置匹配之后立即添加显式类型守卫**：验证值的具体类型（如 `isinstance(value, str)`），确保仅在类型匹配时才执行类型特定操作。将类型守卫作为现有条件链中的附加条件，而非引入新的控制流分支。
3. **定义类型守卫失败时的回退行为**：通常是跳过特殊处理，将该元素视为普通节点，不赋予其特殊语义角色。
4. **编写回归测试**：在目标位置放置所有合理的字面量类型（`str`、`int`、`float`、`bool`、`bytes`、`None`、复数等），验证类型守卫正确工作且不会崩溃。

### Why This Works

The fix directly closes the gap between the code's assumed invariant ("this position always holds a string") and the actual invariant ("this position holds any constant"). By adding a single type check to the existing conditional chain, the predicate becomes both positionally and type-correct, matching only the intended semantic role. The minimal nature of the fix — extending a condition rather than restructuring control flow — preserves readability and limits regression risk.

## Boundary Cases
- **Non-string constants in docstring position**: integers, floats, booleans, `None`, bytes, and complex numbers can all appear as the first expression statement in a Python module, class, or function body.
- **Joined string or f-string nodes**: the AST representation may differ from `ast.Constant` (e.g., `ast.JoinedStr`), so the heuristic must account for node type as well as value type.
- **Empty bodies or bodies with no expression statements**: the positional heuristic must handle the case where the target position doesn't exist at all (index out of range).
- **Nested structures**: a docstring-detection heuristic applied recursively to class and function bodies must apply the same type guard at every level, not just the module level.
- **Future literal types**: if the language or schema evolves to allow new literal types, the type guard (using an allowlist like `isinstance(v, str)`) remains safe, whereas a blocklist approach would silently break.

## PR Examples
- **pytest-dev__pytest-11143**: Docstring detection heuristic checked that the first statement was a constant expression but did not verify the constant was a string, causing a crash when a non-string literal (e.g., an integer) occupied the first-statement position.