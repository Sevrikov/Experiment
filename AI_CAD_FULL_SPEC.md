# AI-CAD Multiagent System v2.0 — Полная документация

> Собрано из загруженных файлов сессии: `СЛУЖЕБНАЯ_ЗАПИСКА.docx`,
> `CLAUDE_CODE_PACKAGE.md`, `aicad-diagram.jsx`, `ai_cad_tz_v2.md`

---

## ЧАСТЬ 0 — СЛУЖЕБНАЯ ЗАПИСКА

**КОМУ:** Claude Code (агент разработки)  
**ОТ КОГО:** Claude (claude.ai, сессия архитектурного ревью)  
**ДАТА:** Апрель 2026  
**ТЕМА:** Передача архитектурных материалов по проекту AI-CAD Multiagent System v2.0  
**ПРИОРИТЕТ:** ВЫСОКИЙ — старт разработки

### 1. Цель настоящей записки

Настоящая служебная записка передаёт Claude Code полный пакет архитектурных материалов, необходимых для начала разработки AI-CAD Multiagent System v2.0. Система позволяет пользователям описывать 3D-геометрию на естественном языке — LLM транслирует описание в формальный DSL, который компилируется в операции CAD-ядра.

### 2. Архитектура — 10 компонентов, 3 фазы

| Фаза | Компоненты | Задача |
|------|------------|--------|
| Фаза 1 — MVP | T1, T3, T6 | LLM Planner + DSL Parser + Scene Graph. Базовый цикл без валидации |
| Фаза 2 — Агенты | T2, T4, T5, T9 | Hermes Swarm + OCC Kernel + BRepCheck Validator + Iteration Controller |
| Фаза 3 — Vision | T7, T8, T10 | VTK Renderer + Claude Vision Evaluator + Export STL/STEP/OBJ |

### 3. Ключевые технические решения (зафиксированы, не пересматриваются)

- **CAD-ядро:** OpenCASCADE Technology (OCCT 7.x) через pythonocc-core. Промышленный B-Rep, нативный STEP-экспорт, BRepCheck для валидации.
- **LLM:** claude-sonnet-4-20250514, temperature=0 для детерминизма планирования.
- **Хранилище состояния:** Redis 7.x + JSON. BRep-данные хранятся как Binary keys, отдельно от JSON-графа сцены.
- **Агенты:** stateless Python asyncio процессы, общение через Redis Streams. Всё состояние — в Scene Graph.
- **Рендеринг:** VTK с offscreen-рендером (OSMesa CPU / EGL GPU). НЕ Three.js — система headless серверная.
- **Формальная грамматика DSL:** Lark (Python), Context-Free Grammar. Парсер возвращает AST или исключение.

### 4. Критические ограничения архитектуры (ОБЯЗАТЕЛЬНЫ)

1. Boolean Agent ОБЯЗАН запускать BRepCheck после каждой операции. confidence=0.0 при невалидном результате.
2. Vision Evaluator оценивает ТОЛЬКО семантику (форма ≈ намерение). Числовую точность проверяет исключительно Geometry Validator (T5).
3. Renderer НЕ видит внутренние полости и поднутрения — только геометрическая валидация через T5.
4. Откат к предыдущему состоянию = восстановление снапшота из Redis. Никогда не пересчитывать геометрию заново.
5. Если Iteration Controller фиксирует 3+ итерации без прогресса — автоматический триггер Debug Agent, не завершение с ошибкой.

### 5. Порядок реализации (рекомендуемый)

```
Sprint 1: T6 (Redis schema) + T3 (DSL Parser) + T4 (OCC Adapter) — фундамент
Sprint 2: T1 (LLM Planner) + T2 (только Geometry Agent) + T5 (Validator) — MVP цикл
Sprint 3: T2 Boolean + Transform + Debug агенты
Sprint 4: T7 (Renderer) + T8 (Vision) + T9 (Iteration Controller) + T10 (Export)
```

---

## ЧАСТЬ 1 — ТЕХНИЧЕСКОЕ ЗАДАНИЕ v2.0

> Источник: `ai_cad_tz_v2.md` — финальная редакция после архитектурного ревью

### 1. Цель системы и контекст

#### 1.1 Назначение

Система позволяет пользователю описывать 3D-геометрию на естественном языке. LLM транслирует описание в формальный DSL, который компилируется в операции CAD-ядра. Результат верифицируется геометрически и семантически, после чего система выдаёт валидный экспортируемый 3D-объект (STL, STEP, OBJ).

#### 1.2 Целевые пользователи

- Инженеры-конструкторы, не имеющие опыта работы с CAD-системами
- Дизайнеры продуктов на этапе концептуального прототипирования
- Исследователи, которым нужна быстрая геометрическая валидация идей

#### 1.3 Ограничения области применения (Scope)

Система **не является** заменой полноценным CAD-системам (Fusion 360, SolidWorks). Она покрывает класс задач: **твёрдотельное параметрическое моделирование из примитивов** с булевыми операциями. Поверхностное моделирование, сборки, чертежи — вне scope v1.

---

