## Problem Description

When implementing composite data structures that stitch together regions from multiple sources (e.g., inserting rows/columns into a matrix, splicing arrays, or merging coordinate spaces), a piecewise index-mapping function routes combined-space indices back to the correct original source. This pattern typically has three branches: *before* the insertion point, *within* the inserted block, and *after* the inserted block. The bug arises when the **boundary condition** (the insertion position that decides which branch applies) is accidentally conflated with the **offset** (the arithmetic that translates a combined-space index back to a source-space index) in the "after insertion" branch. The result is a formula that only produces correct values when the insertion position happens to be zero.

## Root Cause Analysis

The boundary parameter and the offset parameter serve fundamentally independent roles in a piecewise coordinate remapping:

- **Boundary (routing):** The insertion position determines *which* branch of the piecewise function a given index falls into — i.e., which source to consult.
- **Offset (translation):** The size of the inserted block determines *how much* to shift an index to recover the corresponding position in the original source.

The cognitive trap is reasoning: "to undo everything before this region, I subtract the insertion position plus the inserted size." This mentally collapses two independent quantities into a single subtraction. In truth, for elements after the inserted block, the only difference between their position in the combined space and their position in the original source is the number of newly inserted elements — regardless of where the insertion occurred. Mixing the insertion position into the offset breaks a symmetry invariant: moving the insertion point should only change *which* elements land in *which* branch, never *how* coordinates are translated within a branch.

## Solution Strategy

### 识别信号
- 观测到的现象: Wrong output values for elements located **after** a non-zero insertion point. Results are correct only when insertion occurs at position 0 or at the very end of the structure. Specifically, elements after the insertion carry values that appear shifted by the insertion position rather than by the inserted block size.

### 解决步骤
1. **Isolate the piecewise mapping.** Locate the function that converts combined-space indices back to source-space indices. Identify every branch and the condition that guards it.
2. **Separate boundary from offset in each branch.** For each branch, explicitly label (a) the boundary condition (comparison against the insertion position) and (b) the offset arithmetic (subtraction to recover the source index). Confirm they reference independent parameters.
3. **Fix the "after insertion" branch.** Ensure the offset equals exactly the size of the inserted block (`inserted_size`), **not** `insertion_position + inserted_size`. The corrected translation is: `source_index = combined_index - inserted_size`.
4. **Add regression tests at non-trivial insertion positions.** Insert at a position that is neither 0 nor the end. Verify that every element after the insertion point maps back to the correct value from the original source.

### Why This Works

The fix restores the invariant that the offset in each branch depends only on the *size* of the region that displaces indices, not on *where* that region was placed. The insertion position is used solely for routing (choosing the branch), while the inserted block size is used solely for translation (recovering the original coordinate). Keeping these concerns orthogonal guarantees correctness for all insertion positions.

## Boundary Cases

- **Insertion at position 0:** The "before insertion" branch is empty; all original elements fall into the "after insertion" branch. The offset must still equal the inserted block size, not `0 + inserted_size` (which happens to be the same, masking the bug).
- **Insertion at the end:** The "after insertion" branch is empty, so the faulty offset is never exercised — another configuration that masks the bug.
- **Insertion at a middle position with inserted block size ≠ insertion position:** This is the critical case that exposes the conflation, because `insertion_position + inserted_size ≠ inserted_size`.
- **Inserted block of size 0:** Degenerates to the identity mapping; the offset is 0 regardless, so no bug is visible.
- **Multiple successive insertions:** Each insertion shifts the coordinate space further; conflating boundary and offset compounds the error with each additional insertion.

## PR Examples

- **sympy__sympy-13647** — Matrix column/row insertion used the insertion position in the offset arithmetic of the piecewise index function, producing incorrect element values for any non-zero, non-end insertion point.