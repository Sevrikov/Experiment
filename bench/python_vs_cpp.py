"""Где в этом проекте Python действительно стоит денег, а где нет.

Вопрос был: писать ли сразу на C++ или вставлять C++ в Python. Ответ меряется,
а не угадывается. Замер показывает две разные ситуации:

  - геометрия OCC: один вызов уходит в C++ на миллисекунды, накладные расходы
    Python составляют тысячные доли процента -> переписывать нечего
  - поэлементные циклы: чистый Python проигрывает BLAS в сотни раз
    -> здесь и только здесь нужна векторизация или нативный код

Запуск:  python3 bench/python_vs_cpp.py
Требует: numpy; cadquery опционально (без него часть с геометрией пропускается)
"""

import time
import numpy as np


def bench(fn, warmup=3, target=0.3):
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    k = 0
    while time.perf_counter() - t0 < target:
        fn(); k += 1
    return (time.perf_counter() - t0) / k


def us(x):
    return f"{x * 1e6:>11.2f} мкс"


def main():
    t_call = bench(lambda: None)
    print(f"Пустой вызов функции Python: {us(t_call)}   <- накладные расходы\n")

    try:
        from cadquery.occ_impl.shapes import Solid
    except ImportError:
        print("cadquery не установлен — часть с геометрией OCC пропущена\n")
    else:
        print("-" * 72)
        print("ГЕОМЕТРИЯ OCC  (Python только вызывает, работу делает C++)")
        print("-" * 72)
        box = Solid.makeBox(100, 50, 30)
        cyl = Solid.makeCylinder(4.5, 35).translate((50, 25, 0))
        cases = [
            ("makeBox(100,50,30)", lambda: Solid.makeBox(100, 50, 30)),
            ("makeSphere(20)", lambda: Solid.makeSphere(20)),
            ("Volume() BRepGProp", lambda: box.Volume()),
            ("isValid() BRepCheck", lambda: box.isValid()),
            ("cut() булева разность", lambda: box.cut(cyl)),
            ("tessellate(0.5)", lambda: box.tessellate(0.5)),
        ]
        for name, fn in cases:
            t = bench(fn)
            print(f"  {name:<24}{us(t)}   работы C++ в {t / t_call:>8.0f}x больше overhead")
        print()

    print("-" * 72)
    print("ЧИСЛЕННОЕ ЯДРО  (здесь Python решает всё)")
    print("-" * 72)
    for n in (64, 256, 1024):
        W = np.random.rand(n, n)
        v = np.random.rand(n)
        t_np = bench(lambda: W @ v)
        Wl, vl = W.tolist(), v.tolist()

        def pure():
            return [sum(Wl[i][j] * vl[i] for i in range(n)) for j in range(n)]

        reps = max(1, int(0.25 / (n * n * 3e-8)))
        t0 = time.perf_counter()
        for _ in range(reps):
            pure()
        t_py = (time.perf_counter() - t0) / reps
        print(f"  MVM {n:>4}x{n:<4} numpy(BLAS) {us(t_np)}   чистый Python {us(t_py)}"
              f"   разрыв x{t_py / t_np:>7.0f}")

    print("\nВывод: Python бесплатен там, где один вызов уходит в библиотеку")
    print("минимум на ~10 мкс работы, и разорителен в поэлементных циклах.")


if __name__ == "__main__":
    main()