### 2. Ключевые архитектурные гипотезы

#### H1: LLM способен надёжно транслировать естественный язык в DSL
**Утверждение:** Claude (claude-sonnet-4) при наличии формальной грамматики DSL в system prompt генерирует синтаксически корректный DSL в >90% случаев для задач из целевого класса.  
**Критерий фальсификации:** Если после 500 тестовых запросов точность ниже 85% — необходим fallback-механизм с пошаговым уточнением через диалог.  
**Проверка:** Автоматический парсер DSL возвращает success/error для каждого сгенерированного фрагмента.

#### H2: Семантическая оценка по изображению достаточна для навигации итераций
**Утверждение:** LLM, анализируя 4 вида рендера (front/top/side/iso), способен определить соответствие цели и сформулировать корректирующую DSL-команду.  
**Критерий фальсификации:** Если система зацикливается на одной ошибке более 3 итераций без прогресса — нужна дополнительная аналитика.  
**Проверка:** Логирование convergence rate по классам задач.

#### H3: OpenCASCADE достаточен для целевого класса геометрии
**Утверждение:** Примитивы + булевы операции + трансформации покрывают 80% запросов целевых пользователей.  
**Критерий фальсификации:** User research покажет, что >40% запросов требуют операций вне этого множества.

#### H4: Агентная декомпозиция ускоряет обработку сложных задач
**Утверждение:** Swarm даёт лучшее качество по сравнению с одним агентом для задач с 5+ операциями.  
**Приоритет:** Проверяется только после MVP.

---

### 3. Финальная архитектура

```
┌─────────────────────────────────────────────────────┐
│                  Пользователь                        │
│         "Создай корпус для электроники               │
│          100x50x30мм с отверстием под разъём"        │
└──────────────────────┬──────────────────────────────┘
                       │ Естественный язык
                       ▼
┌─────────────────────────────────────────────────────┐
│           LLM Planner (Claude Sonnet 4)              │
│  • Разбор намерения пользователя                     │
│  • Генерация плана операций                          │
│  • Выбор агентов и последовательности                │
│  • Семантическая оценка результата                   │
└──────────────────────┬──────────────────────────────┘
                       │ Structured Plan (JSON)
                       ▼
┌─────────────────────────────────────────────────────┐
│         Hermes Agent Swarm (Python, asyncio)         │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │  Geometry   │ │   Boolean    │ │  Transform   │  │
│  │   Agent     │ │    Agent     │ │    Agent     │  │
│  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘  │
│         └───────────────┼────────────────┘           │
│                         │ DSL Commands                │
└─────────────────────────┼───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│           Formal DSL Parser (Python / Lark)          │
│  • Лексический анализ                                │
│  • Синтаксический анализ → AST                       │
│  • Семантическая валидация типов                     │
└──────────────────────┬──────────────────────────────┘
                       │ AST
                       ▼
┌─────────────────────────────────────────────────────┐
│       Geometry Kernel Adapter (Python-OCC)           │
│  • Трансляция AST → OpenCASCADE API вызовы           │
│  • Выполнение геометрических операций                │
│  • Управление Shape Registry                         │
└──────────────────────┬──────────────────────────────┘
                       │ OCC Shape objects
                       ▼
┌─────────────────────────────────────────────────────┐
│         Geometry Validation Layer                    │
│  • Manifold check (BRepCheck_Analyzer)               │
│  • Volume consistency (BRepGProp)                    │
│  • Degeneracy detection                              │
│  • Boolean result non-empty check                    │
└──────────────────────┬──────────────────────────────┘
                       │ Validated Shape / Error Report
                       ▼
┌─────────────────────────────────────────────────────┐
│         Scene Graph Store (Redis + JSON)             │
│  • Граф объектов сцены                               │
│  • История операций (append-only log)                │
│  • Снапшоты для отката                               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│         Renderer (VTK + offscreen / matplotlib)      │
│  • 4 камеры: front / top / side / isometric          │
│  • Offscreen рендер (OSMesa / EGL)                   │
│  • Экспорт PNG для vision feedback                   │
└──────────────────────┬──────────────────────────────┘
                       │ 4x PNG
                       ▼
┌─────────────────────────────────────────────────────┐
│         Vision Evaluator (Claude Vision API)         │
│  • Семантическое сравнение с целью                   │
│  • Выявление грубых расхождений                      │
│  • Формирование корректирующего запроса              │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│         Iteration Controller                         │
│  • Бюджет итераций (max N)                           │
│  • Критерий сходимости                               │
│  • Стратегия выхода                                  │
└──────────────────────┬──────────────────────────────┘
                       │ Финальный результат
                       ▼
              STL / STEP / OBJ файл
```

---

### 4. Компоненты системы — детальная спецификация

#### T1 — LLM Planner (Claude Sonnet 4)

**Роль:** Оркестратор и семантический судья. Не выполняет числовые вычисления.

**Входные данные:**
- Текстовый запрос пользователя
- Текущее состояние сцены (Scene Graph Summary — краткий JSON)
- Список доступных DSL-команд (из grammar.lark)
- История итераций (последние N шагов)

