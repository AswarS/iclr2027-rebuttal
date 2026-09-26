## Problem Description

When a code generator or serialization layer translates high-level mathematical/domain constructs into a target language representation, it encounters constructs that have no direct primitive mapping in the target language's standard library. Instead of decomposing these constructs into equivalent compositions of already-supported primitives, the generator falls back to a "not supported" path — emitting invalid, commented-out, or placeholder code. This pattern arises because the generator's architecture assumes a one-to-one mapping between source constructs and target primitives, failing to recognize that many "unsupported" constructs are algebraically expressible as compositions of primitives the generator already handles.

## Root Cause Analysis

The fundamental issue is an **incomplete abstraction in the code generation layer**: the system treats each high-level construct as requiring a dedicated target-language counterpart, rather than recognizing that the generator's existing primitive set is often expressive enough to represent the construct compositionally. This stems from two architectural blind spots:

1. **Terminal failure assumption**: Unmapped constructs are treated as dead ends rather than decomposition opportunities. The generator lacks a rewrite/lowering phase that would transform unsupported constructs into equivalent expression trees of supported ones before rendering.

2. **Shallow rendering path validation**: Even when a decomposition is attempted, developers fix only the immediate missing handler without tracing the full rendering path of the decomposed output. The decomposition may introduce intermediate sub-constructs (e.g., comparison operators inside piecewise/conditional expressions) that also lack handlers, causing a cascading failure that is only discovered at runtime.

## Solution Strategy

### 识别信号
- 观测到的现象: Code generator emits invalid output (e.g., commented-out code, "not supported" markers, or raw symbolic representations) for specific high-level constructs that are mathematically well-defined and expressible in terms of basic operations.
- The target language supports all the primitive operations needed to express the construct (arithmetic, conditionals, comparisons), but the generator has no dedicated handler for the high-level construct itself.
- Tests produce wrong output or fail to generate compilable/executable code for expressions involving special functions, domain-specific operators, or composite mathematical objects.

### 解决步骤
1. **Identify the algebraic or logical equivalence**: Determine whether the unsupported construct has a well-known decomposition into primitives already supported by the generator. Consult mathematical references, domain specifications, or the construct's own `rewrite()` method if available (e.g., a special function expressible as a piecewise/conditional over basic arithmetic).

2. **Add a dedicated rewrite handler**: Implement a handler in the code generator that rewrites the unsupported construct into its equivalent composition of supported primitives, then delegates rendering to the existing printers for those primitives. This keeps the decomposition logic localized and the rendering pipeline uniform.

3. **Trace the full rendering path**: Walk the entire expression tree produced by the decomposition and verify that every intermediate node — conditionals, comparison operators, sub-expressions — has a working handler in the generator. Do not assume that "obvious" constructs like relational operators are already covered.

4. **Add general-purpose handlers for any missing intermediate construct classes**: If the decomposition reveals that an entire class of sub-constructs (e.g., all relational operators `<`, `>`, `<=`, `>=`, `==`, `!=`) lacks handlers, implement handlers for the full class — not just the specific instance needed by the current fix. This prevents the same gap from resurfacing with the next decomposition.

5. **Add comprehensive tests**: Test the decomposed output end-to-end, including edge cases that exercise the intermediate constructs independently (e.g., standalone relational expressions, nested conditionals, boundary values of the original construct).

### Why This Works

Code generators are fundamentally **tree-to-text transformers**. Their power comes not from having a handler for every possible source construct, but from having handlers for a sufficient set of primitives and a rewriting layer that can lower complex constructs into those primitives. Algebraic decomposition leverages this architecture: by rewriting an unsupported node into a subtree of supported nodes, the existing rendering pipeline handles the rest without any target-language-specific helper functions or runtime dependencies. This approach is more maintainable, composable, and self-documenting than ad-hoc workarounds, and it naturally extends the generator's coverage as new decompositions are added.

## Boundary Cases
- **Decomposition introduces constructs that are themselves unsupported**: The fix must recursively ensure all intermediate constructs are printable; otherwise the decomposition merely shifts the failure deeper into the expression tree.
- **Numerical edge cases in the decomposition**: Algebraic equivalences may have domain restrictions (e.g., division by zero, branch cuts) that differ from the original construct's semantics. The decomposition must preserve correctness across the full input domain.
- **Multiple code generation backends**: A decomposition valid for one target language may not be optimal or correct for another. Each backend may need its own rewrite strategy or may already support the construct natively.
- **Performance implications**: A piecewise/conditional decomposition may be less efficient than a direct intrinsic call. If the target language later adds native support, the handler should be easy to replace.
- **Nested compositions**: When the unsupported construct appears inside another complex expression (e.g., as an argument to another function or inside a summation), the decomposition must integrate cleanly with the surrounding expression tree rendering.

## PR Examples
- sympy__sympy-11400