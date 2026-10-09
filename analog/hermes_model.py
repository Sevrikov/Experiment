"""Модель шума, записи и дрейфа PCM для кристалла IBM HERMES.

Формулы и коэффициенты перенесены дословно из IBM AIHWKit (лицензия MIT),
файл src/aihwkit/inference/noise/hermes.py. Перенос сверен с оригинальным
кодом покоэффициентно: максимальное относительное расхождение 2e-10
(см. verify_port.py).

Коэффициенты откалиброваны IBM на кристалле HERMES Project Chip:
Le Gallo et al., "A 64-core mixed-signal in-memory compute chip based on
phase-change memory for deep neural network inference", Nature Electronics
(2023). Методика статистического моделирования — Nandakumar et al., ICECS 2019.

Единицы: проводимость в мкСм, время в секундах.
"""

import math
import numpy as np

# Два режима кристалла. num_devices=2 — метод MSF (Vasilopoulos et al., TED 2023):
# точнее запись и меньше разброс дрейфа ценой двух ячеек на вес.
DEVICES = {
    2: dict(
        num_devices=2, g_max=20.7, t_0=300.0, t_read=512e-9,
        prog_coeff=[0.16603222, 4.71806468, -8.48101252, 4.68961419],
        prog_ref=20.7,
    ),
    1: dict(
        num_devices=1, g_max=10.35, t_0=200.0, t_read=512e-9,
        prog_coeff=[0.15781817, 2.32443916, -2.16310839, 0.68841818],
        prog_ref=10.35,
    ),
}

_ZERO_CLIP = 1e-7


def prog_sigma(g, d):
    """σ ошибки записи: полином от g/g_max, затем масштаб g_max/ref. [мкСм]"""
    g = np.asarray(g, dtype=np.float64)
    s = np.full_like(g, d["prog_coeff"][0])
    m = np.ones_like(g)
    for c in d["prog_coeff"][1:]:
        m = m * g / d["g_max"]
        s = s + m * c
    return s * (d["g_max"] / d["prog_ref"])


def drift_stats(g, d):
    """Среднее и разброс показателя дрейфа ν. Оба зависят от состояния ячейки."""
    r = np.clip(np.abs(np.asarray(g, dtype=np.float64) / d["g_max"]), _ZERO_CLIP, None)
    L = np.log(r)
    mu = np.where(
        r < 0.0945,
        np.clip(-0.0387 * L - 0.0182, 0.0720, 0.13),
        -0.0436 * r**2 - 0.0126 * r + 0.0736,
    )
    if d["num_devices"] == 1:
        sg = np.where(
            r < 0.3039,
            np.clip(-0.0120 * L - 0.0023, 0.0124, 0.04),
            -0.0165 * r**2 + 0.0116 * r + 0.0104,
        )
    else:
        sg = np.where(
            r < 0.3055,
            np.clip(-0.0117 * L - 0.0057, 0.0091, 0.04),
            -0.0118 * r**2 + 0.0093 * r + 0.0073,
        )
    return mu, sg


def read_q(g, d):
    """Множитель q накопленного шума 1/f. Тоже зависит от состояния."""
    r = np.abs(np.asarray(g, dtype=np.float64)) / d["g_max"]
    L = np.log(np.clip(r, 1e-12, None))
    if d["num_devices"] == 1:
        return np.where(
            r < 0.1591,
            np.clip(-0.0078 * L + 0.0038, 0.0179, 0.04),
            0.0664 * r**3 - 0.1352 * r**2 + 0.0768 * r + 0.0088,
        )
    return np.where(
        r < 0.16,
        np.clip(-0.0117 * L - 0.0069, 0.015, 0.04),
        0.0069 * r**3 - 0.0280 * r**2 + 0.0211 * r + 0.0123,
    )


def read_sigma(g, d, t_inference):
    """σ шума чтения как доля от G. Набирается как sqrt(ln t)."""
    t = t_inference + d["t_0"]
    return read_q(g, d) * math.sqrt(math.log((t + d["t_read"]) / (2 * d["t_read"])))


