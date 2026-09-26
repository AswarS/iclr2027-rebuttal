## Problem Description

When implementing solvers or search functions over algebraic domains (modular arithmetic, finite fields, rings), the zero/identity element that trivially satisfies an equation is systematically missed. The core algorithm uses residue classification, group-theoretic properties, or iterative lifting techniques (e.g., Hensel lifting) that implicitly assume nonzero inputs. As a result, the function returns all correct nonzero solutions but silently omits the trivial zero solution — a classic case of **boundary-blindness** where sophisticated algebraic machinery creates false confidence that all cases are exhaustively covered.

This pattern generalizes beyond modular arithmetic: any solver that delegates to group-theoretic subroutines risks excluding elements that lie in the kernel or outside the group but still belong to the broader algebraic structure (the full ring) over which the original equation is defined.

## Root Cause Analysis

The fundamental issue is a **conflation of the ring with its multiplicative group**. Algebraic solvers often rely on multiplicative group structure — quadratic residue classification, Legendre symbols, primitive roots, discrete logarithms — which is only defined for invertible (nonzero) elements. The zero element lives outside this group but still satisfies the original equation (e.g., 0² ≡ 0 mod n).

This creates a cognitive trap: developers mentally model the solution space as the multiplicative group of the domain, forgetting that the equation is defined over the full ring including zero. The sophisticated algebraic machinery feels exhaustive, so the omission goes unnoticed.

A secondary failure mode occurs in **Hensel lifting** (iterative p-adic refinement). The standard Newton-style update requires an invertible derivative at the current solution. When the derivative is zero — which happens precisely at singular/degenerate points like the zero element — the lifting formula breaks down. Without a fallback, these singular branches are silently dropped, losing valid solutions that could only be found by brute-force enumeration at that lifting level.

Finally, when decomposing problems over composite moduli into prime-power subproblems, incomplete solution sets at the component level propagate through CRT reconstruction, causing missing solutions in the final composite result.

## Solution Strategy

### 识别信号
- 观测到的现象: 函数返回正确的非零解，但遗漏了零解或平凡解（**partial-result**, **wrong-output**）
- 当输入恰好是模数的倍数或域的零元素时，返回空集而非包含零的解集
- Hensel lifting 在某些分支上静默丢失解，尤其是导数为零的奇异点
- 复合模数下的解集不完整，缺少某些 CRT 组合

### 解决步骤
1. **识别退化边界**：在进入主算法路径之前，检查输入是否为域的零元素（例如 input ≡ 0 mod modulus）。这是平凡满足方程的情况，必须单独处理。
2. **在早期插入零元素检查**：将检查放在分派逻辑（如复合模数分解为素数幂）之后、但在主要的剩余类检查或群论机制之前。确保零元素直接加入解集，不经过假设非零输入的代码路径。
3. **处理迭代提升中的奇异情况**：在使用 Hensel 提升时，检查当前解处的导数/Jacobian 是否为零。若为零，放弃标准 Newton 更新公式，改为对该层所有可能的提升候选进行暴力枚举（候选数量受素数 p 限制，计算量可控）。
4. **正确组合子问题结果**：将复合模数问题分解为互素的素数幂子问题后，使用中国剩余定理对所有分量解集的笛卡尔积进行重构，确保不遗漏任何根。
5. **编写零元素的显式测试**：包括输入恰好为零、输入为模数的非零倍数、以及导数为零的奇异提升点等测试用例。

### Why This Works
- 零元素检查直接弥补了群论方法的结构性盲区：群论只覆盖可逆元素，显式检查覆盖了剩余的零元素，两者合并即为完整的环上解集。
- Hensel 提升的暴力回退在数学上是正确的：标准提升公式是 Newton 法的 p-adic 版本，要求导数可逆；当导数为零时，解的提升不唯一，但候选数有限（至多 p 个），逐一验证即可穷尽所有分支。
- CRT 笛卡尔积组合是数学上完备的重构方式：它保证了复合模数下的每一个解都恰好对应一组素数幂分量解的组合，不多不少。

## Boundary Cases
- 输入恰好为零（0² ≡ 0 mod n）：最基本的遗漏情况
- 输入为模数的非零倍数（如求 n² ≡ 0 mod p 中 n = kp）：在模运算下等价于零，但原始输入形式上非零
- Hensel 提升中导数为零的奇异点：标准公式失效，需要暴力枚举回退
- 素数幂模数下零解与非零解的交叉：如 x² ≡ 0 mod p² 的解为 x ≡ 0 mod p，包含 p 个解而非 1 个
- 复合模数下某些分量有零解而其他分量有非零解：CRT 组合必须覆盖所有笛卡尔积元素
- 模数为 1 的退化情况：所有元素都是解（解集为全集）

## PR Examples
- sympy__sympy-18199: `nthroot_mod` 函数在计算模 n 的 k 次根时，遗漏了零解。核心算法依赖二次剩余分类和 Hensel 提升，两者都隐式假设非零输入，导致 `nthroot_mod(a**(n % (p-1)), n, p)` 在 `a ≡ 0` 时返回不完整结果。