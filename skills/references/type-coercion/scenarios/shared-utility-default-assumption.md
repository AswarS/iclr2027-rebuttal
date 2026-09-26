## Problem Description

When a shared input validation utility — designed primarily for numeric data — is adopted by a code path that handles categorical or symbolic data (e.g., string labels, object-typed arrays), the utility's default dtype coercion (typically to `float64`) silently destroys non-numeric inputs. This manifests as a crash ("could not convert string to float") or data corruption, and typically appears as a regression after the shared validation call is introduced or updated in a previously working categorical code path.

This is a **default-value substitution** problem: the utility's implicit contract assumes numeric inputs because the majority of its callers are numeric. When a minority caller with fundamentally different input semantics uses the utility without overriding the default, the mismatch between the utility's assumptions and the caller's actual data causes failure.

## Root Cause Analysis

The underlying principle is **majority-case anchoring in shared abstractions**. Shared validation utilities in numerical computing libraries are designed around the most common case — floating-point arrays. Their default parameters encode this assumption (e.g., `dtype="numeric"` or `dtype=np.float64`). This default is invisible at the call site, creating a cognitive trap:

1. **Implicit contract propagation**: The utility's numeric-only contract is not enforced at the API boundary but embedded in a default parameter value. Developers adding a new call site see a clean function signature and assume it is type-agnostic.
2. **Semantic mismatch**: Categorical identifiers (class labels, group names, string-typed features) are structurally similar to numeric arrays (both are array-like) but semantically incompatible with numeric coercion. The validation utility cannot distinguish structural validation (shape, nulls) from semantic type enforcement (must be float).
3. **Regression vector**: The code path previously worked because it either had no validation or used a different validation mechanism. Adopting the shared utility introduces an unintended type constraint that breaks existing functionality for non-numeric inputs.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ValueError: could not convert string to float` or similar coercion exceptions when passing string/object arrays to a function that previously accepted them.
  - Regression appearing after a refactor that introduced or standardized shared validation calls across multiple code paths.
  - Failures only on non-numeric inputs (string labels, mixed-type object arrays); numeric inputs continue to work correctly.

### 解决步骤
1. **Audit all call sites of the shared validation utility.** Classify each call site by whether its inputs are inherently numeric (feature matrices, distance arrays) or inherently categorical/symbolic (class labels, group identifiers, string-typed categorical features).
2. **Override the default dtype at categorical call sites.** For each categorical-input call site, explicitly pass a parameter that disables numeric coercion (e.g., `dtype=None`, `dtype="no-conversion"`, or the equivalent in the framework). This preserves the original dtype while still performing structural validation (shape, dimensionality, missing values).
3. **Verify downstream compatibility.** Confirm that downstream processing (label encoding, contingency table construction, set operations on labels) already handles arbitrary label types and does not implicitly depend on numeric input. If it does, fix the downstream logic as well.
4. **Add regression tests with non-numeric inputs.** For every categorical-input call site, add test cases using string arrays, object-typed arrays, and mixed-type labels to ensure the validation path does not impose numeric coercion. These tests serve as a permanent guardrail against future regressions.

### Why This Works

The minimal fix — disabling coercion rather than adding complex type-detection logic — works because the validation utility's purpose at these call sites is **structural**, not **semantic**. The utility should verify shape, dimensionality, and absence of invalid values, but it should not enforce a numeric type contract on data that is semantically non-numeric. Downstream logic (e.g., `LabelEncoder`, `contingency_matrix`) already has its own encoding step that handles arbitrary label types. By passing `dtype=None`, we decouple structural validation from type enforcement, respecting the separation of concerns between the validation layer and the domain logic layer.

## Boundary Cases
- **Object arrays containing numeric strings** (e.g., `["1", "2", "3"]`): These should remain as strings if the caller treats them as categorical labels, even though they could technically be coerced to floats. The caller's semantic intent, not the data's coercibility, should govern behavior.
- **Mixed-type object arrays** (e.g., `[1, "a", None]`): Disabling dtype coercion preserves these as object arrays, but downstream logic must handle `None`/`NaN` values explicitly since the validation utility's null-checking behavior may differ for object vs. numeric dtypes.
- **Callers that accept *both* numeric and categorical inputs** depending on context (e.g., a metric that works on both continuous predictions and discrete labels): These require conditional dtype handling, potentially inspecting the input's dtype before deciding whether to coerce.
- **Sparse matrix inputs**: Sparse formats may not support object dtypes; disabling coercion on sparse categorical inputs may require converting to dense first or using a different validation path entirely.

## PR Examples
- scikit-learn__scikit-learn-15535