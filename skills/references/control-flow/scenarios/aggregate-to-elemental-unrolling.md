## Problem Description

When aggregate predicate functions like `all()` or `any()` are used in assertions with inline generator expressions or comprehensions, the assertion failure message collapses all per-element boolean results into a single `False` or `True` value. This destroys the diagnostic information needed to identify *which specific element* caused the failure. The problem pattern is **aggregate-to-elemental unrolling**: recognizing when an opaque aggregate operation can be decomposed back into its constituent element-level evaluations to restore lost granularity in diagnostic output.

## Root Cause Analysis

Aggregate functions like `all()` and `any()` are **information-destroying by design** — they reduce N individual boolean verdicts into a single boolean. When assertion rewriting machinery treats these as ordinary function calls, it only captures and displays the final collapsed result (e.g., `assert False`), which tells the user nothing about which element failed or why.

The underlying principle is an **implicit assumption violation**: the default call-handling logic assumes that showing a function's return value provides sufficient diagnostic context. This assumption holds for most functions but fundamentally breaks for aggregation functions whose entire purpose is to discard per-element detail. The cognitive trap is treating all function calls uniformly when certain well-known functions have a decomposable internal structure that, if surfaced, dramatically improves debuggability.

The key enabler for a fix is that when the argument to `all()`/`any()` is a generator expression or comprehension, the loop variable, predicate expression, and iterable are all available as distinct AST nodes — making safe syntactic decomposition possible without runtime guessing.

## Solution Strategy

### 识别信号
- 观测到的现象: Assertion failure messages show only `assert False` or `assert True` with no indication of which element in the collection caused the aggregate predicate to fail — **incorrect-error-message** / **wrong-output** that lacks actionable diagnostic detail.

### 解决步骤
1. **Detect the decomposable pattern in the call visitor**: When visiting a `Call` AST node, check whether the function is a known aggregate (`all` or `any`) and its single argument is a generator expression or comprehension. If not, fall through to default call-handling logic.
2. **Extract the comprehension components**: From the generator expression / comprehension AST, isolate the iterable expression, the loop variable(s), any filter conditions, and the per-element predicate expression as distinct AST nodes.
3. **Unroll the iteration within the rewriting framework**: Evaluate the iterable at runtime, then iterate through its elements. For each element, bind the loop variable and evaluate the per-element predicate, collecting both the element value and its individual boolean result.
4. **Format per-element results into the explanation**: Build explanation lines showing each element alongside its pass/fail status (e.g., `item=3: True`, `item=5: False`). Insert these into the existing explanation list managed by the assertion rewriting infrastructure.
5. **Preserve original evaluation semantics**: Still evaluate the original `all()`/`any()` call normally so the assertion passes or fails exactly as before. The enhancement is purely additive — enriching the diagnostic output without altering control flow or assertion outcomes.

### Why This Works

The solution works because it **reverses the information destruction** at the diagnostic layer without changing the semantic layer. By recognizing that `all(pred(x) for x in iterable)` is syntactically decomposable, the rewriter can reconstruct the per-element detail that `all()` discards. Operating within the existing assertion rewriting framework (augmenting the call visitor rather than synthesizing new loop AST statements) keeps the change minimal, avoids duplicating infrastructure, and maintains compatibility with the rest of the introspection pipeline. Restricting to syntactically decomposable forms (generator expressions and comprehensions) ensures the necessary components are always available as explicit AST nodes, making the transformation safe and deterministic.

## Boundary Cases

- **Non-decomposable arguments**: When `all()` or `any()` receives a plain variable, function call result, or other opaque expression (not a generator/comprehension), the enhancement must be skipped entirely, falling back to default call-handling behavior.
- **Nested comprehensions or multiple `for` clauses**: Generator expressions with multiple loop variables or nested iterations require careful handling of variable binding scope during unrolling.
- **Comprehensions with `if` filter clauses**: The filter condition must be respected during unrolling so that only elements passing the filter are evaluated and displayed.
- **Large iterables**: Unrolling thousands of elements could produce overwhelming output; a truncation or summarization strategy may be needed.
- **Side-effecting predicates or iterables**: Unrolling evaluates the predicate per-element in addition to the original `all()`/`any()` call, potentially doubling side effects — though this is acceptable in a testing/diagnostic context.
- **Custom `all`/`any` overrides**: If a user shadows the builtins, the special-case detection should verify the function identity to avoid incorrect decomposition.

## PR Examples
- pytest-dev__pytest-5103