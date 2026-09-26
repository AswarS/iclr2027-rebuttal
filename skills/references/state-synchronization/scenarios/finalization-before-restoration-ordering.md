## Problem Description

This pattern occurs in optimization or fitting routines that employ a **multi-initialization (multi-restart) strategy** to avoid local optima. The routine runs N independent initializations, tracks the best result by some criterion (e.g., highest log-likelihood, lowest loss), and then performs a finalization step (e.g., a final E-step, label assignment, or post-processing computation) that depends on the model's internal parameters. The bug arises when the finalization step executes **before** the best parameters are restored to the model's mutable state, causing it to silently use the parameters from the **last** initialization attempted rather than the **best** one. This produces incorrect outputs from combined fit-and-return methods (e.g., `fit_predict`, `fit_transform`) that disagree with calling `fit` followed by a separate inference call.

## Root Cause Analysis

In any select-best-from-N pattern, the model's mutable internal state at loop exit reflects the **last** iteration, not necessarily the **best** one. These are only identical when N=1 (the default), which is the configuration most commonly tested during development. This creates a **single-iteration reasoning trap**: the developer verifies correctness for the default case where last-tried ≡ best, and never re-evaluates the ordering assumption for N>1.

The underlying principle is an **ordering dependency**: derived computations must follow the establishment of their prerequisites. When a finalization step (computing labels, responsibilities, scores, etc.) depends on model parameters, it must execute *after* the best parameters have been restored to the model's state. Violating this invariant is a form of **state desynchronization** — the model's parameters and its derived outputs become inconsistent.

This class of bug is particularly insidious because:
- It produces no errors or exceptions — only silently wrong results.
- It is non-deterministic in appearance: depending on random seeds, the last initialization may or may not coincide with the best, making failures intermittent.
- Default-configuration tests (N=1) always pass, providing false confidence.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `fit_predict` / `fit_transform` returns different results than `fit` followed by `predict` / `transform`.
  - Results are correct when `n_init=1` but incorrect or inconsistent when `n_init>1`.
  - Outputs appear non-deterministic even with a fixed random seed, because they depend on which initialization happened to run last.
  - Model attributes (e.g., cluster centers, mixture weights) are consistent with the best run, but returned labels/responsibilities are not.

### 解决步骤
1. **Locate the multi-initialization loop**: Find the loop that iterates over N restarts, tracking the best parameters and best score separately from the model's live mutable state.
2. **Trace post-loop operations**: Map the exact sequence of operations after the loop exits. Identify (a) where best parameters are restored to the model's state, and (b) where any finalization computation (final inference pass, label assignment, score computation) occurs.
3. **Verify ordering**: Check that every finalization step that reads model parameters is sequenced **after** the best-state restoration. If any finalization precedes restoration, this is the bug.
4. **Reorder**: Move the finalization step to after the best-parameter restoration, or equivalently, move the restoration to before the finalization step. Ensure no other state-dependent computation is left stranded before restoration.
5. **Add a regression test**: Write a test with `n_init > 1` (e.g., `n_init=5`) that asserts the combined method (`fit_predict`) produces identical results to the two-step call (`fit` then `predict`). Use a fixed random seed for reproducibility.
6. **Verify**: Confirm the test fails on the unfixed code and passes after the fix.

### Why This Works

The fix enforces the invariant that **derived computations follow the establishment of their prerequisites**. By ensuring the best parameters are restored before any finalization step reads them, the model's state and its derived outputs become consistent. The regression test with N>1 breaks the single-iteration masking effect, ensuring the ordering dependency is validated for the general case.

## Boundary Cases

- **N=1 (single initialization)**: The bug is invisible because last-tried ≡ best. Tests must use N>1 to detect this pattern.
- **Best initialization happens to be the last one**: The bug is masked by coincidence. Tests should use seeds or configurations where the best initialization is NOT the last one.
- **Finalization has side effects on state**: If the finalization step itself modifies model state (e.g., caching intermediate results), reordering may require ensuring those cached values are also consistent with the best parameters.
- **Multiple finalization steps**: Some routines have several post-loop computations (e.g., compute labels, compute scores, set convergence flags). ALL of them must be audited for dependency on model parameters and placed after restoration.
- **Early termination / convergence shortcuts**: If the loop can exit early (e.g., on convergence), verify that the restoration-before-finalization ordering holds on all exit paths, not just the normal loop completion path.

## PR Examples

- **scikit-learn__scikit-learn-13142**: GaussianMixture's `fit_predict` performed a final E-step (to compute responsibilities/labels) before restoring the best parameters from the multi-initialization loop, causing `fit_predict` to disagree with `fit().predict()` when `n_init > 1`.