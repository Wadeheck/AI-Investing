"""Tiny pure-Python linear algebra for the learning engine (feature dim is small).

Covers the two fitters:
  - ridge_solve : batch regularized least squares (offline curation of theta)
  - the matrix ops RLS needs for the online update (dot / matvec / outer / scale)
"""
from __future__ import annotations


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def matvec(M: list[list[float]], v: list[float]) -> list[float]:
    return [dot(row, v) for row in M]


def outer(a: list[float], b: list[float]) -> list[list[float]]:
    return [[x * y for y in b] for x in a]


def identity(n: int, scale: float = 1.0) -> list[list[float]]:
    return [[scale if i == j else 0.0 for j in range(n)] for i in range(n)]


def mat_sub(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[A[i][j] - B[i][j] for j in range(len(A[i]))] for i in range(len(A))]


def mat_scale(A: list[list[float]], s: float) -> list[list[float]]:
    return [[s * x for x in row] for row in A]


def solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve A x = b via Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-15:
            continue
        M[c], M[piv] = M[piv], M[c]
        pivot = M[c][c]
        M[c] = [x / pivot for x in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]


def ridge_solve(X: list[list[float]], y: list[float], reg: float) -> list[float]:
    """theta = argmin ||X theta - y||^2 + reg ||theta||^2  (closed form)."""
    if not X:
        return []
    n = len(X[0])
    A = [[0.0] * n for _ in range(n)]  # XᵀX + reg I
    b = [0.0] * n                       # Xᵀy
    for row, yi in zip(X, y):
        for i in range(n):
            b[i] += row[i] * yi
            Ai = A[i]
            ri = row[i]
            for j in range(n):
                Ai[j] += ri * row[j]
    for i in range(n):
        A[i][i] += reg
    return solve(A, b)