**Выходные данные — Structured Plan (JSON):**
```json
{
  "intent_summary": "Корпус 100x50x30мм с вырезом под разъём USB-C",
  "operations": [
    {
      "agent": "geometry",
      "command": "create_box",
      "params": {"w": 100, "h": 50, "d": 30},
      "output_id": "obj_001"
    },
    {
      "agent": "geometry",
      "command": "create_cylinder",
      "params": {"r": 4.5, "h": 10},
      "output_id": "obj_002"
    },
    {
      "agent": "transform",
      "command": "translate",
      "params": {"obj": "obj_002", "x": 50, "y": 25, "z": 30},
      "output_id": "obj_002"
    },
    {
      "agent": "boolean",
      "command": "subtract",
      "params": {"base": "obj_001", "tool": "obj_002"},
      "output_id": "obj_003"
    }
  ],
  "expected_result": "Прямоугольный корпус с цилиндрическим отверстием в центре верхней грани"
}
```

**Ограничения роли:**
- LLM НЕ вычисляет точные координаты пересечений
- LLM НЕ принимает решения о топологической корректности
- LLM НЕ интерпретирует геометрические ошибки ядра — только семантические расхождения с целью

**Технология:** Anthropic API, `claude-sonnet-4-20250514`, temperature=0.

---

#### T2 — Hermes Agent Swarm

**Архитектура агентов:** Каждый агент — независимый Python-процесс, общающийся через Redis Streams. Агенты stateless — всё состояние хранится в Scene Graph.

**Интерфейс агента:**
```python
class BaseAgent:
    agent_id: str
    domain: Literal["geometry", "boolean", "transform", "debug"]

    async def process(self, task: AgentTask) -> AgentResult:
        ...

@dataclass
class AgentTask:
    task_id: str
    command: str
    params: dict
    scene_snapshot: dict
    confidence_threshold: float = 0.8

@dataclass
class AgentResult:
    task_id: str
    success: bool
    output_id: str | None
    error: GeometryError | None
    confidence: float        # 0.0–1.0
    patch: ScenePatch
```

**Geometry Agent:** `create_box`, `create_sphere`, `create_cylinder`, `create_cone`, `create_torus`  
**Boolean Agent:** `union`, `subtract`, `intersect` — ОБЯЗАН запускать BRepCheck после каждой операции  
**Transform Agent:** `translate`, `rotate`, `scale`, `mirror`  
**Debug Agent:** Активируется при `success=False`. ShapeFix pipeline, human-readable описание для LLM Planner.

**Разрешение конфликтов при параллельном выполнении:**
1. Каждый агент применяет патч к своей копии снапшота
2. Оркестратор применяет патчи последовательно в порядке топологической зависимости
3. При конфликте (два агента изменяют один объект) — откат к снапшоту, последовательное выполнение

---

#### T3 — Formal DSL Parser

**Свойства:**
- Контекстно-свободная грамматика (Context-Free Grammar)
- Парсер на базе библиотеки **Lark** (Python)
- Строгая типизация параметров
- Явные единицы измерения (мм по умолчанию)

---

#### T4 — Geometry Kernel Adapter

**Технология:** `pythonocc-core` (Python-биндинги для OCCT 7.x) / `cadquery-ocp`

**Shape Registry:**
```python
class ShapeRegistry:
    _shapes: dict[str, TopoDS_Shape]

    def register(self, obj_id: str, shape: TopoDS_Shape) -> None: ...
    def get(self, obj_id: str) -> TopoDS_Shape: ...
    def serialize(self, obj_id: str) -> bytes: ...  # BRep bytes для Redis
```

---

#### T5 — Geometry Validation Layer

Выполняется **после каждой операции** до записи в Scene Graph.

```python
class GeometryValidator:
    def validate(self, shape: TopoDS_Shape) -> ValidationResult:
        checks = [
            self._check_not_null(shape),
            self._check_manifold(shape),
            self._check_volume_positive(shape),
            self._check_no_degenerate_edges(shape),
            self._check_closed_shell(shape),
        ]
        errors = [c for c in checks if not c.passed]
        return ValidationResult(passed=len(errors)==0, errors=errors)
```

**Классификация ошибок:**

| Код | Описание | Стратегия восстановления |
|-----|----------|--------------------------|
| `NULL_SHAPE` | Пустой результат операции | Откат, Debug Agent |
| `NON_MANIFOLD` | Невалидная топология | ShapeFix → повтор |
| `ZERO_VOLUME` | Вырожденная геометрия | Откат, пересмотр параметров |
| `DEGENERATE_EDGE` | Вырожденные рёбра | ShapeFix.FixSmallEdges |
| `OPEN_SHELL` | Незамкнутая оболочка | ShapeFix.FixShell |

---

#### T6 — Scene Graph Store

**Технология:** Redis 7.x + JSON-сериализация (SQLite для MVP)

