"""Сверка нашего порта модели HERMES с оригинальным кодом IBM AIHWKit.

Клонирует репозиторий IBM, импортирует их HermesNoiseModel и сравнивает
детерминированные части (σ записи, ν дрейфа, множитель шума чтения) с нашей
реализацией в hermes_model.py.

Запуск:  python3 analog/verify_port.py
Требует: torch, numpy, git
"""

import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermes_model as hm

AIHWKIT = os.environ.get("AIHWKIT_PATH", "/tmp/aihwkit")
TOLERANCE = 1e-9


def ensure_aihwkit():
    if not os.path.isdir(os.path.join(AIHWKIT, "src")):
        print(f"клонирую IBM/aihwkit в {AIHWKIT} …")
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/IBM/aihwkit.git", AIHWKIT],
            check=True, capture_output=True,
        )
    sys.path.insert(0, os.path.join(AIHWKIT, "src"))


def main():
    ensure_aihwkit()
    import torch
    from aihwkit.inference.noise.hermes import HermesNoiseModel

    worst = {}
    for num_devices in (2, 1):
        d = hm.DEVICES[num_devices]
        ref = HermesNoiseModel(num_devices=num_devices)

        assert ref.g_max == d["g_max"], f"g_max: {ref.g_max} != {d['g_max']}"
        assert ref.t_0 == d["t_0"], f"t_0: {ref.t_0} != {d['t_0']}"
        assert ref.t_read == d["t_read"], f"t_read: {ref.t_read} != {d['t_read']}"
        assert list(ref.prog_coeff) == d["prog_coeff"], "prog_coeff расходится"

        gs = np.array([0.05, 0.2, 1.0, 2.0, 5.0, 10.0, d["g_max"] * 0.75, d["g_max"]])

        # σ записи — считаем оригинальным кодом IBM
        gt = torch.tensor(gs, dtype=torch.float64)
        mat, sp = 1.0, ref.prog_coeff[0]
        for c in ref.prog_coeff[1:]:
            mat = mat * gt / ref.g_max
            sp = sp + mat * c
        sp = (sp * (ref.g_max / ref.prog_coeff_g_max_reference)).numpy()

        mine = hm.prog_sigma(gs, d)
        rel = np.max(np.abs(sp - mine) / np.maximum(np.abs(sp), 1e-30))
        worst[f"{num_devices} устр. · σ записи"] = rel

        # ν и шум чтения — ветвящиеся функции, воспроизводим их по коду IBM
        for label, ours, theirs in [
            ("ν среднее", hm.drift_stats(gs, d)[0], _ref_mu(gs, d)),
            ("ν разброс", hm.drift_stats(gs, d)[1], _ref_sg(gs, d)),
            ("шум чтения", hm.read_sigma(gs, d, 3.156e7), _ref_read(gs, d, 3.156e7)),
        ]:
            rel = np.max(np.abs(theirs - ours) / np.maximum(np.abs(theirs), 1e-30))
            worst[f"{num_devices} устр. · {label}"] = rel

    print("\nМаксимальное относительное расхождение с кодом IBM:\n")
    ok = True
    for k, v in worst.items():
        good = v < TOLERANCE
        ok &= good
        print(f"  {k:<28} {v:.3e}   {'совпадает' if good else 'РАСХОЖДЕНИЕ'}")
    print("\nИТОГ:", "порт верен" if ok else "ЕСТЬ РАСХОЖДЕНИЯ")
    return 0 if ok else 1


# Ниже — ветви из hermes.py IBM, выписанные независимо от нашего модуля,
# чтобы сверка не сравнивала код сам с собой.
def _ref_mu(g, d):
    r = np.clip(np.abs(g / d["g_max"]), 1e-7, None); L = np.log(r)
    return np.where(r < 0.0945, np.clip(-0.0387 * L - 0.0182, 0.0720, 0.13),
                    -0.0436 * r**2 - 0.0126 * r + 0.0736)


def _ref_sg(g, d):
    r = np.clip(np.abs(g / d["g_max"]), 1e-7, None); L = np.log(r)
    if d["num_devices"] == 1:
        return np.where(r < 0.3039, np.clip(-0.0120 * L - 0.0023, 0.0124, 0.04),
                        -0.0165 * r**2 + 0.0116 * r + 0.0104)
    return np.where(r < 0.3055, np.clip(-0.0117 * L - 0.0057, 0.0091, 0.04),
                    -0.0118 * r**2 + 0.0093 * r + 0.0073)


def _ref_read(g, d, t_inf):
    r = np.abs(g) / d["g_max"]; L = np.log(np.clip(r, 1e-12, None))
    if d["num_devices"] == 1:
        q = np.where(r < 0.1591, np.clip(-0.0078 * L + 0.0038, 0.0179, 0.04),
                     0.0664 * r**3 - 0.1352 * r**2 + 0.0768 * r + 0.0088)
    else:
        q = np.where(r < 0.16, np.clip(-0.0117 * L - 0.0069, 0.015, 0.04),
                     0.0069 * r**3 - 0.0280 * r**2 + 0.0211 * r + 0.0123)
    t = t_inf + d["t_0"]
    return q * math.sqrt(math.log((t + d["t_read"]) / (2 * d["t_read"])))


if __name__ == "__main__":
    sys.exit(main())
