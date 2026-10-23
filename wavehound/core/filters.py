"""Filter perataan sinyal RSSI: Exponential Moving Average (EMA) dan Kalman 1D."""


class EMA:
    """Exponential Moving Average untuk perataan derau cepat di level pemindai."""

    def __init__(self, alpha: float = 0.25):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha harus dalam (0, 1]")
        self.alpha = alpha
        self.value: float | None = None

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value = (self.alpha * x) + ((1.0 - self.alpha) * self.value)
        return self.value

    def reset(self) -> None:
        self.value = None


class Kalman1D:
    """Filter Kalman 1-dimensi dengan bobot koreksi adaptif terhadap noise pengukuran.

    Model:
        x_k = x_{k-1} + w    (w ~ N(0, process_var))
        z_k = x_k + v        (v ~ N(0, meas_var))
    """

    def __init__(
        self,
        process_var: float = 0.05,
        meas_var: float = 4.0,
        x0: float = 0.0,
        p0: float = 10.0
    ):
        self.q = process_var
        self.r = meas_var
        self.x = x0
        self.p = p0

    def update(self, z: float) -> float:
        p_pred = self.p + self.q
        k = p_pred / (p_pred + self.r)
        self.x = self.x + (k * (z - self.x))
        self.p = (1.0 - k) * p_pred
        return self.x

    def reset(self, x0: float = 0.0, p0: float = 10.0) -> None:
        self.x = x0
        self.p = p0