**Структура данных:**
```json
{
  "session_id": "sess_abc123",
  "version": 7,
  "objects": {
    "obj_001": {
      "type": "box",
      "params": {"w": 100, "h": 50, "d": 30},
      "brep_key": "brep:sess_abc123:obj_001",
      "valid": true,
      "created_at_version": 1
    },
    "obj_003": {
      "type": "boolean_subtract",
      "inputs": ["obj_001", "obj_002"],
      "brep_key": "brep:sess_abc123:obj_003",
      "valid": true,
      "created_at_version": 4
    }
  },
  "active_object": "obj_003",
  "history": [
    {"version": 1, "operation": "create_box", "params": {"w":100,"h":50,"d":30}, "output": "obj_001"},
    {"version": 2, "operation": "create_cylinder", "params": {"r":4.5,"h":10}, "output": "obj_002"},
    {"version": 3, "operation": "translate", "params": {"obj":"obj_002","x":50,"y":25,"z":30}, "output": "obj_002"},
    {"version": 4, "operation": "subtract", "params": {"base":"obj_001","tool":"obj_002"}, "output": "obj_003"}
  ],
  "snapshots": [1, 4]
}
```

**Принципы:**
- История — append-only лог, никогда не изменяется
- BRep-данные хранятся отдельно (Redis Binary key)
- Снапшоты создаются после каждой успешной валидированной операции
- Откат = восстановление из снапшота без пересчёта

**Rollback:**
```python
def rollback_to_snapshot(session_id: str, target_version: int) -> None:
    snapshot = redis.get(f"snapshot:{session_id}:{target_version}")
    redis.set(f"scene:{session_id}", snapshot)
    # BRep более новых версий помечаются как orphaned, GC удаляет через TTL
```

---

#### T7 — Renderer

**Технология:** VTK с offscreen рендерингом (OSMesa CPU / EGL GPU)

**4 фиксированных камеры:**
```python
CAMERAS = {
    "front":      {"position": (0, -distance, 0),  "up": (0, 0, 1)},
    "top":        {"position": (0, 0, distance),    "up": (0, 1, 0)},
    "side":       {"position": (distance, 0, 0),    "up": (0, 0, 1)},
    "isometric":  {"position": (d, -d, d),          "up": (0, 0, 1)},
}
```

**Параметры рендера:** 512×512 px, PNG, Phong shading, нейтральный серый, ambient light.

**Явное ограничение:** Renderer не видит внутренние полости и поднутрения. Для них — только геометрический валидатор T5.

---

#### T8 — Vision Evaluator

**Технология:** Claude Vision API (claude-sonnet-4, multimodal)

**Разграничение ответственности:**

| Что делает | Что НЕ делает |
|---|---|
| "Форма похожа на корпус электроники" | Измеряет размеры |
| "Есть ли отверстие на верхней грани" | Проверяет топологию |
| "Соответствует ли форма запросу" | Верифицирует геометрическую точность |
| Формулирует корректирующий DSL | Вычисляет координаты |

**Промпт-шаблон:**
```
System: Ты — эксперт по семантической оценке 3D-геометрии.
Тебе показаны 4 вида 3D-объекта.
Твоя задача: определить, соответствует ли объект описанию цели.
НЕ оценивай числовую точность. Оценивай только форму, топологию и соответствие намерению.

Цель пользователя: {intent_summary}
Ожидаемый результат: {expected_result}

Ответь в JSON:
{
  "semantic_match": true/false,
  "confidence": 0.0–1.0,
  "issues": ["список семантических расхождений"],
  "correction_hint": "что нужно изменить в DSL для исправления"
}
```

---

#### T9 — Iteration Controller

```python
@dataclass
class IterationConfig:
    max_iterations: int = 5
    max_plan_retries: int = 3
    max_parse_retries: int = 3
    operation_timeout_ms: int = 10000
    total_session_timeout_s: int = 120
    convergence_threshold: float = 0.85

def should_stop(iteration_state: IterationState) -> StopDecision:
    if iteration_state.current_iteration >= config.max_iterations:
        return StopDecision(stop=True, reason="BUDGET_EXHAUSTED")
    if iteration_state.vision_confidence >= config.convergence_threshold:
        return StopDecision(stop=True, reason="CONVERGED")
    if iteration_state.consecutive_same_error >= 2:
        return StopDecision(stop=True, reason="STUCK_IN_LOOP")
    if time.time() - iteration_state.start_time > config.total_session_timeout_s:
        return StopDecision(stop=True, reason="TIMEOUT")
    return StopDecision(stop=False, reason=None)
```

**Критерий сходимости:**
- Успех: Vision confidence >= 0.85 И Geometry valid = True
- Частичный успех: Vision confidence >= 0.6 И Geometry valid = True (с предупреждением)
- Неудача: Исчерпан бюджет ИЛИ timeout

**Результат при досрочной остановке:**
```json
{
  "status": "partial_success",
  "stop_reason": "BUDGET_EXHAUSTED",
  "best_iteration": 3,
  "vision_confidence": 0.72,
  "geometry_valid": true,
  "output_file": "result_iter3.stl",
  "user_message": "Система не достигла полного соответствия за 5 итераций. Лучший результат — итерация 3 (72% соответствие). Экспортирован для ручной проверки."
}
```

