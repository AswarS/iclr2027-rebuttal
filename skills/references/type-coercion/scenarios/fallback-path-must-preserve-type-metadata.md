## Problem Description

When a system derives type metadata (e.g., scalar vs. array, dimensions, pointer semantics) by analyzing how symbols are **used** within an expression, a secondary code path that handles declared-but-unused arguments may silently discard intrinsic type information. This occurs because the fallback path constructs argument descriptors using minimal defaults (e.g., treating everything as a scalar) rather than consulting the argument's own type properties (shape, rank, dimensions). The result is that array or matrix arguments not referenced in the expression body lose their dimensionality and are incorrectly downgraded to scalars in the generated output.

This pattern is common in code generation, serialization, API binding, and any transformation pipeline where:
- A primary path infers rich metadata from expression-level analysis.
- A fallback path exists for symbols that escape expression-level discovery.
- The fallback path was written under the implicit assumption that it would rarely (or never) be exercised with composite types.

## Root Cause Analysis

An argument's type — scalar, vector, matrix, tensor — is an **intrinsic property of the symbol itself**, encoded in attributes like `.shape`, `.rank`, or analogous type descriptors. It is not a property of how the symbol happens to be used in a particular expression. When the primary code path discovers a symbol within the expression, it typically has access to contextual usage information that coincidentally aligns with the symbol's intrinsic type. This creates a false sense that the metadata derivation is correct "by construction."

The fallback path, triggered when a declared argument is absent from the expression, lacks this contextual usage information. Developers treat this path as a rare error-recovery case and apply minimal logic — often just wrapping the symbol name in the simplest descriptor type (a scalar). The cognitive trap is the **implicit assumption that all declared arguments will appear in the expression**, which makes the fallback path seem unimportant. In reality, it is a legitimate and necessary path for functions with fixed signatures, library interop contracts, partial evaluation, or constant-returning functions.

The asymmetry between the two paths — one type-aware, one type-blind — is the root cause. Any type metadata that the primary path derives from expression analysis but the fallback path does not derive from intrinsic symbol properties will be silently lost.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: Generated code signatures, serialized schemas, or API bindings treat array/matrix arguments as scalars when those arguments are declared but not referenced in the expression.
  - **Type errors**: Downstream consumers (compilers, runtimes, foreign function interfaces) reject the generated output because the argument type does not match the expected signature.
  - **Silent data corruption**: The system produces output that appears valid but carries incorrect type metadata, leading to runtime failures such as missing pointer indirection, wrong memory layout, or dimension mismatch.

### 解决步骤

1. **Audit all code paths that construct argument descriptors.** Trace the flow from declared argument list to final descriptor output. Identify the primary path (symbol found in expression) and every fallback/default path (symbol not found). Map which type metadata each path attaches.

2. **Extract intrinsic type-metadata derivation into a shared helper.** Create a function that derives dimensionality, shape, pointer semantics, and other type metadata directly from the symbol's intrinsic type properties (e.g., `.shape`, `.rank`, type annotations) — independent of expression-level analysis. This helper should be the single source of truth for "what type is this argument?"

3. **Refactor the primary path to use the shared helper.** Ensure the primary path delegates to the same helper for type metadata, supplementing with any expression-derived information only as an enrichment layer, not as the sole source.

4. **Refactor the fallback path to use the shared helper.** Replace the minimal/default descriptor construction with a call to the shared helper, so that declared-but-unused arguments receive the same type-aware treatment as expression-discovered arguments.

5. **Add targeted test cases.** Write tests that declare array, matrix, and other composite-type arguments that do **not** appear in the wrapped expression body. Verify that the generated output preserves their full type metadata (dimensions, shape, pointer semantics) identically to the case where they do appear.

### Why This Works

By extracting type-metadata derivation into a single shared helper that consults the symbol's intrinsic properties, the solution eliminates the structural asymmetry between the primary and fallback paths. Both paths now produce descriptors through the same logic, making it impossible for one to silently lose metadata that the other preserves. Future enhancements to type handling automatically propagate to both paths, preventing regressions.

## Boundary Cases

- **Zero-dimensional arrays or rank-0 tensors**: These may appear scalar-like but carry distinct type semantics (e.g., a 0-d NumPy array vs. a Python float). The shared helper must distinguish them from true scalars.
- **Arguments with symbolic or dynamic shapes**: When dimensions are not statically known, the fallback path must still preserve the symbolic shape expressions rather than collapsing to a scalar default.
- **Nested composite types**: Arguments that are containers of arrays (e.g., a list of matrices) require recursive type-metadata derivation; the fallback path must handle depth beyond a single level.
- **Arguments that appear in the declared list multiple times or under aliases**: Deduplication logic must not interfere with type-metadata attachment on the fallback path.
- **Empty expression body**: When the expression is trivial (e.g., returns a constant), *all* declared arguments hit the fallback path. This is the maximum-exposure case and must be explicitly tested.

## PR Examples

- **sympy__sympy-16792**: Code generation system (`autowrap`/`codegen`) lost array dimension metadata for `MatrixSymbol` arguments not referenced in the expression, because the fallback path constructed `InputArgument` descriptors without consulting the symbol's `.shape` attribute, defaulting to scalar treatment.