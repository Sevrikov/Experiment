"""Прогон обученной сети через аналоговую решётку: деградация и рычаги.

Две части:
  1) ход точности во времени на одной записанной матрице (парные замеры)
  2) сравнение режимов работы, усреднённое по нескольким разыгрываниям записи

Важно про методику: каждое новое «программирование» матрицы заново разыгрывает
ошибку записи и показатель ν, поэтому режимы НЕЛЬЗЯ сравнивать между разными
вызовами build(). Сравнение всегда парное — на одной и той же матрице.

Запуск:  python3 analog/eval_analog.py [--full]
         --full  скачать все 10 000 тестовых картинок MNIST (иначе 300 из model.json)
"""

import argparse, base64, gzip, json, os, struct, sys, urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hermes_model import DifferentialLayer

HERE = os.path.dirname(os.path.abspath(__file__))
YEAR = 3.156e7
TIMES = [("сразу", 0), ("1 час", 3600), ("1 сутки", 86400), ("1 месяц", 2.63e6),
         ("1 год", YEAR), ("10 лет", 3.156e8)]


def load_model():
    M = json.load(open(os.path.join(HERE, "model.json")))
    d = lambda k, dt, sh: np.frombuffer(base64.b64decode(M[k]), dt).reshape(sh)
    return dict(
        W1=d("W1", np.int8, (256, 64)).astype(np.float64) * M["s1"] / 127,
        W2=d("W2", np.int8, (64, 10)).astype(np.float64) * M["s2"] / 127,
        b1=d("b1", np.float32, (64,)).astype(np.float64),
        b2=d("b2", np.float32, (10,)).astype(np.float64),
        X=d("imgs", np.uint8, (M["nTest"], 256)).astype(np.float64) / 255,
        y=d("labs", np.uint8, (M["nTest"],)).astype(np.int64),
    )


def load_full_testset():
    import torch, torch.nn.functional as F
    base = "https://ossci-datasets.s3.amazonaws.com/mnist/"
    def grab(n):
        raw = gzip.decompress(urllib.request.urlopen(base + n, timeout=120).read())
        if "images" in n:
            _, c, h, w = struct.unpack(">IIII", raw[:16])
            return np.frombuffer(raw[16:], np.uint8).reshape(c, h, w)
        _, c = struct.unpack(">II", raw[:8])
        return np.frombuffer(raw[8:], np.uint8)
    Xr = grab("t10k-images-idx3-ubyte.gz")
    y = grab("t10k-labels-idx1-ubyte.gz").astype(np.int64)
    X = F.interpolate(torch.from_numpy(Xr.copy()).float().unsqueeze(1) / 255,
                      size=(16, 16), mode="area").reshape(len(Xr), 256).numpy().astype(np.float64)
    return X, y


def build(m, X, num_devices=2, floor=0.0, programming_error=True, seed=0):
    rng = np.random.default_rng(seed)
    L1 = DifferentialLayer(m["W1"], num_devices, floor, programming_error, rng)
    L2 = DifferentialLayer(m["W2"], num_devices, floor, programming_error, rng)
    # шкалы АЦП снимаются по реальному размаху сигнала, слой за слоем
    L1.calibrate_adc(X[:64])
    h = np.maximum(X[:64] @ (L1.gp - L1.gn) / L1.ratio + m["b1"], 0)
    L2.calibrate_adc(h)
    return L1, L2