---

#### T10 — Export

**Технология:** OCC StlAPI_Writer · STEPControl · BRepMesh tessellation  
**Входные данные:** `active_object TopoDS_Shape` из ShapeRegistry  
**Выходные данные:** `.stl` / `.step` / `.obj` файл  
**Только для финального объекта** (`active_object` из Scene Graph)

---

### 5. Формальная грамматика DSL

#### 5.1 EBNF-грамматика

```ebnf
program        ::= statement+
statement      ::= command NEWLINE
command        ::= create_cmd | boolean_cmd | transform_cmd | query_cmd

(* Создание примитивов *)
create_cmd     ::= "create_box"      id_assign params_box
                 | "create_sphere"   id_assign params_sphere
                 | "create_cylinder" id_assign params_cylinder
                 | "create_cone"     id_assign params_cone
                 | "create_torus"    id_assign params_torus

params_box       ::= "w=" number "h=" number "d=" number
params_sphere    ::= "r=" number
params_cylinder  ::= "r=" number "h=" number
params_cone      ::= "r1=" number "r2=" number "h=" number
params_torus     ::= "r1=" number "r2=" number

(* Булевы операции *)
boolean_cmd    ::= "union"     id_assign "base=" OBJECT_ID "tool=" OBJECT_ID
                 | "subtract"  id_assign "base=" OBJECT_ID "tool=" OBJECT_ID
                 | "intersect" id_assign "base=" OBJECT_ID "tool=" OBJECT_ID

(* Трансформации *)
transform_cmd  ::= "translate" "obj=" OBJECT_ID "x=" number "y=" number "z=" number
                 | "rotate"    "obj=" OBJECT_ID "ax=" axis "ang=" number
                 | "scale"     "obj=" OBJECT_ID "sx=" number "sy=" number "sz=" number
                 | "mirror"    "obj=" OBJECT_ID "plane=" plane

axis           ::= "X" | "Y" | "Z"
plane          ::= "XY" | "XZ" | "YZ"

(* Запросы к сцене *)
query_cmd      ::= "get_volume" "obj=" OBJECT_ID
                 | "get_bbox"   "obj=" OBJECT_ID
                 | "list_objects"

(* Общие *)
id_assign      ::= "id=" OBJECT_ID
OBJECT_ID      ::= [a-zA-Z][a-zA-Z0-9_]{0,31}
number         ::= ["-"] DIGIT+ ["." DIGIT+] [unit]
unit           ::= "mm" | "cm" | "m"
DIGIT          ::= [0-9]
NEWLINE        ::= "\n"
```

#### 5.2 Семантические правила

1. `OBJECT_ID` должен быть уникальным в сессии (при дубликате — ошибка, не перезапись)
2. Все числовые параметры > 0 (кроме координат трансформаций)
3. Для `subtract` и `intersect` — `base` и `tool` не могут быть одним объектом
4. `rotate` применяет угол в градусах (не радианах)
5. Единицы измерения конвертируются в мм при парсинге

#### 5.3 Пример валидной программы

```
create_box id=body w=100 h=50 d=30
create_cylinder id=hole r=4.5 h=35
translate obj=hole x=50 y=25 z=0
subtract id=result base=body tool=hole
```

#### 5.4 ParseError dataclass

```python
@dataclass
class ParseError:
    line: int
    column: int
    token: str
    expected: list[str]
    message: str   # human-readable, для передачи в LLM Planner
```

LLM Planner получает `ParseError.message` и перегенерирует команду — не более 3 попыток.

---

### 6. Протокол агентов Hermes v2

#### 6.1 Формат сообщений Redis Streams

**Задание агенту (Orchestrator → Agent):**
```json
{
  "msg_type": "TASK",
  "task_id": "task_7f3a",
  "session_id": "sess_abc123",
  "agent_domain": "geometry",
  "command": "create_box",
  "params": {"w": 100, "h": 50, "d": 30, "id": "body"},
  "scene_version": 6,
  "timeout_ms": 5000,
  "priority": 1
}
```

**Ответ агента (Agent → Orchestrator):**
```json
{
  "msg_type": "RESULT",
  "task_id": "task_7f3a",
  "agent_id": "geometry_agent_01",
  "success": true,
  "output_id": "body",
  "confidence": 0.98,
  "execution_ms": 43,
  "patch": {
    "add_objects": {
      "body": {
        "type": "box",
        "params": {"w": 100, "h": 50, "d": 30},
        "brep_key": "brep:sess_abc123:body"
      }
    },
    "remove_objects": [],
    "set_active": "body"
  },
  "error": null
}
```

**Ошибка агента:**
```json
{
  "msg_type": "RESULT",
  "task_id": "task_7f3a",
  "success": false,
  "output_id": null,
  "confidence": 0.0,
  "patch": null,
  "error": {
    "code": "NULL_SHAPE",
    "description": "BRepAlgoAPI_Cut вернул пустой Shape. Вероятная причина: tool полностью содержит base.",
    "recoverable": true,
    "suggested_action": "Проверить, что объект hole пересекает body, но не содержит его полностью."
  }
}
```

