"""Обучение классификатора под размер решётки: MNIST 16x16 = 256 входов.

Архитектура 256 -> 64 -> 10. Размер входа выбран так, чтобы картинка ровно
ложилась на 256 строк кроссбара. Веса сохраняются в int8 (без потери точности)
вместе с выборкой тестовых картинок — этот же файл читают и Python-скрипты,
и браузерная страница artifacts/crossbar-mnist.html.

Запуск:  python3 analog/train_mnist.py
Требует: torch, numpy, сеть (скачивает MNIST)
"""

import base64, gzip, json, os, struct, urllib.request

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(7)
np.random.seed(7)

BASE = "https://ossci-datasets.s3.amazonaws.com/mnist/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


def grab(name):
    print("качаю", name)
    raw = gzip.decompress(urllib.request.urlopen(BASE + name, timeout=120).read())
    if "images" in name:
        _, n, h, w = struct.unpack(">IIII", raw[:16])
        return np.frombuffer(raw[16:], np.uint8).reshape(n, h, w)
    _, n = struct.unpack(">II", raw[:8])
    return np.frombuffer(raw[8:], np.uint8)


def prep(X):
    t = torch.from_numpy(X.copy()).float().unsqueeze(1) / 255.0
    return F.interpolate(t, size=(16, 16), mode="area").reshape(len(X), 256)


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.f1 = nn.Linear(256, 64)
        self.f2 = nn.Linear(64, 10)

    def forward(self, x):
        return self.f2(F.relu(self.f1(x)))


def quantize_int8(M):
    sc = float(np.abs(M).max())
    return np.clip(np.round(M / sc * 127), -127, 127).astype(np.int8), sc


def main():
    Xtr, ytr = prep(grab("train-images-idx3-ubyte.gz")), torch.from_numpy(grab("train-labels-idx1-ubyte.gz").copy()).long()
    Xte_raw, yte_raw = grab("t10k-images-idx3-ubyte.gz"), grab("t10k-labels-idx1-ubyte.gz")
    Xte, yte = prep(Xte_raw), torch.from_numpy(yte_raw.copy()).long()
    print(f"вход: {tuple(Xtr.shape)} -> решётка 256 строк")

    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    for ep in range(14):
        perm = torch.randperm(len(Xtr))
        for i in range(0, len(perm), 256):
            idx = perm[i:i + 256]
            opt.zero_grad()
            F.cross_entropy(net(Xtr[idx]), ytr[idx]).backward()
            opt.step()
        with torch.no_grad():
            acc = (net(Xte).argmax(1) == yte).float().mean().item()
        print(f"  эпоха {ep + 1:2d}  точность {acc * 100:.2f} %")

    with torch.no_grad():
        W1 = net.f1.weight.T.contiguous().numpy()
        W2 = net.f2.weight.T.contiguous().numpy()
        b1, b2 = net.f1.bias.numpy(), net.f2.bias.numpy()
        acc = (net(Xte).argmax(1) == yte).float().mean().item()

    W1q, s1 = quantize_int8(W1)
    W2q, s2 = quantize_int8(W2)
    with torch.no_grad():
        h = F.relu(Xte @ torch.from_numpy(W1q.astype(np.float32) * s1 / 127) + torch.from_numpy(b1))
        o = h @ torch.from_numpy(W2q.astype(np.float32) * s2 / 127) + torch.from_numpy(b2)
        accq = (o.argmax(1) == yte).float().mean().item()
    print(f"\nточность float {acc * 100:.2f} %   после int8 {accq * 100:.2f} %")

    sel = np.random.choice(len(Xte), 300, replace=False)
    b64 = lambda a: base64.b64encode(a.tobytes()).decode()
    json.dump({
        "arch": [256, 64, 10],
        "accFloat": round(acc * 100, 2), "accInt8": round(accq * 100, 2),
        "W1": b64(W1q), "s1": s1, "b1": b64(b1.astype(np.float32)),
        "W2": b64(W2q), "s2": s2, "b2": b64(b2.astype(np.float32)),
        "imgs": b64((Xte[sel].numpy() * 255).round().clip(0, 255).astype(np.uint8)),
        "labs": b64(yte_raw[sel].astype(np.uint8)),
        "nTest": len(sel),
    }, open(OUT, "w"))
    print(f"{OUT}: {os.path.getsize(OUT) // 1024} КБ")


if __name__ == "__main__":
    main()