def predict(m, X, L1, L2, t, bits=8, read_noise=True, compensate=False,
            layer2_analog=True, chunk=2000):
    L1.at_time(t); L2.at_time(t)
    out = []
    for i in range(0, len(X), chunk):
        V = X[i:i + chunk]
        h = np.maximum(L1.mvm(V, bits, read_noise, compensate) + m["b1"], 0)
        o = (L2.mvm(h, bits, read_noise, compensate) if layer2_analog else h @ m["W2"]) + m["b2"]
        out.append(o.argmax(1))
    return np.concatenate(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="все 10 000 картинок вместо 300")
    ap.add_argument("--seeds", type=int, default=3, help="разыгрываний записи для рычагов")
    a = ap.parse_args()

    m = load_model()
    if a.full:
        m["X"], m["y"] = load_full_testset()
    X, y = m["X"], m["y"]
    print(f"тестовый набор: {len(X)} картинок 16x16")

    ref = (np.maximum(X @ m["W1"] + m["b1"], 0) @ m["W2"] + m["b2"]).argmax(1)
    print(f"цифровой эталон: {(ref == y).mean() * 100:.2f} %\n")

    print("=" * 62)
    print("ХОД ДЕГРАДАЦИИ · 2 устройства на вес, 8 бит, одна матрица")
    print("=" * 62)
    print(f"{'срок':<12}{'без комп.':>12}{'с комп.':>12}{'сохранено G':>14}")
    L1, L2 = build(m, X, seed=42)
    by_time = {}
    for lab, t in TIMES:
        p0 = predict(m, X, L1, L2, t, compensate=False)
        p1 = predict(m, X, L1, L2, t, compensate=True)
        by_time[lab] = p0
        print(f"{lab:<12}{(p0 == y).mean() * 100:>11.2f}%{(p1 == y).mean() * 100:>11.2f}%"
              f"{L1.retained():>13.1f}%")

    print("\n" + "=" * 62)
    print(f"РЫЧАГИ · парно на одной матрице, {a.seeds} разыгрываний, срок 1 год")
    print("=" * 62)

    def paired(variants, **build_kw):
        acc = {k: [] for k in variants}
        for s in range(a.seeds):
            L1, L2 = build(m, X, seed=100 + s, **build_kw)
            for k, kw in variants.items():
                acc[k].append((predict(m, X, L1, L2, YEAR, **kw) == y).mean() * 100)
        return {k: (float(np.mean(v)), float(np.std(v))) for k, v in acc.items()}

    def show(title, res):
        print(f"\n{title}")
        for k, (mu, sd) in res.items():
            print(f"   {k:<40}{mu:>7.2f}% ± {sd:.2f}")

    show("Компенсация дрейфа, 2 устройства:",
         paired({"без компенсации": dict(compensate=False), "с компенсацией": dict(compensate=True)}))
    show("Компенсация дрейфа, 1 устройство:",
         paired({"без компенсации": dict(compensate=False), "с компенсацией": dict(compensate=True)},
                num_devices=1))
    print("\nЧисло устройств на вес (с компенсацией):")
    for nd in (1, 2):
        mu, sd = paired({"x": dict(compensate=True)}, num_devices=nd)["x"]
        print(f"   {nd} устройство(а)                          {mu:>7.2f}% ± {sd:.2f}")
    print("\nНижний порог G (с компенсацией) — в дифф. схеме он ВРЕДИТ:")
    for f in (0.0, 0.1, 0.2, 0.3):
        mu, sd = paired({"x": dict(compensate=True)}, floor=f)["x"]
        print(f"   порог {int(f * 100):>2} %                              {mu:>7.2f}% ± {sd:.2f}")
    show("Разрядность АЦП (с компенсацией):",
         paired({f"{b} бит": dict(bits=b, compensate=True) for b in (3, 4, 5, 6, 8, 10, 12)}))
    show("Вклад источников шума (с компенсацией):",
         paired({"всё включено": dict(compensate=True),
                 "без шума чтения": dict(compensate=True, read_noise=False),
                 "второй слой цифровой": dict(compensate=True, layer2_analog=False)}))

    print("\n" + "=" * 62)
    print("ТОЧНОСТЬ ПО ЦИФРАМ · что ломается первым")
    print("=" * 62)
    cols = ["сразу", "1 месяц", "1 год", "10 лет"]
    print(f"{'цифра':<8}" + "".join(f"{c:>11}" for c in cols))
    for dg in range(10):
        row = f"{dg:<8}"
        for c in cols:
            p, mask = by_time[c], (y == dg)
            row += f"{(p[mask] == dg).mean() * 100:>10.1f}%"
        print(row)

    print("\nТоп подмен через 10 лет:")
    from collections import Counter
    p = by_time["10 лет"]; bad = p != y
    cnt = Counter(zip(y[bad].tolist(), p[bad].tolist()))
    for (t_, pp), c in cnt.most_common(6):
        print(f"   {t_} принято за {pp}   {c:>4} раз   {c / bad.sum() * 100:>5.1f} % ошибок")


if __name__ == "__main__":
    main()