#### 6.2 Правила разрешения параллельных конфликтов

```
Правило 1: Параллельное выполнение допустимо только для операций над РАЗНЫМИ объектами.
Правило 2: Операция, зависящая от результата другой, выполняется только после её завершения.
Правило 3: При конфликте patch — last-write-wins с логированием конфликта.
Правило 4: Confidence < 0.5 у любого агента → маршрутизация в Debug Agent перед записью.
```

#### 6.3 Топологическая сортировка задач

Orchestrator строит DAG зависимостей из плана LLM Planner и выполняет задачи в топологическом порядке, параллелизируя независимые узлы.

---

### 7. Стратегия обработки ошибок и восстановления

```
Уровень 1 — DSL Parse Error
  → Парсер вернул ParseError
  → LLM Planner перегенерирует команду (макс. 3 попытки)
  → При 3 неудачах → запрос уточнения у пользователя

Уровень 2 — Geometry Execution Error (агент вернул success=False)
  → Debug Agent получает задачу
  → Debug Agent пробует ShapeFix
  → Если исправлено → валидация → запись
  → Если не исправлено → формирует ErrorReport для LLM Planner

Уровень 3 — Validation Error (агент вернул success=True, но Validator провалился)
  → Откат к последнему снапшоту
  → LLM Planner получает ValidationError с кодом и описанием
  → LLM Planner перепланирует операцию

Уровень 4 — Semantic Mismatch (Vision Evaluator: semantic_match=False)
  → Iteration Controller проверяет бюджет
  → Если бюджет есть → LLM Planner получает correction_hint и перепланирует
  → Если бюджет исчерпан → возвращаем лучший результат с флагом

Уровень 5 — Критическая ошибка (исключение Python, недоступность Redis, etc.)
  → Логирование в structured log (structlog)
  → Возврат пользователю с описанием
  → Состояние сцены не изменяется (транзакционная запись)
```

**Транзакционность:** Сначала пишется BRep в Redis, затем атомарно обновляется JSON-граф через MULTI/EXEC. При сбое — только BRep-мусор без обновления графа (очищается фоновым GC).

**ShapeFix — порядок применения (bottom-up):**
```python
from OCC.Core.ShapeFix import (
    ShapeFix_Edge,   # 1. Вырожденные рёбра
    ShapeFix_Face,   # 2. Проблемные грани
    ShapeFix_Shell,  # 3. Незамкнутые оболочки
    ShapeFix_Solid,  # 4. Солиды
    ShapeFix_Shape,  # 5. Общий фиксер
)
```

---

### 8. Scene Summary для LLM (сжатый формат)

```json
{
  "session_id": "sess_abc123",
  "version": 7,
  "objects_count": 3,
  "active_object": "result",
  "objects_summary": [
    {"id": "body", "type": "box", "valid": true},
    {"id": "hole", "type": "cylinder", "valid": true},
    {"id": "result", "type": "boolean_subtract", "inputs": ["body", "hole"], "valid": true}
  ],
  "last_operation": "subtract",
  "last_error": null
}
```

---

### 9. Vision Loop — уточнённая семантика

Vision Loop — **не** основной механизм валидации. Это механизм **семантической навигации**.

```
Геометрическая корректность   → Geometry Validation Layer (детерминированный)
Семантическое соответствие    → Vision Evaluator (вероятностный)
```

Vision Loop вызывается после каждой **завершённой итерации** (весь план LLM Planner выполнен), НЕ после каждой отдельной операции.

**Vision Evaluator НЕ может оценить:**
- Точные размеры (только грубое соответствие пропорций)
- Внутренние полости и скрытые грани
- Коаксиальность отверстий
- Допуски менее ~10% от размера объекта

---

### 10. MVP — строгое определение

#### 10.1 Scope MVP

**Включено:**
- Один агент (Geometry + Boolean + Transform в одном процессе, без swarm)
- DSL: 8 команд (`create_box`, `create_sphere`, `create_cylinder`, `subtract`, `union`, `translate`, `rotate`, `scale`)
- Один бэкенд: pythonocc-core / cadquery-ocp
- Валидатор: manifold check + volume check (2 из 5 проверок)
- Рендер: 1 камера (isometric)
- Vision Loop: один вызов после завершения (не итеративный)
- Iteration Controller: max_iterations=1
- Хранилище: **SQLite** вместо Redis

**НЕ входит в MVP:**
- Swarm архитектура
- Debug Agent
- ShapeFix (кроме простейшего)
- Multi-view рендер (4 камеры)
- STEP экспорт (только STL)
- Полная обработка ошибок Уровней 4–5
- Rollback / снапшоты

#### 10.2 Критерии готовности MVP

- [ ] 20 тестовых запросов обработаны без краша системы
- [ ] DSL парсер: 0 false-positive (валидный DSL не отвергается)
- [ ] Геометрический валидатор: корректно детектирует NULL_SHAPE и NON_MANIFOLD
- [ ] STL-файл открывается в MeshLab без ошибок
- [ ] Round-trip time (запрос → файл): < 30 секунд

---

