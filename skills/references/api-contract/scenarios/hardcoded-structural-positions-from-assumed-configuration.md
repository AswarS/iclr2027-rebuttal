## Problem Description

A subclass of a parameterizable parent class hardcodes structural positions (line indices, offsets, separator locations, etc.) based on a single assumed configuration, rather than computing them dynamically from actual runtime parameters. When users attempt to use the subclass with non-default parameter values — values that the parent class fully supports — the subclass either rejects the parameter outright (e.g., unexpected keyword argument error) or produces malformed output because its hardcoded constants no longer correspond to the actual structure.

This pattern commonly arises in serialization layers, format writers/readers, and layout engines where a parent class defines a flexible structure (e.g., configurable number of header rows, variable-length preambles) and a subclass specializes the format but inadvertently freezes structural assumptions that should remain dynamic.

## Root Cause Analysis

The root cause is **single-configuration mental modeling** during subclass implementation. The developer designs the subclass with only the most common use case in mind (e.g., exactly one header row, a fixed number of metadata lines) and encodes the structural consequences of that single configuration as literal constants — magic numbers in index calculations, hardcoded class attributes for line positions, or fixed offsets in slicing logic.

This creates a **capability mismatch** between the parent's interface contract and the subclass's actual behavior. The parent promises parameterizability; the subclass silently violates that promise. The subclass appears to be a proper specialization (adding format-specific behavior) but is actually a restriction (removing supported configurations). Because the constants are correct for the default case, the defect remains latent until a user exercises a non-default parameter combination, at which point the mismatch between the parameter's effect on the logical structure and the hardcoded physical positions causes crashes, type errors, or corrupted output.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or unexpected keyword argument errors when passing a parent-supported parameter to the subclass
  - Malformed or corrupted output (e.g., misaligned columns, duplicated separator lines, missing header rows) when a structural parameter deviates from its default value
  - Magic numbers in the subclass that correspond to structural positions (e.g., `self.data.start_line = 3`, `header_line = 1`, `splitter_index = 1`)
  - Class-level attributes that encode assumptions about runtime configuration (e.g., `data_start = 2` as a class constant)

### 解决步骤
1. **Identify blocked parameters**: Verify that the subclass constructor accepts and forwards all relevant parent class parameters. If the subclass overrides `__init__`, ensure it uses `**kwargs` or explicitly passes through configuration parameters that the parent supports. Remove any artificial restrictions on parameter acceptance.
2. **Audit hardcoded structural constants**: Search the subclass for magic numbers and class-level constants that encode assumptions about the output/input structure. For each one, trace back to determine which configuration parameter it implicitly assumes a fixed value for. Document the mapping (e.g., "`separator_index = 1` assumes `header_rows = 1`").
3. **Replace constants with derived computations**: For each identified hardcoded value, replace it with a dynamic expression that computes the correct value from the actual runtime configuration. For example, replace `separator_line = 1` with `separator_line = len(header_rows)`, or replace `data_start = 3` with `data_start = num_header_lines + num_separator_lines`.
4. **Move class-level attributes to method-level computation**: If a structural value is defined as a class attribute but must vary based on runtime configuration, remove the class attribute and compute the value inside the method where it is consumed, after the configuration is known.
5. **Verify round-trip correctness**: Ensure that both the write path (output formatting) and the read path (input parsing) are updated consistently. Write data with various parameter combinations and confirm it can be read back identically. Pay special attention to boundary values (e.g., zero header rows, maximum header rows).

### Why This Works

The fix restores the subclass to being a **proper specialization** of the parent rather than an inadvertent restriction. By making structural positions functions of configuration parameters rather than frozen constants, the subclass's behavior remains correct across all valid parameter combinations that the parent supports. The subclass adds format-specific behavior (its intended purpose) without silently removing the parent's parameterization flexibility. This aligns the runtime behavior with the interface contract, eliminating the capability mismatch that caused the failures.

## Boundary Cases
- **Default parameter values must remain correct**: After replacing constants with computations, verify that the default configuration still produces identical output to the original hardcoded behavior — the refactoring must be backward-compatible.
- **Zero or empty configurations**: If the parameter can be set to zero (e.g., zero header rows), ensure the computed positions handle this gracefully without negative indices or off-by-one errors.
- **Maximum or unusually large configurations**: Test with large parameter values (e.g., many header rows) to confirm that computed positions scale correctly and don't overflow or misalign.
- **Interaction between multiple parameterized features**: When multiple structural parameters are configurable (e.g., header rows *and* comment lines), ensure the derived computations account for all combinations, not just independent variation of each parameter.
- **Subclass-of-subclass chains**: If the affected subclass is itself subclassed further, verify that the dynamic computation is not re-hardcoded at a deeper level in the hierarchy.

## PR Examples
- astropy__astropy-14182