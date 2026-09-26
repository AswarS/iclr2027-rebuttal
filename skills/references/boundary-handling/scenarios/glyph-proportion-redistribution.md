## Problem Description

When constructing text-based or character-grid renderings of composite visual symbols (such as mathematical operators like ∏, ∑, or bracket-like glyphs), developers often model the symbol as a simple rectangle where corner/boundary characters define the full extent of the glyph. This leads to a characteristic distortion: all decorative width is allocated to the interior space between vertical boundaries, producing a symbol that is disproportionately wide internally while its horizontal bars terminate abruptly at the corners without the visual overhang that gives the glyph its proper typographic weight. Additionally, off-by-one errors in vertical extent introduce spurious blank rows that create asymmetric whitespace.

## Root Cause Analysis

The fundamental issue is an **implicit assumption that a composite glyph's bounding box coincides with its structural frame**. In reality, typographic glyphs like product (∏) or summation (∑) symbols are not simple rectangular frames — their horizontal bars intentionally extend *beyond* the vertical supports to create a T-shaped or bracket-like silhouette. When the rendering code treats corner characters as the outermost extent of the symbol, two things go wrong simultaneously:

1. **Width misallocation**: The total allocated decorative width is stuffed entirely into the interior between vertical bars, inflating the symbol's internal cavity while starving the exterior of the overhang that defines the glyph's visual identity.
2. **Symmetry-breaking off-by-one**: The vertical body loop often includes an extra iteration (e.g., `height + 2` instead of `height + 1`) — likely added to "balance" a top bar — but since the bottom of the symbol is intentionally open (no bottom bar), the extra row creates visual asymmetry rather than resolving it.

The cognitive trap is treating a *glyph* design problem as a *container* layout problem, conflating the frame boundary with the glyph boundary.

## Solution Strategy

### 识别信号
- 观测到的现象: Rendered symbol appears disproportionately wide or tall compared to its content; horizontal structural bars (e.g., top bars) end flush at corner characters without visual overhang; unnecessary blank rows or columns produce asymmetric whitespace; the output looks correct at large sizes but visibly wrong at small or minimum content sizes.

### 解决步骤
1. **Decompose the glyph into structural roles**: Identify which characters form the "frame" (corners, vertical bars) and which form the "extensions" (horizontal bars that should overhang past the frame). Map out the intended visual silhouette independent of the bounding box.
2. **Redistribute width from interior to exterior**: Instead of allocating all padding inside the vertical boundaries, move the vertical boundaries inward (reduce internal width) and extend horizontal bars outward past the corners by the reclaimed amount — typically 1 character per side. This transforms the glyph from a fat rectangle into the intended T-shaped or bracket-like profile.
3. **Audit the vertical extent for off-by-one errors**: Check whether the loop constructing vertical body rows iterates one time too many (e.g., `height + 2` when `height + 1` is correct). Remove the extra iteration to eliminate the spurious trailing blank line.
4. **Validate at minimum content sizes**: Test with single-character or minimal content to ensure the narrower, corrected symbol doesn't collapse or degenerate. Confirm that the overhang remains visually coherent at all scales.

### Why This Works

The solution realigns the rendering model with the actual typographic intent of the glyph. By moving decorative space from the interior to the exterior (as overhang), the symbol achieves its characteristic silhouette — horizontal bars wider than the vertical body — rather than appearing as an inflated rectangular frame. Fixing the off-by-one in vertical iteration removes a row that was compensating for a non-existent bottom bar, restoring vertical symmetry. Together, these changes ensure the glyph's proportions match the visual expectations established by mathematical typesetting conventions.

## Boundary Cases
- **Single-character content**: The narrowed interior must still accommodate the minimum content width without collapsing the vertical bars onto the content itself.
- **Very tall content**: The vertical body should scale correctly without the off-by-one compounding into noticeable trailing whitespace.
- **Symbols with both top and bottom bars** (e.g., brackets, matrices): The overhang redistribution must be applied symmetrically to both ends, and the extra-row fix does *not* apply since both bars are present.
- **Odd vs. even total width**: When redistributing width, ensure the overhang is balanced (e.g., 1 character on each side) and doesn't create a lopsided glyph when the total available space is odd.
- **Nested or composed symbols**: When one glyph is embedded inside another (e.g., subscript/superscript on a product symbol), the adjusted bounding box must be correctly communicated to the parent layout engine.

## PR Examples
- sympy__sympy-16281