### 11. Технологический стек

#### Полный стек

| Компонент | Технология | Версия |
|---|---|---|
| LLM Planner | Anthropic API | claude-sonnet-4-20250514 |
| Vision Evaluator | Anthropic Vision API | claude-sonnet-4-20250514 |
| CAD Kernel | pythonocc-core (OCCT) | 7.7.x |
| DSL Parser | Lark (Python) | 1.1.x |
| Agent Framework | Python asyncio + Redis Streams | asyncio 3.11, Redis 7 |
| Scene Graph Store | Redis | 7.x |
| Renderer | VTK Python | 9.3.x |
| Offscreen Display | OSMesa / EGL | — |
| Shape Validation | pythonocc BRepCheck | — |
| Shape Healing | pythonocc ShapeFix | — |
| API Layer | FastAPI | 0.110.x |
| Логирование | structlog | 24.x |
| Тестирование | pytest + pytest-asyncio | — |
| Контейнеризация | Docker + docker-compose | — |

#### MVP стек (упрощённый)

| Компонент | MVP технология |
|---|---|
| Scene Graph | SQLite (sqlite3, stdlib) |
| Agent | Один Python класс, без asyncio |
| Renderer | VTK offscreen или matplotlib Agg |
| API | FastAPI |
| Queue | Нет, синхронный вызов |

---

### 12. Этапы разработки

#### Этап 0: Прототип DSL + Parser (1–2 недели)
**Deliverable:** `dsl/grammar.lark`, `dsl/parser.py`, `dsl/ast_nodes.py`, тест-репорт H1.

1. Написать EBNF-грамматику (grammar.lark)
2. Написать Lark-парсер и AST-узлы
3. Написать набор из 50 тестов: valid DSL, invalid DSL, edge cases
4. Написать промпт для LLM с грамматикой в system prompt
5. Запустить 100 запросов, измерить parse success rate
6. **Go/No-Go по Гипотезе H1**

#### Этап 1: CAD Kernel Adapter (1–2 недели)
**Deliverable:** `kernel/adapter.py`, `kernel/validator.py`, `kernel/registry.py`

1. Установить pythonocc-core в Docker-контейнере
2. Реализовать Kernel Adapter для 8 MVP-команд
3. Реализовать ShapeRegistry
4. Реализовать GeometryValidator (2 проверки для MVP)
5. Тест: создать 10 сложных форм с булевыми операциями, проверить STL в MeshLab

#### Этап 2: Scene Graph + Storage (1 неделя)
**Deliverable:** `scene/graph.py`, `scene/storage.py`

1. Реализовать SceneGraph класс (SQLite для MVP)
2. Реализовать сериализацию/десериализацию BRep
3. Реализовать append-only history log
4. Реализовать Scene Summary generator для LLM

#### Этап 3: LLM Planner Integration (1–2 недели)
**Deliverable:** `planner/llm_planner.py`, `api/main.py`

1. Написать system prompt для LLM Planner (включая grammar.lark)
2. Реализовать Structured Plan parser
3. Реализовать retry logic для parse errors
4. Собрать pipeline: FastAPI → LLM → Parser → Kernel → Validator → Scene Graph

#### Этап 4: Renderer + Vision Loop (1–2 недели)
**Deliverable:** `renderer/vtk_renderer.py`, `vision/evaluator.py`, тест-репорт H2

1. Настроить VTK offscreen в Docker (OSMesa)
2. Реализовать Renderer (1 камера для MVP)
3. Реализовать Vision Evaluator
4. Подключить к pipeline
5. **Go/No-Go по Гипотезе H2**

#### Этап 5: Iteration Controller + Error Handling (1 неделя)
**Deliverable:** `controller/iteration_controller.py`, `errors/handlers.py`, MVP Acceptance Report

1. Реализовать IterationController
2. Реализовать полную стратегию обработки ошибок (все 5 уровней)
3. Реализовать rollback (простой для MVP: reload last SQLite state)
4. **MVP Acceptance Testing** по критериям раздела 10.2

#### Этап 6: Swarm Architecture (после MVP, 2–3 недели)

1. Мигрировать на Redis (заменить SQLite)
2. Выделить агентов в отдельные asyncio процессы
3. Реализовать Orchestrator с DAG и топологической сортировкой
4. Реализовать Debug Agent + ShapeFix pipeline
5. Реализовать 4-камерный рендер
6. **A/B тест по Гипотезе H4**

---

### 13. Риски и митигации

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| LLM генерирует DSL ниже 85% accuracy | Средняя | Высокое | Этап 0 Go/No-Go; fallback — диалоговое уточнение |
| pythonocc сложен в установке | Высокая | Среднее | Docker image на этапе 0 (cadquery-ocp как альтернатива) |
| Vision loop не даёт полезного feedback | Средняя | Среднее | Этап 4 Go/No-Go; альтернатива — аналитические метрики |
| OCC булевы операции нестабильны | Средняя | Высокое | ShapeFix pipeline; ограничение класса задач в v1 |
| LLM Planner "зависает" в семантическом цикле | Низкая | Высокое | STUCK_IN_LOOP детектор в Iteration Controller |
| Производительность: >30s на запрос | Средняя | Среднее | Profile на этапе 3; кэшировать BRep промежуточных объектов |

