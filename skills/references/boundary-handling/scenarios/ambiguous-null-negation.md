## Problem Description

When a domain-specific predicate (e.g., "key exists in a nested structure") has an affirmative branch implemented with a dedicated function, but its negation branch falls back to a generic inverse operation (e.g., `IS NULL` on an extracted value), the system produces incorrect results whenever the underlying data representation **collapses two semantically distinct states into the same surface-level signal**. The canonical example: extracting a value from a JSON/map-like structure returns SQL `NULL` both when the key is entirely absent AND when the key is present but holds a typed null value. The affirmative "exists" check uses a purpose-built function that distinguishes these cases, but the negated path naively checks `IS NULL`, which conflates absence with presence-of-null — silently returning wrong results for the typed-null case.

This pattern is **backend-dependent**: some backends' extraction primitives preserve the distinction (e.g., returning type metadata like the string `'null'` for a JSON null vs. SQL `NULL` for absence), while others do not. The bug often goes undetected because tests only exercise non-null values, where the ambiguity never manifests.

## Root Cause Analysis

The root cause is a **symmetry-breaking assumption**: developers assume that if the affirmative case is handled with domain-specific logic, the negation can safely use the default/generic inverse path. This assumption fails when the generic path lacks the **discriminating power** of the domain-specific logic.

Specifically:
- A dedicated existence-check function encodes domain knowledge (e.g., probing key presence in a container via a specialized operator or function).
- The generic inverse (`extracted_value IS NULL`) operates on the *output* of a value-extraction function, which is a **lossy projection** — it maps two distinct semantic states (absent key vs. present key with null value) onto the same SQL `NULL`.
- The logical negation of "key exists" is "key does not exist," but `IS NULL` on the extracted value means "key does not exist OR key exists with null value." These are not equivalent.
- Because different backends implement extraction differently (some provide type-inspection functions, some provide dedicated existence operators, some conflate the two states), a single generic negation strategy cannot be correct across all backends.

## Solution Strategy

### 识别信号
- 观测到的现象: Wrong query results (wrong-output) specifically when data contains keys with typed null values; negation queries incorrectly match rows where the key exists but holds null. Regression manifests as an edge-case failure that only appears with specific data patterns and may differ across database backends.

### 解决步骤
1. **Audit all negation paths**: Identify every location where the negation of a domain-aware predicate falls back to a generic operation (e.g., raw `IS NULL` instead of `NOT domain_specific_exists(...)`). Map out the affirmative vs. negated code paths and flag asymmetries.

2. **Characterize backend extraction semantics**: For each supported backend, determine whether the extraction/access function conflates absence with typed null. Document what each backend returns for (a) absent key, (b) present key with null value, and (c) present key with non-null value.

3. **Implement backend-specific negation logic**:
   - If the backend provides a **type-inspection function** (e.g., `JSON_TYPE()` returns `'null'` for typed nulls vs. SQL `NULL` for absence), use `type_function(...) IS NULL` as the absence check in the negation path.
   - If the backend provides a **dedicated existence operator** (e.g., `?` in PostgreSQL for JSON key existence), negate it explicitly (`NOT container ? key`) and combine with a disjunct for the case where the entire container column is `NULL` (to handle rows with no container at all).
   - If the backend cannot distinguish the two states at all, document the limitation explicitly rather than silently returning wrong results.

4. **Add targeted test cases**: Create tests with data rows where keys are present but hold typed null values. Verify that:
   - The affirmative existence check matches these rows.
   - The negated existence check does **not** match these rows.
   - Rows where the key is truly absent are matched only by the negation.

5. **Cross-backend validation**: Run the full test suite across all supported backends, since the ambiguity is backend-dependent and a fix correct for one backend may be insufficient or unnecessary for another.

### Why This Works

The negation of a domain-specific predicate must be constructed with **equal domain awareness** as the affirmation. By replacing the generic fallback with backend-specific logic that leverages each backend's native primitives for distinguishing absence from typed null, the negation correctly mirrors the semantics of the affirmation. Keeping backend-specific implementations separate (rather than forcing a unified abstraction) is the correct approach because the underlying primitives genuinely differ — a forced abstraction would be leaky and fragile.

## Boundary Cases
- **Key present with typed null value**: The critical case — must NOT match the negated existence check, but MUST match the affirmative existence check.
- **Entire container column is NULL**: The negation path must account for rows where the container itself is `NULL` (not just the extracted key), typically requiring an `OR column IS NULL` disjunct alongside the negated existence check.
- **Nested key paths**: When checking existence of deeply nested keys (e.g., `container.a.b.c`), absence at any level of the path must be handled correctly — intermediate nulls vs. leaf-level typed nulls may behave differently.
- **Backend-specific extraction quirks**: Some backends may return empty strings, special sentinel values, or different `NULL` flavors; each must be tested independently.
- **Chained negations (double negation)**: `NOT NOT exists(key)` should be equivalent to `exists(key)` — verify that the domain-specific negation composes correctly.
- **Mixed queries combining existence with value predicates**: E.g., "key exists AND value > 5" negated as "key does not exist OR value <= 5" — the negation of the existence sub-predicate must still use domain-aware logic.

## PR Examples
- django__django-13757