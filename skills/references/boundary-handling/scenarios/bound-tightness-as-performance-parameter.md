## Problem Description

When algorithms use mathematical bounds to constrain search spaces, loop limits, modular arithmetic ranges, or data structure sizes, the tightness of those bounds directly determines runtime performance — not just correctness. A common pattern emerges where an initial implementation selects a mathematically valid but loose bound (chosen for simplicity or historical convention), and this looseness becomes an invisible performance bottleneck. The algorithm produces correct results, but as input size grows, the overly generous bound causes exponential or polynomial blowup in downstream computation. Because the bound is technically valid, the performance degradation is never attributed to it, and the code is treated as "correct but slow" rather than "correct but poorly parameterized."

## Root Cause Analysis

The fundamental cognitive trap is treating mathematical bounds as binary properties — either valid or invalid — rather than recognizing them as **continuous performance parameters** on a spectrum from tight to loose. During initial implementation, developers naturally select the simplest sufficient bound from the literature or from first principles. This bound satisfies the correctness invariant and passes all tests. However, the downstream impact of bound looseness is rarely profiled or quantified. Over time, as the algorithm is applied to larger or more diverse inputs, the gap between the loose bound and the actual values encountered grows dramatically (often by orders of magnitude), and this gap multiplies through every computation that depends on the bound. The root cause is **complexity-escalation blindness** — the failure to recognize that a constant factor buried in a bound formula is actually the dominant term in the algorithm's practical complexity — combined with **implicit assumption violation** — the assumption that any valid bound is "good enough" for performance purposes.

## Solution Strategy

### 识别信号
- 观测到的现象: Algorithm produces correct results but is orders of magnitude slower than expected, especially on larger inputs
- 观测到的现象: The computed bound value is dramatically larger (e.g., 100x–10000x) than the actual values encountered during execution
- 观测到的现象: Performance degrades super-linearly with input size in a way not explained by the algorithm's theoretical complexity class
- 观测到的现象: Profiling reveals that the majority of time is spent in loops or search spaces whose size is governed by a single bound parameter

### 解决步骤
1. **Trace the bound's downstream propagation**: Identify exactly how the bound value flows into the algorithm — does it set a loop iteration count, define a modulus for arithmetic, constrain a combinatorial search, or size a data structure? Quantify the relationship between bound magnitude and runtime (linear, quadratic, exponential).
2. **Survey tighter alternatives from the literature**: For well-studied mathematical problems, multiple bounds of varying tightness typically exist. Compare candidates (e.g., Mignotte bound vs. Knuth-Cohen bound) empirically across representative inputs that vary in size, density, coefficient magnitude, and structure — not just on worst-case or toy examples.
3. **Implement the tighter bound**: Replace the loose formula with the tighter variant, ensuring it uses the correct norms, coefficients, or combinatorial quantities required by the refined bound. Verify the formula against its original source.
4. **Add a safety margin for degenerate cases**: When a tighter bound risks being too tight for edge cases (e.g., irreducible inputs where the output equals the input, or trivial single-element cases), add a corrective term — such as the maximum absolute value of the input's components — to guarantee the bound remains valid under all conditions.
5. **Validate correctness across the full input spectrum**: Test with inputs where the bound should be near-tight (worst-case constructions), inputs where the old bound was wildly loose (typical real-world cases), and degenerate inputs (trivial, irreducible, or minimal cases) to confirm the new bound never underestimates.
6. **Scope the change narrowly**: If the bound appears in both simple and complex variants of the algorithm (e.g., univariate vs. multivariate polynomial factoring), apply the improvement to the well-understood case first and defer the more complex generalization to a separate change.

### Why This Works
Mathematical bounds are not merely correctness guards — they are **performance multipliers**. Every unit of looseness in a bound translates directly into wasted computation in every downstream step that depends on it. Replacing a loose bound with a tighter one from the same mathematical domain preserves the correctness invariant while eliminating the dominant source of unnecessary work. The safety margin ensures the tighter bound still satisfies its contract in degenerate cases where the estimated quantity equals or approaches the bound itself. Scoping the change narrowly reduces risk and enables empirical validation before broader application.

## Boundary Cases
- **Degenerate/trivial inputs**: Cases where the output equals the input (e.g., irreducible polynomials in factoring), meaning the bound must be at least as large as the input's own coefficients — a corrective term is needed to prevent underestimation
- **Inputs with extreme coefficient ranges**: Very large or very small coefficients can expose differences between bounds that appear equivalent on moderate inputs
- **Minimal-size inputs**: Single-element or degree-zero inputs where combinatorial terms in the bound formula may degenerate to zero or negative values
- **Near-worst-case inputs**: Inputs specifically constructed to make the bound tight, verifying the tighter bound does not underestimate
- **Multivariate or higher-dimensional generalizations**: The tighter bound proven for the simple case may not directly generalize; these should be deferred and handled separately

## PR Examples
- sympy__sympy-19254: Replaced a loose Mignotte bound with a tighter Knuth-Cohen bound in polynomial factoring, adding a corrective max-coefficient term for edge cases, yielding orders-of-magnitude speedup on larger inputs while preserving correctness.