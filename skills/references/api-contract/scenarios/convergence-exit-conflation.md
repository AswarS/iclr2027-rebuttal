## Problem Description

When an iterative algorithm has two semantically distinct termination modes — convergence (success) and iteration budget exhaustion (failure) — but both exit paths flow into a single shared post-processing block, the algorithm silently returns plausible-looking but meaningless results on failure. The intermediate state accumulated during iteration (partial assignments, tentative centroids, candidate solutions) superficially resembles a valid final result, so the caller receives output that appears correct but violates the documented API contract. There is no warning, no error, and no programmatic way to distinguish a converged result from a non-converged one without inspecting verbose logs or manually comparing iteration counts to the configured maximum.

This is a **convergence-exit conflation** pattern: the code treats "the loop ended" as a single event, when in reality there are two fundamentally different reasons the loop can end, each requiring different post-processing behavior.

## Root Cause Analysis

The root cause is an **implicit assumption that reaching the end of an iterative loop with accumulated state implies that state is valid**. Developers naturally focus on the happy path where convergence occurs and write the result-construction logic once, after the loop. When the loop terminates by exhausting its iteration budget, execution falls through to the same result-construction code — silently promoting incomplete, intermediate computational artifacts to the status of a final answer.

This conflation arises because:

1. **Partial progress is mistaken for approximate progress.** An incomplete computation in an iterative algorithm is not the same as an approximate solution. Partial assignments or tentative centroids from a non-converged run may be arbitrarily far from any meaningful result.
2. **Loop termination is treated as a single semantic event.** Languages like Python offer constructs (`for-else`) that distinguish "broke out early" from "exhausted the iterator," but developers often don't use them, collapsing two distinct outcomes into one code path.
3. **The API contract specifies distinct failure behavior** (e.g., returning empty results, sentinel labels like `-1`, or raising warnings), but the implementation never checks which termination mode occurred, so the contract is violated silently.
4. **Testing typically covers only the convergence case**, leaving the non-convergence path unexercised and its incorrect behavior undetected.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - The algorithm returns plausible-looking results (e.g., cluster labels, fitted parameters) even when it clearly should not have converged (e.g., `max_iter=1` on a complex problem).
  - No warning or error is emitted on non-convergence; the only evidence is buried in verbose log output or requires manual comparison of `n_iter_` to `max_iter`.
  - Downstream consumers (e.g., `predict()`, `transform()`) operate on the non-converged state without complaint, producing silently wrong outputs.
  - The documented API contract specifies failure return values (empty arrays, sentinel labels, specific exceptions) that are never actually produced by the implementation.

### 解决步骤

1. **Map all loop exit paths.** Trace every way the iterative loop can terminate: early break on convergence, natural exhaustion of the iteration counter, and any exceptional exits. Label each path as "converged" or "not converged."

2. **Introduce an explicit convergence flag.** Add a boolean (e.g., `converged = False`) initialized before the loop. Set it to `True` **only** on the successful-convergence break. Use language-idiomatic constructs (Python's `for-else`, post-loop index checks) to make the two-state nature visible in code structure.

3. **Branch post-processing on the convergence flag.** After the loop, check the flag. On the non-converged path: construct the documented failure return value (empty results, sentinel labels like `-1`), emit a `ConvergenceWarning`, and skip the success-path post-processing entirely. Do **not** fall through.

4. **Thread convergence status into the return structure.** Expose the convergence state as a programmatically inspectable attribute (e.g., `converged_`, `n_iter_` alongside `max_iter`) on any fitted object or return tuple, so callers can detect failure without heuristics.

5. **Guard downstream methods against non-converged state.** Add validation in methods like `predict()` or `transform()` that depend on valid fitted parameters. If the model is in a non-converged state, raise a clear error or warning rather than silently computing on garbage state.

6. **Test both termination modes explicitly.** Write at least two tests:
   - A test where the algorithm is given sufficient iterations and data that guarantees convergence, asserting valid results.
   - A test where `max_iter` is set artificially low (e.g., `max_iter=1`) to guarantee non-convergence, asserting that the documented failure values are returned, warnings are emitted, and the convergence flag is `False`.

### Why This Works

An explicit convergence flag makes the two-state nature of iterative termination **visible and enforceable** in the code. It transforms a silent, implicit assumption ("the loop ended, so we must have a result") into an explicit, testable condition. By branching post-processing on this flag, the implementation structurally mirrors the API contract: success and failure are handled by different code paths, making it impossible for intermediate artifacts to be silently promoted to final results. Threading the flag into the return structure gives callers a first-class mechanism to detect and handle non-convergence, converting a silent data-loss scenario into a well-defined, observable outcome.

## Boundary Cases

- **Convergence on the very last iteration.** The algorithm converges exactly when `i == max_iter - 1`. The flag must be set inside the convergence check, not inferred from the loop index, to correctly classify this as success rather than exhaustion.
- **Multiple restarts or inner loops.** Algorithms with random restarts (e.g., k-means with `n_init > 1`) may converge on some restarts but not others. The convergence flag must be tracked per-restart, and the overall result should reflect whether the *best* restart converged.
- **Warm-start or incremental fitting.** If the algorithm supports warm-starting from a previous fit, a non-converged prior state fed into a new fit must not be treated as a valid initialization without explicit acknowledgment.
- **`max_iter=0` or `max_iter=None`.** Edge cases in configuration should be validated upfront. A `max_iter` of zero should either raise an error or return the documented failure value immediately, not enter the loop.
- **Convergence tolerance set to zero.** With `tol=0`, exact convergence may be unreachable due to floating-point arithmetic. The algorithm should still respect `max_iter` and correctly flag non-convergence rather than looping indefinitely or returning partial results.
- **Parallel or distributed execution.** When iterations are distributed across workers, the convergence flag must be synchronized correctly; a race condition in flag-setting could cause one worker's non-convergence to be masked by another's success.

## PR Examples

- **scikit-learn__scikit-learn-15512**: An iterative algorithm returned plausible-looking but invalid results when it failed to converge, with no warning or programmatic indicator, because the convergence and non-convergence exit paths shared a single result-construction block. The fix introduced an explicit convergence flag, branched post-processing on it, and ensured the documented failure return values were actually produced.