---

## ЧАСТЬ 2 — КАРТА АРХИТЕКТУРЫ (из aicad-diagram.jsx)

### Компоненты и связи

#### 10 узлов системы

| ID | Название | Фаза | Технология |
|----|----------|------|------------|
| T1 | LLM Planner | P1 | Anthropic API · claude-sonnet-4-20250514 |
| T2 | Hermes Swarm | P2 | Python asyncio · Redis Streams |
| T3 | DSL Parser | P1 | Python · Lark library · EBNF grammar |
| T4 | Geometry Kernel | P2 | pythonocc-core · OCCT 7.x · BRep_Builder |
| T5 | Geometry Validator | P2 | BRepCheck_Analyzer · BRepGProp · BRep_Tool |
| T6 | Scene Graph Store | P1 | Redis 7.x · JSON · Binary BRep keys |
| T7 | Renderer | P3 | VTK · OSMesa / EGL · PNG |
| T8 | Vision Evaluator | P3 | Claude Vision API · claude-sonnet-4 multimodal |
| T9 | Iteration Controller | P2 | Python · stateful loop · Redis counter |
| T10 | Export | P3 | OCC StlAPI · STEPControl · BRepMesh tessellation |

#### 14 связей (рёбра)

| От | До | Данные | Протокол | Тип |
|----|----|--------|----------|-----|
| T1 | T2 | Structured Plan | Redis Streams → JSON | Основной поток |
| T2 | T3 | DSL Commands | In-process text | Основной поток |
| T3 | T4 | AST | In-process dataclass | Основной поток |
| T4 | T5 | TopoDS_Shape | Sync Python call | Валидация |
| T5 | T6 | ValidationResult + ScenePatch | Sync call on success | Валидация |
| T5 | T2 | ErrorCode | Redis Streams | Ошибки → Debug |
| T4 | T6 | BRep bytes | Redis Binary SET | Хранение |
| T6 | T7 | Scene Snapshot | Shape reference | Хранение |
| T6 | T10 | active_object shape | Python API | Хранение |
| T6 | T1 | Scene Graph Summary | JSON digest | Обратная связь |
| T7 | T8 | 4× PNG (512×512) | REST/bytes | Основной поток |
| T8 | T9 | Evaluation JSON | Python call | Основной поток |
| T9 | T1 | correction_hint | CONTINUE signal | Обратная связь |
| T9 | T10 | DONE signal | Control signal | Основной поток |

#### Легенда стилей связей

| Стиль | Цвет | Описание |
|-------|------|----------|
| primary | `#E2E8F0` сплошная | Основной поток данных |
| validate | `#FBBF24` сплошная | Поток валидации |
| error | `#F87171` пунктир | Поток ошибок (Recovery) |
| storage | `#F472B6` пунктир | Хранение / персистентность |
| feedback | `#A3E635` сплошная жирная | Обратная связь (Feedback) |

#### Фазы разработки

- **P1 — MVP:** T1, T3, T6
- **P2 — Агенты + Валидация:** T2, T4, T5, T9
- **P3 — Vision Loop + Экспорт:** T7, T8, T10

---

## ЧАСТЬ 3 — АУДИТ СРЕДЫ (результаты проверки)

> Проверено в ходе сессии, май 2026

| Зависимость | Статус | Версия | Примечание |
|-------------|--------|--------|------------|
| `anthropic` | ✅ установлен | 0.97.0 | T1, T8 — готово |
| `lark` | ✅ установлен, протестирован | 1.3.1 | Грамматика DSL работает |
| `redis` | ✅ клиент установлен | 7.4.0 | Нужен сервер (docker) |
| `cadquery` | ✅ установлен | 2.7.0 | Все OCC операции работают |
| `cadquery-ocp` | ✅ установлен | 7.8.1.1 | OCCT 7.x — замена pythonocc-core |
| `vtk` | ✅ установлен | 9.3.1 | Offscreen без OSMesa не работает |
| `matplotlib` | ✅ Agg backend | — | Рендер для MVP — работает |
| `docker` | ✅ | 29.3.1 | Для Redis, OSMesa контейнеров |
| `pythonocc-core` | ❌ не pip-устанавливается | — | Не нужен: cadquery-ocp = то же самое |
| `sqlite3` | ✅ stdlib | — | MVP хранилище |

**Протестировано через CadQuery Solid API:**
- `makeBox(100, 50, 30)` → Volume = 150000.0 ✅
- `makeCylinder(4.5, 35)` → Volume = 2226.6 ✅
- `translate((50, 25, 0))` ✅
- `cut()` → Volume = 148091.5, `isValid() = True` ✅
- `exportStl('/tmp/test.stl')` → 26 KB ✅
- `exportBin/importBin` (BRep round-trip) ✅
- Lark parser: 4 команды из примера ТЗ → Parse OK ✅
- matplotlib Agg isometric render → PNG 69 KB ✅
