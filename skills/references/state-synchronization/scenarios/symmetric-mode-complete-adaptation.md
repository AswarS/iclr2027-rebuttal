## Problem Description

When a component supports two symmetric operational modes (e.g., horizontal vs. vertical orientation, row-major vs. column-major, left-to-right vs. right-to-left), the second mode is often implemented by adapting only the most visually obvious rendering code while leaving the rest of the coordinate-dependent logic hardcoded to the first mode. This creates a component that appears correct at rest in the second mode but crashes, misaligns, or fails silently during initialization with non-default values, programmatic state changes, user interaction (click, drag), and hit detection. The pattern is a form of **incomplete symmetric adaptation** — the mode switch permeates every coordinate-dependent operation, but only a subset of those operations are updated.

## Root Cause Analysis

The underlying cause is **symmetry-breaking through selective adaptation**. A developer mentally models the second mode as a localized variation, reasoning that changing the drawing/rendering path is sufficient. However, in any interactive, stateful component, the choice of active axis or dimension is not confined to rendering — it propagates through:

- **Initialization**: geometric primitives (polygons, rectangles, handle markers) are constructed with axis-specific vertex counts or positions.
- **Programmatic value setting**: updating a slider position, selection range, or indicator requires writing to the correct coordinate.
- **Event interpretation**: mouse/touch events carry both x and y; the handler must read the correct one.
- **Hit detection**: proximity checks must compare the event coordinate against element positions on the correct axis.
- **Visual feedback updates**: handle positions, highlight regions, and annotation placements must track the active axis.

When only the rendering path is adapted, shared update code that indexes into geometric data structures (e.g., polygon vertices) may encounter index-out-of-bounds errors because the second mode's constructor produced a different vertex layout. Drag handlers read the wrong event coordinate, so elements don't track the cursor. Hit-test logic compares against the wrong axis, so clicks don't register. The result is a component that passes visual inspection in a static screenshot but fails every dynamic interaction path.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Crashes or `IndexError` when initializing the second mode with non-default values
  - Visual handles or indicators not tracking user drag in the second mode
  - Click/tap targeting failing — elements cannot be selected in the second mode
  - Programmatic value changes (e.g., `set_val()`) not reflected visually in the second mode
  - One mode works flawlessly while the other exhibits intermittent or consistent failures across interaction paths

### 解决步骤

1. **Audit every method for coordinate-axis-dependent operations.** Search the entire component for references to axis-specific properties (`x` vs. `y`, `width` vs. `height`, `xdata` vs. `ydata`, row vs. column indices). Do not limit the search to the rendering/drawing method.

2. **Enumerate all state-mutating paths.** List every code path that reads or writes coordinate data: initialization/construction, programmatic value setting, interactive drag handling, hit-testing/proximity detection, and visual feedback updates. Each path must be verified independently.

3. **Add mode-conditional branching to every identified path.** For each path:
   - **Initialization**: Ensure geometric primitives are constructed with the correct vertex layout, dimensions, and axis alignment for both modes.
   - **Value setting**: Update visual markers (handles, indicators, highlight regions) along the correct axis.
   - **Drag handling**: Read the event coordinate from the correct axis (`event.xdata` vs. `event.ydata`) and update the visual element along that same axis.
   - **Hit detection**: Compare the event coordinate against element positions on the correct axis.

4. **Centralize coordinate-dependent updates in a single authoritative method.** Create or refactor a canonical value-setting method that all paths (initialization, user interaction, programmatic API) funnel through. This method encapsulates the mode-conditional logic once, eliminating divergence.

5. **Verify geometric primitive consistency.** Ensure that mode-specific constructors produce data structures with the same expected shape (e.g., same number of polygon vertices) so that shared index-based update code does not encounter out-of-bounds access. If vertex layouts differ inherently, the update code must also branch on mode.

6. **Test both modes through all interaction paths.** For each mode, verify: initialization with default and non-default values, programmatic value changes via public API, click-to-select, drag-to-move, and visual consistency after each operation.

### Why This Works

The mode choice is a **cross-cutting concern** that affects every layer of the component's coordinate logic. By systematically auditing all coordinate-dependent operations — not just the rendering path — and funneling them through a single authoritative method, the fix eliminates the class of bugs caused by partial adaptation. Centralizing the mode-conditional logic ensures that future changes to value-setting behavior automatically propagate to all entry points (initialization, interaction, API), preventing regression.

## Boundary Cases

- **Geometric primitive vertex count mismatch**: When the two modes require different polygon shapes (e.g., a horizontal slider uses a 4-vertex rectangle while a vertical slider uses a 5-vertex polygon), shared update code that indexes vertices by position will crash in one mode. Either normalize the vertex count or branch the update logic.
- **Compound components with nested sub-elements**: A component may contain multiple interactive sub-elements (e.g., two handles on a range slider), each of which independently requires full symmetric adaptation. Missing the adaptation on even one sub-element creates a subtle partial failure.
- **Animation or timer-driven updates**: If the component supports animated transitions or periodic refresh, the animation callback is another state-mutating path that must respect the active mode — easily overlooked since it is neither user-initiated nor part of the public API.
- **Serialization and deserialization**: Saving and restoring component state (e.g., to a config file or undo stack) may encode axis-specific values; the restore path must interpret them according to the correct mode.
- **Dynamic mode switching at runtime**: If the component allows changing orientation after construction, all cached geometric state must be invalidated and reconstructed, not just the rendering output.

## PR Examples

- **matplotlib__matplotlib-22711**: A slider widget's vertical orientation mode was implemented by modifying only the drawing code. Initialization with non-default values, programmatic `set_val()`, drag tracking, and hit detection all remained hardcoded to horizontal axis logic, causing crashes and non-functional interaction in vertical mode.