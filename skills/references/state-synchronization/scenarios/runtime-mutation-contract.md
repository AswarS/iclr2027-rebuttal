## Problem Description

When a system's public API permits metadata (markers, annotations, attributes) to be added to objects dynamically during execution, but an internal refactoring or optimization moves the evaluation of that metadata to an earlier lifecycle phase (e.g., setup or initialization), dynamically added metadata is silently ignored. This creates a **runtime mutation contract violation**: the API promises that mutation is valid at any point during execution, but the evaluation pipeline only honors mutations that exist before execution begins. The result is a regression where previously working dynamic-metadata patterns break without any explicit error, producing inconsistent internal state that downstream phases cannot correctly interpret.

This pattern is particularly insidious because it manifests as a silent behavioral change — the system doesn't raise an error; it simply stops recognizing metadata that was added at runtime. The failure is invisible until a user or test relies on the dynamic mutation path and observes that the expected side-effect (e.g., marking a test as expected failure, applying a skip, triggering a hook) no longer occurs.

## Root Cause Analysis

The root cause is the **static-completeness assumption**: a developer optimizing or refactoring the evaluation pipeline assumes that all relevant metadata will be present before execution begins, treating evaluation as a one-time pre-computation. This assumption is valid for the common case (statically declared metadata) but violates the contract for the dynamic case that the API explicitly supports.

This is a specific instance of **implicit assumption violation** combined with **state desynchronization**:

1. **Implicit assumption violation**: The refactoring encodes an unstated assumption (metadata is static) that contradicts the public API contract (metadata can be added at runtime). No assertion or check enforces this assumption, so the violation is silent.

2. **State desynchronization**: After the optimization, the internal evaluated state (computed once at setup) diverges from the actual metadata state (which may have been mutated during execution). Downstream phases that rely on the evaluated state now operate on stale information.

3. **Conflation of "not evaluated" with "no result"**: When evaluation is skipped or gated behind a configuration flag, the absence of a result is indistinguishable from a genuine negative result. Later phases cannot tell whether they should re-evaluate or trust the existing (absent) state.

The cognitive trap is that the optimization appears correct in testing because the majority of usage is static. The dynamic mutation path is an edge case that may not be covered by the refactoring author's test suite, causing the regression to slip through.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Inconsistent state**: Metadata added during execution is present on the object but has no behavioral effect, as if the system never saw it.
  - **Regression on edge case**: Behavior that worked in a prior version (dynamic metadata addition during execution) silently stops working after a refactoring or optimization.
  - **Configuration-dependent state loss**: A configuration flag that controls a behavioral side-effect inadvertently suppresses the evaluation/storage of metadata, causing downstream phases to lose information they depend on.
  - **No error raised**: The system does not signal any failure; it simply ignores the dynamically added metadata.

### 解决步骤

1. **Map the mutation window against the evaluation window.** Enumerate all lifecycle phases where the API permits metadata to be added (declaration, setup, execution, teardown) and all phases where metadata is evaluated. If the mutation window extends beyond the evaluation window, there is a contract gap that must be closed.

2. **Introduce post-execution re-evaluation.** After the main execution phase completes (or yields), re-check whether new metadata was added during execution. Compare the current metadata state against what was captured during pre-execution evaluation. Process any additions that were not previously seen. This ensures the evaluation pipeline honors the full mutation window.

3. **Separate evaluation/storage from behavioral side-effects.** Always evaluate and record metadata into internal state, regardless of configuration flags that control whether the system acts on that metadata. This creates a two-phase model: (a) evaluate and store, (b) conditionally act. Configuration flags should gate only phase (b), never phase (a).

4. **Use sentinel values to distinguish "not yet evaluated" from "evaluated with no result."** Initialize the internal evaluation state to a sentinel (e.g., `None` or a dedicated `NOT_EVALUATED` marker) rather than a default that could be confused with a legitimate negative result (e.g., `False`, empty collection). Post-execution logic can then check the sentinel to determine whether re-evaluation is needed.

5. **Add regression tests for the dynamic mutation path.** Create explicit test cases that add metadata during execution and verify that the system recognizes and acts on it. These tests serve as a contract enforcement mechanism, preventing future optimizations from silently breaking the dynamic path.

### Why This Works

The solution restores alignment between the API contract and the evaluation pipeline by ensuring that evaluation is not a one-shot pre-computation but a process that respects the full lifecycle window during which mutations are permitted. By separating evaluation from action, the system maintains accurate internal state that downstream phases can trust, regardless of configuration. Sentinel values eliminate ambiguity in multi-phase pipelines, allowing each phase to make informed decisions about whether prior phases have run. Together, these principles create a robust pipeline that honors the runtime mutation contract without sacrificing the performance benefits of early evaluation for the common (static) case — the early evaluation still runs and handles the majority of cases efficiently, while the post-execution check handles the dynamic edge case.

## Boundary Cases

- **Metadata added during teardown**: If the API contract extends to teardown, the re-evaluation step must also run after teardown, not just after execution. The evaluation window must be mapped precisely to the full mutation window.
- **Configuration flags that suppress evaluation entirely**: If a flag is intended to disable a feature, it may seem logical to skip evaluation. But if other features or downstream phases depend on the evaluated state (not the behavioral effect), suppressing evaluation breaks those consumers. Always evaluate; only gate the action.
- **Multiple metadata additions across phases**: If metadata is added in both setup and execution, the post-execution re-evaluation must handle incremental additions without duplicating processing of metadata that was already evaluated pre-execution.
- **Metadata removal during execution**: If the API also permits removal of metadata at runtime, the re-evaluation step must detect removals as well as additions, and downstream phases must handle the case where previously-evaluated metadata is no longer present.
- **Concurrent or nested execution contexts**: In systems with parallel test execution or nested execution scopes, dynamically added metadata in one context must not leak into or be evaluated by another context. The re-evaluation step must be scoped correctly.
- **Sentinel value collision**: The chosen sentinel must be a value that cannot be produced by legitimate evaluation. Using `None` is safe only if `None` is never a valid evaluation result; otherwise, a dedicated sentinel object (e.g., `_UNSET = object()`) should be used.

## PR Examples

- **pytest-dev__pytest-7490**: A refactoring moved the evaluation of `xfail` markers to the setup phase only, assuming all markers would be statically present. This broke the documented pattern of dynamically adding `xfail` markers during test execution (e.g., `request.node.add_marker(pytest.mark.xfail(...))`). The fix introduced post-execution re-evaluation of the `xfail` marker state, separated evaluation from the `--runxfail` configuration flag (always evaluate, conditionally act), and used a sentinel to distinguish "not evaluated" from "no xfail marker found."