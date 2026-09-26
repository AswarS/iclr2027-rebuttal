## Problem Description

A data processing pipeline exposes a permissive public API that accepts user-supplied data containing missing values (None, NaN, null), but internally delegates to a downstream numerical routine (e.g., linear algebra solver, regression fitter, matrix decomposition) that has a strict input contract requiring all-valid, complete numeric arrays. No intermediate sanitization layer bridges this contract gap, causing the strict routine to crash or produce garbage results when missing data flows through unchecked.

This is a specific instance of **input-contract mismatch**: two adjacent layers in a software stack disagree on what constitutes valid input, and neither layer explicitly reconciles the difference. The outer layer is designed for user-friendliness and tolerates messy real-world data; the inner layer is designed for mathematical correctness and assumes clean inputs. The missing reconciliation manifests as a hard crash deep in a numerical library — far from where the user could reasonably diagnose or fix the issue.

## Root Cause Analysis

The underlying principle is **implicit assumption of clean data at internal boundaries**. In layered architectures, each layer tends to assume that some other layer — either upstream or downstream — is responsible for data validity. Developers of the public API assume users will provide complete data, or that the computation layer handles missing values gracefully. Developers of the computation layer assume the calling code has already sanitized inputs. When neither assumption holds, the strict downstream routine receives invalid data and fails.

This is especially insidious because:
- The failure signal (e.g., `LinAlgError`, `ValueError` about NaN/Inf) originates deep inside a third-party numerical library, far from the actual root cause (missing sanitization at a layer boundary).
- The problem only manifests when users provide data with gaps in *specific* columns that feed into the numerical routine — it may pass all tests that use complete synthetic data.
- Layered abstractions (grouping, iteration, aggregation) can obscure the data flow path, making it non-obvious where sanitization should be inserted.

## Solution Strategy

### 识别信号
- 观测到的现象: A crash or exception originating from a numerical library (e.g., `numpy.linalg.LinAlgError`, `ValueError` referencing NaN or Inf) when the user provides a dataset containing missing values. The traceback points to an internal computation routine, not to the user-facing API entry point.

### 解决步骤
1. **Trace the contract mismatch**: Follow the traceback from the crash site back to the public API entry point. Identify the exact boundary where data transitions from the permissive layer (user-facing) to the strict layer (numerical computation). Note which stage *should* be responsible for ensuring data validity.

2. **Determine the minimal dependent column set**: Identify exactly which columns or fields the numerical routine depends on for its computation. Do *not* include unrelated columns — filtering on columns irrelevant to the computation would unnecessarily discard valid observations and silently change results.

3. **Insert targeted missing-data removal at the boundary**: Add a sanitization step (e.g., drop rows with NaN in the relevant columns only) at the outermost call site of the computation, *before* any grouping or iteration logic. This ensures that:
   - Grouping and aggregation logic also operates on clean data.
   - The core computation function remains focused on its mathematical responsibility.
   - The sanitization is visible and centralized rather than scattered across per-group worker functions.

4. **Preserve the public API contract**: The sanitization should be silent and automatic — the user-facing API's contract is that it tolerates missing data. Do not raise an error or require the user to pre-clean their data.

5. **Add regression tests**: Create test cases that exercise the full pipeline with missing values in the relevant input columns, verifying that the pipeline completes without error and produces correct results on the non-missing subset.

### Why This Works

This follows two complementary principles:

- **Validate early, compute cleanly**: By placing sanitization at the outermost boundary of the computation (not deep inside a per-group function), data preparation concerns are cleanly separated from algorithmic concerns. Each layer can be reasoned about and tested independently. The numerical routine never sees invalid data; the sanitization layer never worries about mathematics.

- **Minimal data loss**: By restricting the filter to only the columns the computation actually depends on, we preserve the maximum number of valid observations. Filtering on unrelated columns would silently discard data points that are perfectly valid for the computation at hand, potentially changing results in unexpected and hard-to-debug ways.

## Boundary Cases
- **All rows contain missing values in relevant columns**: The sanitization should produce an empty dataset, and the computation should either gracefully return an empty/null result or raise a clear, user-facing error — not a cryptic numerical library crash.
- **Missing values exist only in columns irrelevant to the computation**: No rows should be dropped; the computation should proceed on the full dataset.
- **Grouped/faceted computations where some groups are entirely missing**: After sanitization, some groups may become empty. The pipeline must handle empty groups gracefully (skip them or produce null results) rather than passing empty arrays to the numerical routine.
- **Mixed-type columns where missing values are represented inconsistently** (e.g., `None` vs `np.nan` vs `pd.NA`): The sanitization step must handle all representations of missingness that the input layer permits.
- **Chained computations where an intermediate result introduces NaN** (e.g., division by zero): The sanitization must occur after all data transformations that could introduce new missing values, or each computation boundary must independently validate its inputs.

## PR Examples
- mwaskom__seaborn-3010