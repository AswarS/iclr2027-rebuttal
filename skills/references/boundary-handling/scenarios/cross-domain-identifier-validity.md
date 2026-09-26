## Problem Description

When an identifier string originating from one domain (e.g., OS authentication, LDAP, SSO) is used directly as a component in a different structural domain (e.g., filesystem paths, URLs, database keys), characters that are perfectly legal in the source domain can be illegal or carry unintended structural meaning in the target domain. The classic manifestation is a Windows domain login like `DOMAIN\user` being embedded into a filesystem path — the backslash is interpreted as a path separator, corrupting the directory structure and causing crashes (`FileNotFoundError`, `OSError`) at runtime. This pattern is insidious because it works flawlessly in the most common environments (local logins, simple usernames) and only surfaces in specific authentication contexts (domain-joined Windows machines, SSH sessions, LDAP-backed systems), making it a latent regression that escapes typical testing.

## Root Cause Analysis

The underlying principle is **domain conflation** — the implicit assumption that a value valid in its source domain will remain valid when transplanted into a structurally different target domain. Identity strings from authentication systems have their own grammar (allowing `\`, `/`, `@`, spaces, etc.), while filesystem paths, URLs, and other structured names have a separate, often more restrictive grammar where those same characters carry structural meaning or are outright forbidden.

The bug typically lives in a utility function that retrieves the external identity string and returns it "as-is" for downstream consumers to embed in path construction, key generation, or name formatting. Because the retrieval function doesn't enforce target-domain invariants, every downstream consumer silently inherits the vulnerability. The problem is compounded by the fact that fallback logic (e.g., catching exceptions and returning `"unknown"`) only handles the case where retrieval *fails entirely*, not the case where retrieval *succeeds but returns a structurally dangerous value*.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `FileNotFoundError`, `OSError`, or equivalent filesystem/network errors when creating directories, files, or resources using a name derived from an external identity string.
  - Failures that are **environment-dependent** — the code works on developer machines but crashes in CI, production, or specific authentication contexts (Windows domain logins, Kerberos, LDAP).
  - Stack traces pointing to path construction or `os.makedirs` / `open()` calls where the path contains unexpected directory segments (e.g., a username with `\` splitting into subdirectories).
  - Regression that appears after no apparent code change — triggered instead by a change in deployment environment or user population.

### 解决步骤
1. **Audit retrieval boundaries**: Identify every code path where an externally-sourced identity string (username, hostname, service principal, etc.) is retrieved from an OS or authentication API and subsequently used in structured name construction (paths, URLs, cache keys, log filenames).
2. **Sanitize at the point of retrieval**: Apply a targeted transformation immediately when the value is obtained — before it is returned to any caller. Replace characters that are illegal or structurally meaningful in the target domain. For filesystem paths, use a regex like `re.sub(r'[\\/:*?"<>|]', '_', value)` or, at minimum, `re.sub(r'[\\/]', '_', value)` to neutralize path separators.
3. **Preserve identity uniqueness**: Prefer character replacement (e.g., `\` → `_`) over truncation or extraction (e.g., taking only the part after `\`). This ensures that `DOMAIN_A\user` and `DOMAIN_B\user` remain distinguishable as `DOMAIN_A_user` and `DOMAIN_B_user`.
4. **Retain the existing fallback for retrieval failure**: Keep the `try/except` that returns a safe static string (e.g., `"unknown"`) for cases where the retrieval call itself raises an exception. This fallback should **not** be the primary defense against illegal characters — it is a last resort for total retrieval failure.
5. **Add targeted tests**: Write test cases that inject identity strings containing known cross-domain dangerous characters (`\`, `/`, `:`, null bytes) and verify that the sanitized output is safe for the target domain and preserves uniqueness.

### Why This Works

Sanitizing at the retrieval boundary enforces a **domain translation contract**: every downstream consumer receives a string that is guaranteed to be valid in the target domain, without needing to independently handle edge cases. This follows the principle of validating and normalizing inputs at system boundaries. The minimal, targeted replacement strategy avoids over-sanitization (which would reduce debuggability and uniqueness) while still neutralizing the specific class of characters that cause structural corruption. By keeping the transformation close to the source, the fix is applied once and benefits all consumers — eliminating the combinatorial risk of N call sites each needing their own defensive logic.

## Boundary Cases
- **Windows domain logins** (`DOMAIN\user`): The backslash is a path separator on Windows, splitting the intended single directory name into a nested path.
- **Usernames with forward slashes** (`org/user`): Forward slashes are path separators on Unix/macOS, causing the same structural corruption on those platforms.
- **Usernames containing colons** (`user:role`): Colons are illegal in filenames on Windows and have special meaning in URLs and some key-value stores.
- **Null bytes in identity strings** (`user\x00`): Null bytes terminate C-strings and can cause silent truncation or security vulnerabilities in filesystem operations.
- **Empty string after sanitization**: If the entire identity string consists of illegal characters, sanitization could produce an empty string. A post-sanitization check should fall back to a safe default.
- **Very long identity strings**: Some authentication systems allow very long principal names that may exceed filesystem path length limits after embedding. Consider truncation with a hash suffix for uniqueness.
- **Multi-user environments with fallback collisions**: If sanitization is replaced by a blanket fallback to `"unknown"`, all users share a single identity — causing permission conflicts, cache poisoning, or data leakage between users.

## PR Examples
- **pytest-dev__pytest-8365**: Windows domain usernames containing backslashes (`DOMAIN\user`) were passed unsanitized into temporary directory path construction, causing `FileNotFoundError` when `os.makedirs` interpreted the backslash as a path separator. The fix sanitized the username at the retrieval point in the utility function, replacing path-separator characters before any downstream consumer could use the value.