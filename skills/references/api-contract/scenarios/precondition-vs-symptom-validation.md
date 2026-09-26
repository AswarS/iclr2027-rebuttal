## Problem Description

When an algorithm or solver is designed to handle a specific class of well-posed problems (e.g., fully-determined systems with finite solutions), it may rely on **downstream symptom-based checks** (e.g., "did we find a univariate polynomial?") rather than **upstream precondition validation** (e.g., "does this system have enough independent constraints for the number of unknowns?"). This creates an asymmetric bug: some invalid inputs are caught because they happen to fail the downstream check, while structurally equivalent invalid inputs slip through because their intermediate computation coincidentally produces a result that matches the expected pattern. The algorithm then returns partial or incorrect results instead of raising an error.

This pattern is especially insidious because it gives the illusion of correctness — the algorithm "works" on some permutations of an ill-posed problem while silently producing wrong answers on others, making the bug difficult to detect through casual testing.

## Root Cause Analysis

The fundamental issue is **affirming the consequent**: the algorithm assumes that if its internal computation succeeds in producing a recognizable intermediate structure, then the input must have been valid. In reality, the algorithm's internal success is a *necessary but not sufficient* condition for input validity.

For example, a Gröbner basis computation on an underdetermined system may still produce a univariate polynomial in one of the variables — not because the system is fully determined, but because the constraints happen to constrain that particular variable while leaving others free. A downstream check that looks for "exactly one univariate polynomial" will pass for that variable, and the solver will return an incomplete or misleading result. Meanwhile, a different permutation of the same underdetermined system might fail the same downstream check, correctly (but accidentally) triggering an error.

The root cause is the conflation of two fundamentally different assertions:
1. **"The algorithm found something it can process"** (a symptom-level observation)
2. **"The problem is well-posed for this algorithm"** (a precondition-level invariant)

By validating only symptoms rather than preconditions, the code creates a fragile correctness boundary that depends on the accident of which intermediate pattern the computation produces, rather than on the structural properties of the input.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: The algorithm returns partial, incomplete, or incorrect results for inputs that violate its stated preconditions, without any error or warning.
  - **Missing validation**: No explicit check exists for the algorithm's mathematical preconditions (e.g., constraint count vs. variable count); correctness depends entirely on downstream pattern matching.
  - **Asymmetric behavior**: One permutation of an invalid input raises an error while a structurally equivalent permutation silently returns a wrong answer. For example, `solve([x + y], [x, y])` might return `{x: -y}` (partial solution treated as complete) while a reordered variant fails.

### 解决步骤
1. **Identify the mathematical precondition** the algorithm requires. Determine the structural invariant that distinguishes well-posed inputs from ill-posed ones (e.g., the number of independent constraints must equal or exceed the number of unknowns for a finite-solution solver).
2. **Locate the earliest feasible validation point** — after the necessary intermediate data is available (e.g., after basis reduction or decomposition) but *before* any branching logic that attempts to extract or interpret solutions.
3. **Implement an explicit precondition check** that compares structural properties of the intermediate result against the problem dimensions. For instance, verify that the number of independent elements in a reduced basis is at least as large as the number of variables.
4. **Raise an appropriate error or return a well-defined sentinel** when the precondition is violated, rather than allowing the algorithm to proceed into solution-extraction logic that may produce misleading results.
5. **Test symmetrically across all permutations** of the invalid input. If the algorithm rejects one arrangement of an underdetermined system, verify it also rejects all other arrangements (e.g., constraints on variable X vs. variable Y when both are declared unknowns).

### Why This Works

Precondition checks based on structural invariants validate the **problem's well-posedness directly**, independent of which specific pattern the intermediate computation happens to produce. This decouples correctness from the accident of intermediate representation. By checking "is this problem solvable by this algorithm?" rather than "did this algorithm happen to produce something that looks like an answer?", the validation becomes robust, symmetric, and principled. It eliminates the entire class of bugs where coincidental pattern matches in intermediate results mask invalid inputs.

## Boundary Cases
- **Inputs that are exactly at the boundary** of well-posedness (e.g., number of constraints equals number of unknowns but some constraints are redundant/dependent) — the precondition check must account for *independent* constraints, not just raw count.
- **Inputs where the intermediate computation produces a valid-looking result for a subset of variables** — the check must verify coverage of *all* declared unknowns, not just the presence of any univariate result.
- **Parameterized or symbolic inputs** where the well-posedness may depend on parameter values — the check should either handle the symbolic case conservatively or clearly document its limitations.
- **Mixed systems** where some variables are implicitly treated as parameters — the algorithm must be clear about which symbols are unknowns vs. parameters, and the precondition check must respect this distinction.

## PR Examples
- sympy__sympy-22005