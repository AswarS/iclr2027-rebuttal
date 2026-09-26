## Problem Description

When a method contains two or more code paths that perform similar logic (e.g., a primary execution path and a secondary/fallback path), the secondary path often fails to maintain parity with the primary path's parameter resolution and conditional guards. Specifically, the primary path resolves a raw configuration parameter (such as `'auto'`) into a concrete, normalized value and uses that resolved value for all subsequent branching and indexing. The secondary path, typically written later as a simplified copy, inadvertently references the original raw parameter instead of the resolved local variable, and omits conditional guards that the primary path enforces. This symmetry-breaking causes crashes (index errors, key errors) or incorrect behavior when the secondary path is exercised with default or auto-resolved configuration values.

## Root Cause Analysis

The fundamental issue is **implicit assumption violation through symmetry-breaking between peer code paths**.

When a parameter undergoes normalization early in a method (e.g., `penalty = 'auto'` is resolved to `penalty_resolved = 'l2'`), all downstream logic must operate on the normalized form. The primary code path, being the first written and most tested, correctly uses the resolved variable. However, when a secondary path is added — often for edge cases, warm-start scenarios, or fallback logic — developers treat it as a "simplified copy" rather than a full peer. They mentally test it only under the narrow conditions they expect it to be reached, not realizing it can be triggered with the full range of input configurations.

This creates two distinct failures:
1. **Raw vs. resolved variable mismatch**: The secondary path uses the raw parameter for branching or dictionary/array indexing, encountering values (like `'auto'`) that don't correspond to valid keys or branches.
2. **Missing conditional guards**: The primary path wraps certain computations in guards (e.g., "only compute this derived value when penalty is `'l1_ratio'`"), which control the shape of intermediate data structures. The secondary path omits these guards, performing index arithmetic on structures that don't have the expected number of elements, leading to out-of-bounds errors or silent data corruption.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `IndexError`, `KeyError`, or unexpected branch execution occurring in a secondary/fallback code path
  - Crash only manifests when using default or `'auto'` configuration values — explicitly set values work fine
  - The traceback points to a code block that looks structurally similar to another block in the same method but references a raw parameter instead of a resolved local variable
  - Regression on edge cases: the secondary path worked before a refactor that introduced parameter normalization in the primary path

### 解决步骤
1. **Locate all normalization points**: Identify where raw configuration parameters are resolved into concrete local variables (e.g., `solver_ = 'lbfgs' if solver == 'auto' else solver`). Map each raw parameter to its resolved counterpart.
2. **Audit all downstream references**: Search the entire method for every reference to the raw parameter name. For each occurrence, determine whether the code semantically requires the raw value or the resolved value. In branching, indexing, and computation logic, the resolved value is almost always correct.
3. **Replace raw references in secondary paths**: Substitute the resolved local variable for the raw parameter in all secondary code paths where the resolved form is expected.
4. **Diff conditional guards between paths**: Systematically compare every conditional guard in the primary path against the secondary path. For each guard present in the primary path but absent in the secondary, determine whether the guarded computation is also performed in the secondary path.
5. **Add missing guards with safe defaults**: Where the secondary path lacks a guard, add the equivalent conditional. For cases excluded by the guard, provide a safe default value (e.g., appending `None` to a results list) to maintain consistent data structure shapes.
6. **Add targeted test coverage**: Write tests that exercise the secondary code path specifically with default/auto configuration values, as this is the combination most likely to have been missed during development.

### Why This Works

The solution restores **full parity** between all code paths in the method. By ensuring every path uses the normalized parameter form and enforces the same conditional guards, the method behaves consistently regardless of which path is taken. The principle is that secondary code paths are not simplified subsets — they are full peers that must handle the complete valid input space. Normalizing early and referencing the normalized form everywhere eliminates the class of bugs where raw sentinel values (like `'auto'`) leak into logic that expects concrete resolved values.

## Boundary Cases
- **Parameter normalization that is conditional itself**: The resolution of `'auto'` may depend on other parameters or data properties. Ensure the secondary path has access to the same context needed for resolution, or that resolution happens before any branching.
- **Multiple levels of normalization**: A parameter may be resolved in stages (e.g., `'auto'` → `'ovr'` → specific solver). All intermediate and final forms must be tracked and used consistently.
- **Secondary path reached with partially initialized state**: In warm-start or incremental-fit scenarios, the secondary path may execute with state from a previous run where the parameter was resolved differently. Ensure re-resolution occurs or the stored resolved value is used.
- **Guard omission that causes silent corruption rather than a crash**: If the missing guard doesn't cause an index error but instead silently includes an extra or wrong value in a result list, the bug manifests as incorrect output rather than an exception — harder to detect without explicit test assertions on output shape and values.

## PR Examples
- scikit-learn__scikit-learn-14087