## Problem Description

When multiple ordered sequences need to be merged into a single combined sequence, a common implementation approach is to use a binary fold (reduce) — iteratively merging two lists at a time and feeding each intermediate result into the next merge step. This pattern silently breaks when the pairwise merge operation is **non-associative**, meaning `merge(merge(A, B), C)` does not produce the same result as `merge(A, merge(B, C))` or a simultaneous merge of all inputs. Ordered-list merging is almost never associative because each intermediate result introduces **synthetic ordering constraints** not present in any original input. These phantom constraints accumulate across fold iterations and eventually conflict with real constraints from later inputs, producing spurious conflict warnings, incorrect output orderings, or both.

## Root Cause Analysis

The fundamental issue is an **implicit assumption that the merge operation is associative**, analogous to summing numbers or taking the union of sets. When merging two ordered lists, the algorithm must interleave elements to satisfy both orderings. The resulting merged list encodes transitive ordering relationships that are artifacts of the interleaving — they were not specified by either original input. When this intermediate result is then merged with a third list, those phantom edges are treated as ground truth. This means:

1. **False constraints propagate**: Each fold step adds synthetic ordering edges that constrain subsequent merges.
2. **Real constraints get violated**: A later input list may specify an ordering that contradicts a phantom constraint from an earlier intermediate result, causing the algorithm to either emit a spurious conflict warning or silently produce an output that violates the original input's ordering.
3. **Input order sensitivity**: Rearranging the order of the input sequences changes which phantom constraints are generated, leading to non-deterministic or order-dependent results — a hallmark of this bug pattern.

The cognitive trap is that pairwise merge works perfectly for two inputs, so developers naturally assume folding it over N inputs generalizes correctly. It does not.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Spurious ordering conflict warnings that reference pairs of elements with no actual conflict in the original inputs.
  - Output orderings that contradict constraints explicitly present in one or more original input lists.
  - The problem disappears, changes, or shifts to different elements when the order of input sequences is rearranged.
  - Correct behavior with 2 input sequences but incorrect behavior with 3 or more.

### 解决步骤
1. **Verify non-associativity**: Confirm that the binary merge operation is non-associative by constructing a minimal example with 3 input sequences where `reduce(merge, [A, B, C])` produces a different (incorrect) result than a simultaneous merge of all three.
2. **Build a unified dependency graph**: Replace the pairwise fold with an n-ary algorithm. For each input sequence, create directed edges `a → b` for every consecutive pair `(a, b)`. Combine all edges into a single dependency graph.
3. **Topological sort with stable tiebreaking**: Resolve the combined dependency graph via topological sort. Use a stable variant (e.g., Kahn's algorithm with a queue ordered by first-seen insertion position) to produce deterministic output when multiple valid orderings exist.
4. **Handle cycles gracefully**: If the dependency graph contains cycles (representing genuinely irreconcilable conflicts), fall back to a best-effort ordering (e.g., insertion-order deduplication) and emit a warning that references **all conflicting input lists** — not just a misleading pair of elements from an intermediate merge result.
5. **Update call sites**: Refactor all call sites to collect all sublists upfront and pass them to the n-ary merge in a single invocation, rather than folding incrementally.

### Why This Works

Topological sort over a simultaneously-constructed dependency graph ensures that **every edge comes directly from an original input**. No intermediate results exist, so no phantom constraints can be introduced. The algorithm naturally handles partial orderings from multiple sources without inventing transitive relationships. Stable tiebreaking preserves determinism and respects the "spirit" of the original input ordering when the dependency graph leaves ambiguity. Reporting all input lists on conflict gives users actionable diagnostic information about the actual source of the incompatibility.

## Boundary Cases
- **Two input sequences**: The binary merge and n-ary merge should produce identical results; this is the degenerate case where non-associativity is not observable.
- **Duplicate elements across inputs**: The dependency graph must handle the same element appearing in multiple sequences, creating edges from multiple sources — deduplication must preserve all ordering constraints.
- **Single input sequence**: Should be returned as-is with no merge logic invoked.
- **Empty input sequences**: Must be gracefully ignored without corrupting the dependency graph.
- **True cyclic conflicts**: Input sequences that genuinely contradict each other (e.g., `[A, B]` and `[B, A]`) must be detected and reported with full provenance, not masked by phantom constraints.
- **All inputs identical**: Should produce the same sequence with no warnings.
- **Large number of inputs**: The n-ary algorithm must scale linearly with total number of elements across all inputs, not quadratically as nested pairwise merges might.

## PR Examples
- django__django-11019: MRO-style merging of CSS/JS media lists used `reduce(merge, ...)` over ordered asset lists from multiple form widgets, producing spurious ordering warnings and incorrect asset orderings when 3+ widgets contributed media declarations.