class DifferentialLayer:
    """Знаковая весовая матрица в дифференциальных парах ячеек.

    Раскладка повторяет SinglePairConductanceConverter из AIHWKit:
    W -> (G+ , G-), где одна ячейка пары всегда на нижней границе.
    Обратно: W = (G+ - G-) / ratio.
    """

    def __init__(self, W, num_devices=2, floor=0.0, programming_error=True, rng=None):
        self.d = DEVICES[num_devices]
        d = self.d
        rng = rng or np.random.default_rng(0)
        self.rng = rng

        g_min = floor * d["g_max"]
        span = d["g_max"] - g_min
        self.ratio = span / max(float(np.abs(W).max()), 1e-12)
        scaled = W * self.ratio

        gp = np.clip(scaled, 0, span) + g_min
        gn = np.clip(-scaled, 0, span) + g_min

        if programming_error:
            gp = np.clip(gp + rng.standard_normal(gp.shape) * prog_sigma(gp, d), 0, None)
            gn = np.clip(gn + rng.standard_normal(gn.shape) * prog_sigma(gn, d), 0, None)

        self.gp, self.gn = gp, gn
        # ν разыгрывается один раз при записи и дальше не меняется
        mu, sg = drift_stats(gp, d)
        self.nu_p = np.abs(mu + sg * rng.standard_normal(gp.shape))
        mu, sg = drift_stats(gn, d)
        self.nu_n = np.abs(mu + sg * rng.standard_normal(gn.shape))
        self.at_time(0.0)

    def at_time(self, t_inference):
        """Применить дрейф и пересчитать σ шума чтения для данного срока."""
        d = self.d
        self.t = t_inference
        if t_inference > 0:
            f = (t_inference + d["t_0"]) / d["t_0"]
            self.dp = self.gp * f ** (-self.nu_p)
            self.dn = self.gn * f ** (-self.nu_n)
        else:
            self.dp, self.dn = self.gp.copy(), self.gn.copy()
        self.sp = read_sigma(self.gp, d, t_inference)
        self.sn = read_sigma(self.gn, d, t_inference)
        # единый цифровой множитель компенсации: отношение исходной суммы к текущей
        a = np.abs(self.gp - self.gn).sum()
        b = np.abs(self.dp - self.dn).sum()
        self.comp = a / b if b > 1e-12 else 1.0
        return self

    def retained(self):
        """Доля сохранившегося веса, в процентах от записанного."""
        a = np.abs(self.gp - self.gn).sum()
        return float(np.abs(self.dp - self.dn).sum() / a * 100) if a > 0 else 100.0

    def calibrate_adc(self, V):
        """Полная шкала АЦП по реальному размаху сигнала.

        Критично: шкала НЕ равна rows*g_max. В дифференциальной схеме выход это
        разность, знаковые веса взаимно гасятся, и настоящий размах на два
        порядка меньше теоретического максимума. Если взять завышенную шкалу,
        АЦП тратит почти все коды на диапазон, куда сигнал не заходит, и
        8-битное квантование рушит точность (проверено: 94 % -> 78 %).
        """
        acc = V @ (self.gp - self.gn)
        self.fs = float(np.abs(acc).max()) * 1.35 or 1.0
        return self.fs

    def mvm(self, V, bits=8, read_noise=True, compensate=False):
        """Матрично-векторное умножение через решётку, с АЦП на выходе столбца."""
        ga, gb = self.dp, self.dn
        if read_noise:
            ga = ga + ga * self.sp * self.rng.standard_normal(ga.shape)
            gb = gb + gb * self.sn * self.rng.standard_normal(gb.shape)
        acc = V @ np.clip(ga, 0, None) - V @ np.clip(gb, 0, None)
        lv = 2**bits - 1
        q = np.round(np.clip(acc / self.fs, -1, 1) * lv) / lv
        return q * self.fs * (self.comp if compensate else 1.0) / self.ratio
