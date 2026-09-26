## Problem Description

When programmatically constructing command-line invocations for external CLI tools, developers often treat the argument list as an unordered collection where flags and positional arguments can be freely interleaved. However, many POSIX-style CLI tools use the first positional argument (e.g., a database name, filename, or URL) as a parsing boundary — once encountered, the argument parser stops interpreting subsequent tokens as option flags. Any flags placed after this positional terminator are silently ignored or misinterpreted, producing no error but also no effect. This makes the failure extremely subtle: the command executes successfully, but dynamically injected options have no impact.

## Root Cause Analysis

The root cause is an **implicit assumption of argument order interchangeability**. Developers building command-line argument lists programmatically assume that the position of flags relative to positional arguments is irrelevant — that `-c some_option dbname` and `dbname -c some_option` are semantically equivalent. This assumption holds within the options-only portion of a command, but breaks at the boundary where a positional argument acts as a terminator for option parsing.

The underlying principle is that an external tool's CLI interface constitutes an **API contract with ordering semantics**. Unlike keyword arguments in most programming languages, CLI argument parsing is inherently sequential. Tools like `psql`, `ssh`, `mysqldump`, and others follow conventions where positional arguments partition the argument list into distinct parsing zones. The calling code must honor this structural contract, even though violating it produces no explicit error — only silent data loss or behavioral omission.

This is compounded by the fact that argument assembly code often grows incrementally: a base command is constructed with the positional argument in place, and later code paths append additional flags to the end of the list. As long as no dynamic flags are injected, the ordering issue remains latent. It only manifests when a user or configuration mechanism introduces extra parameters that land after the positional terminator.

## Solution Strategy

### 识别信号
- 观测到的现象: Extra flags or options passed to an external CLI tool via a dynamic injection mechanism (e.g., user-configurable parameters, settings-driven arguments) are **silently ignored** — the command completes without error, but the flags have no observable effect on the tool's behavior.
- No error messages, no warnings, no non-zero exit codes — the failure is entirely silent.
- The issue is intermittent in appearance: it only manifests when dynamic/user-supplied flags are present, not with the base command.

### 解决步骤
1. **Audit the external tool's argument parsing semantics.** Consult the tool's man page or documentation to determine whether it uses positional arguments as option-parsing terminators. Look for phrases like "the first non-option argument" or argument ordering requirements.
2. **Identify the positional terminator in your constructed command.** Locate which argument in your assembly code serves as the positional boundary (e.g., a database name passed to `psql`, a hostname passed to `ssh`, a filename passed to a compiler).
3. **Restructure argument assembly to enforce correct ordering.** Refactor the code so that all option flags — both static and dynamically injected — are collected and inserted **before** the positional terminator. The positional argument should always be appended as the final element (or after a `--` separator if the tool supports it).
4. **Centralize the assembly point.** Rather than allowing multiple code paths to append to the argument list independently, create a single assembly point where the final ordering is enforced: options first, then positional arguments.
5. **Add ordering-aware tests.** Write test cases that inject extra flags via the dynamic mechanism and assert that they appear **before** the positional argument in the final constructed command. Test with multiple injected flags to ensure none slip past the boundary.

### Why This Works

By ensuring all option flags precede the positional terminator, the external tool's argument parser encounters them in the zone where it is actively scanning for options. The positional argument, placed last, correctly signals the end of option parsing without prematurely terminating it. This respects the tool's implicit API contract about argument ordering and guarantees that dynamically injected parameters are actually processed by the tool rather than silently discarded.

## Boundary Cases
- **Multiple positional arguments**: Some tools accept more than one positional argument (e.g., source and destination). All option flags must precede the *first* positional argument, not just the last.
- **The `--` separator convention**: Some tools support `--` to explicitly separate options from positional arguments. Using `--` before positional arguments can provide an additional safety net, but flags must still appear before `--`.
- **Flags that themselves take positional-looking values**: Options like `-o filename` where the value resembles a positional argument must be kept together and before the true positional terminator.
- **User-supplied parameters containing positional arguments**: If the dynamic injection mechanism allows users to pass their own positional arguments (not just flags), these must also be placed correctly relative to the tool's expected positional argument order.
- **Tools with subcommand structures** (e.g., `git commit -m "msg"`): The subcommand itself is a positional argument that changes the parsing context; flags must be ordered relative to the subcommand, not just the final positional argument.

## PR Examples
- django__django-15851: Database client command construction placed the database name (a positional terminator for tools like `psql`) before user-supplied extra parameters, causing those parameters to be silently ignored. The fix ensured the database name is always appended last, after all option flags and user-injected arguments.