

import math


def _residuals(
    pos: tuple[float, float],
    nodes: list[tuple[float, float]],
    dists: list[float]
) -> list[float]:
    x, y = pos
    return [math.hypot(x - nx, y - ny) - d for (nx, ny), d in zip(nodes, dists)]


def trilaterate(
    nodes: list[tuple[float, float]],
    dists: list[float],
    iters: int = 60,
    tol: float = 1e-9
) -> tuple[float, float, float]:
    """Estimasi koordinat 2D (x, y) dan residual RMS dari minimal 3 titik node acuan."""
    if len(nodes) < 3 or len(nodes) != len(dists):
        raise ValueError("butuh >= 3 node dengan jarak yang cocok")

    x = sum(nx for nx, _ in nodes) / len(nodes)
    y = sum(ny for _, ny in nodes) / len(nodes)

    for _ in range(iters):
        res = _residuals((x, y), nodes, dists)

        jtj00 = jtj01 = jtj11 = jtr0 = jtr1 = 0.0
        for (nx, ny), ri in zip(nodes, res):
            den = math.hypot(x - nx, y - ny)
            if den < 1e-12:
                continue
            j0 = (x - nx) / den
            j1 = (y - ny) / den
            jtj00 += j0 * j0
            jtj01 += j0 * j1
            jtj11 += j1 * j1
            jtr0 += j0 * ri
            jtr1 += j1 * ri

        det = (jtj00 * jtj11) - (jtj01 * jtj01)
        if abs(det) < 1e-15:
            # Sistem kolinear atau singular; hentikan langkah iterasi
            break

        dx = -((jtj11 * jtr0) - (jtj01 * jtr1)) / det
        dy = -((-jtj01 * jtr0) + (jtj00 * jtr1)) / det

        x += dx
        y += dy

        if math.hypot(dx, dy) < tol:
            break

    res = _residuals((x, y), nodes, dists)
    rms = math.sqrt(sum(r * r for r in res) / len(res))
    return (x, y, rms)


def position_error(est: tuple[float, float], truth: tuple[float, float]) -> float:
    """Jarak Euclidean antara estimasi posisi dengan koordinat aktual."""
    return math.hypot(est[0] - truth[0], est[1] - truth[1])
