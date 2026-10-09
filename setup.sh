#!/usr/bin/env bash
# Разворачивание окружения с нуля.
#
# Зачем нужен: контейнер облачной сессии Claude Code одноразовый. Диск
# очищается при перезапуске, установленные пакеты не сохраняются. Этот скрипт
# восстанавливает окружение за один проход.
#
# Укажите его в настройке setup script своего окружения — тогда он будет
# выполняться автоматически при старте каждой сессии.
#
# Использование:  ./setup.sh [--minimal]
#   --minimal   только numpy (хватает для analog/eval_analog.py без --full)

set -euo pipefail
cd "$(dirname "$0")"

echo "== установка зависимостей =="
if [[ "${1:-}" == "--minimal" ]]; then
    pip3 install --quiet numpy
    echo "   поставлен numpy"
else
    # Ставим по одному: cadquery весит много, и при падении понятно, что именно упало
    pip3 install --quiet numpy lark anthropic
    echo "   поставлены numpy, lark, anthropic"
    pip3 install --quiet torch        && echo "   поставлен torch"       || echo "   torch не встал"
    pip3 install --quiet cadquery     && echo "   поставлен cadquery (тянет OCCT и vtk)" || echo "   cadquery не встал"
    pip3 install --quiet matplotlib   && echo "   поставлен matplotlib"  || true
fi

echo
echo "== проверка =="
python3 - <<'PY'
mods = ["numpy", "torch", "cadquery", "lark", "anthropic", "matplotlib"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"   {m:<12} {getattr(mod, '__version__', 'есть')}")
    except ImportError:
        print(f"   {m:<12} НЕТ")
PY

echo
echo "Готово. Дальше:"
echo "   python3 analog/eval_analog.py           прогон сети через аналоговую решётку"
echo "   python3 analog/verify_port.py           сверка модели с кодом IBM"
echo "   python3 bench/python_vs_cpp.py          где Python стоит денег"
echo "   python3 analog/train_mnist.py           переобучить сеть с нуля"
