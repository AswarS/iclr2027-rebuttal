## Problem Description

When a function or operator dispatches on special/sentinel values of its parameters independently (e.g., separate `if` branches for "parameter A is zero" and "parameter B is infinity"), the **cross-product combination** of two or more simultaneously special inputs creates an emergent edge case that falls between the cracks of all individual handlers. The first matching single-parameter handler silently consumes the input and returns a plausible but **incorrect** result — the bug manifests as wrong output, not a crash, making it particularly insidious.

This pattern is common in mathematical libraries, data transformation pipelines, and validation logic where multiple inputs each have well-defined boundary values (zero, infinity, null, empty, identity elements, sentinel constants) and the correct result for their intersection is qualitatively different from what any single-parameter handler would produce.

## Root Cause Analysis

The underlying principle is the **compositional correctness assumption**: developers reason about special-case handling one parameter at a time and implicitly assume that if handler A correctly manages "X is special" and handler B correctly manages "Y is special," then one of them will naturally produce the correct result when **both** X and Y are special simultaneously. This assumption is false whenever the interaction of two special values demands a distinct result that neither individual handler is designed to yield.

The structural cause is **specificity inversion in dispatch ordering** — general single-parameter handlers are placed before (or without awareness of) the more specific multi-parameter intersection cases. Because the first matching branch short-circuits evaluation, the more specific case never gets a chance to execute. The result looks valid (it's a value the function could plausibly return), so no error is raised and the bug propagates silently.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output on edge cases** — the function returns a value that is plausible but mathematically or logically incorrect for a specific combination of boundary inputs.
  - **Regression on edge cases** — a previously correct result becomes wrong after refactoring or extending the dispatch cascade, because a new general handler now matches before the specific case.
  - **No crash or exception** — the bug is silent; only specification-level or property-based testing reveals the discrepancy.
  - **Individual special-case tests pass** — tests for "A is special, B is normal" and "A is normal, B is special" all succeed; only the intersection fails.

### 解决步骤

1. **Inventory all special/sentinel values per parameter.** For each parameter of the function, enumerate every value that receives (or should receive) special treatment: zero, infinity, negative infinity, null/None, empty collections, identity elements, NaN, boundary constants, etc.

2. **Form the full Cartesian product.** Construct the matrix of all combinations of special values across all parameters. For a function with parameters (X, Y) where X has special values {0, ∞} and Y has special values {0, ∞}, the matrix has 4 cells: (0,0), (0,∞), (∞,0), (∞,∞).

3. **Determine the correct result for every cell.** Consult the specification, mathematical definition, or domain invariant for each combination independently. Do not derive the expected result by mentally running the existing code — derive it from first principles.

4. **Audit the existing dispatch cascade.** For each cell in the matrix, trace which branch of the current code would match first. Identify cells where the matching branch produces a result that differs from the specification-derived expectation.

5. **Add explicit early-return checks for cross-product edge cases.** Insert these checks **at the top** of the dispatch cascade, before any single-parameter general handler that could match and short-circuit. Use the same comparison idiom (identity `is` vs. equality `==`) as surrounding code for consistency.

6. **Order checks from most specific to most general.** Multi-parameter intersection cases must precede single-parameter handlers. Within intersection cases, order by the number of constrained parameters (most constrained first).

7. **Add test cases for every cell in the cross-product matrix.** Especially target combinations where two special values interact, as these are the cases most likely to have been missed.

### Why This Works

The principle of **specificity precedence** dictates that concrete, narrow cases must be resolved before abstract, broad patterns get a chance to match. By explicitly enumerating the cross-product of special values and placing their handlers first, we eliminate the gap between independently correct single-parameter handlers. This converts an implicit, fragile reliance on handler ordering into an explicit, auditable decision for every edge-case combination. The Cartesian product enumeration is exhaustive by construction, ensuring no intersection case is overlooked.

## Boundary Cases

- **Two parameters are both zero** — e.g., `Power(0, 0)` where the "base is zero" handler and the "exponent is zero" handler each assume the other parameter is non-special.
- **One parameter is zero and another is infinity** — e.g., `0 * ∞` where the "multiply by zero" handler returns 0 and the "multiply by infinity" handler returns infinity, but the correct result is indeterminate.
- **Both parameters are infinity with conflicting signs** — e.g., `∞ + (-∞)` where individual infinity handlers assume the other operand is finite.
- **A sentinel/identity value combined with a null or NaN** — e.g., `max(NaN, 0)` where the "identity element" handler and the "NaN propagation" handler conflict.
- **Empty collection crossed with a boundary-length collection** — e.g., joining an empty table with a table that has zero columns, where both "empty input" handlers assume the other input provides schema information.
- **Multiple parameters simultaneously at type-boundary values** — e.g., both arguments at `INT_MAX`, where individual overflow checks assume only one operand is extreme.

## PR Examples

- **sympy__sympy-20212**: A dispatch cascade in a mathematical operation handled individual special parameter values (e.g., zero, infinity) in separate branches, but the cross-product combination of two simultaneously special inputs was not covered, causing a silently wrong result. The fix added an explicit early-return check for the intersection case before the general single-parameter handlers.