## Problem Description

When a rendering or layout system assembles multi-line text blocks (such as pretty-printing, ASCII art, or terminal UI), it must horizontally and vertically concatenate sub-expressions that have structurally different multi-line layouts. A common defect arises when the system assumes all sub-expression blocks share the same vertical geometry — specifically, that labels, decorators, or operators can be placed at a single fixed row index (e.g., always row 0). This **uniform-structure assumption** causes misalignment, duplicated decorators inside nested delimiters, or visually broken output whenever structurally distinct forms (fractions, superscripts, tall delimiters, simple terms) are combined in the same expression.

## Root Cause Analysis

Multi-line text layout is inherently a **2D problem**: each rendered block has both a height and a **baseline** (semantic anchor row) — the fraction bar for fractions, the base row for superscripts, the center row for tall delimiters, etc. When the layout engine treats placement as a 1D problem by hardcoding a fixed anchor row, it works correctly only for the single class of expression the original developer tested against. As soon as richer expression forms are introduced, the fixed-row assumption silently breaks.

This is a manifestation of **complexity escalation blindness**: the initial implementation was adequate for simple cases (e.g., single-line terms or uniformly structured parenthesized groups), but the invariant it relied on — "all blocks have the same vertical structure" — was never explicitly stated or enforced. When new structural forms appeared, no discriminator existed to detect the difference, and the single placement rule produced incorrect 2D positioning.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Labels or decorators appear duplicated inside nested delimiters.
  - Vertical baselines of horizontally concatenated blocks are visibly misaligned.
  - Output is correct for simple/uniform expressions but breaks for mixed-structure expressions (e.g., a fraction next to a power next to a plain term).
  - Regression appears when a new multi-line expression form is added to the renderer.

### 解决步骤
1. **Locate the assembly logic** that places labels, decorators, or operators onto multi-line rendered blocks. Confirm whether it uses a single fixed row index (e.g., always row 0 or always the last row) for placement.
2. **Enumerate structurally distinct multi-line forms** that sub-expressions can take. For each form, determine where the semantic anchor row actually is (e.g., the fraction bar row, the base row for superscripts, the center row for tall delimiters, row 0 for single-line terms).
3. **Introduce structural discriminators** that detect which form a given rendered block has. Prefer inspecting structural markers already present in the rendered output (specific delimiter characters, line content patterns, block height) rather than reaching back into the AST, since the bug lives in the rendering layer.
4. **Compute the correct row for each form** — both for label/decorator placement and for baseline alignment during horizontal concatenation. Replace the single fixed insertion rule with a discriminated set of rules, each matched to a specific structural form.
5. **Align blocks during horizontal concatenation** by padding shorter blocks with blank lines (above, below, or both) so that their anchor rows align, then set the composite baseline to the aligned anchor row.
6. **Add comprehensive test cases** covering at least: (a) a fraction-like multi-line block with a label/decorator, (b) a single-line term concatenated next to a multi-line term, (c) a power/superscript multi-line form with a label, and (d) nested combinations of all the above.

### Why This Works

The fix replaces an implicit, untested invariant ("all blocks share the same vertical geometry") with an explicit, discriminated mapping from structural form to anchor-row computation. Each known multi-line form gets its own correct placement rule, restoring proper 2D positioning. By operating on structural markers in the rendered output rather than AST properties, the fix stays local to the rendering layer where the bug originates. Padding and baseline alignment during concatenation ensure that composite blocks inherit correct geometry regardless of the mix of sub-expression forms.

## Boundary Cases
- **Single-line term next to a tall multi-line term**: the single-line block must be vertically centered or baseline-aligned, not top-aligned by default.
- **Deeply nested fractions or powers**: anchor row computation must be recursive or compositional — a fraction whose numerator is itself a fraction has a different anchor row than a simple fraction.
- **Empty or zero-height blocks**: padding logic must handle degenerate cases without producing negative indices or off-by-one errors.
- **Odd vs. even total height**: centering logic must have a consistent tie-breaking rule (e.g., prefer shifting up) to avoid jitter between similar expressions.
- **Mixed decorators on the same block**: when multiple labels/operators attach to one block (e.g., a conjugate bar on top of a fraction with a subscript), each decorator must reference the correct anchor independently.

## PR Examples
- sympy__sympy-14308