# COMP3019J 理发店预约系统 · 开发前统一规格 v1.0（AI 执行版）

> 读者：AI 编码助手。本文件是可执行约束，不含说明性文字。
> 适用：Team Custom Name 4 · 单店理发店预约系统 · 4 人协作
> 状态：除 §15 列出的 2 个待决项外，全部已定。

---

## 0. 元规则

### 0.1 权威

本文件是系统边界的唯一来源。路由、方法、请求字段、响应字段、状态码、错误码、重定向目标、权限判定、字段名、枚举值、函数签名，一律以此为准。

其他文档（`01_需求与规则.md`、`02_设计.md`、`04_验收用例.md`、`docs/spec/*`）描述动机或历史，与本文件冲突时以本文件为准。

### 0.2 执行约束（每次生成代码都要遵守）

1. 只实现本文件列出的功能。不得添加推荐、聊天、支付、多门店、手机端、优惠券、邮件验证、找回密码、改密码、分页。
2. 字段名以 §5 为准。§5 里没有的字段不许出现在表单、JSON 或模型里；确实需要先改本文件。
3. 服务端重新校验一切。前端校验只是提示，不是防线。
4. 权限在服务端判断；前端隐藏按钮不算。
5. 不返回 SQL、堆栈、文件路径、异常类名、密码或哈希。
6. 时间与金额只用 §2.3、§2.4 规定的表示。
7. 不加依赖。`requirements.txt` 现有 7 项之外的东西一律先说明理由。
8. 每次交付一个可验证的小任务。

### 0.3 实现自由（本文件明确不规定）

以下不是接口，任何实现可自由选择，不构成违规：

- 目录与包的内部组织（blueprint 内部如何拆分、是否用具名子包）
- ORM 使用方式、查询写法、模型类名与内部辅助函数
- 测试框架（pytest / unittest）、测试文件位置
- HTML 结构、CSS 类名、DOM 层级、模板拆分粒度
- 依赖库补丁版本、日志格式、内部异常类名
- 数据库迁移工具（本项目不使用；见 §12.4）

**唯一例外是 §12.1 的文件归属表**——那是并行开发的防撞车约定，不是风格偏好。

### 0.4 变更流程

| 变更 | 需四人同意 | 说明 |
|---|---|---|
| 新增可选查询参数 | 否 | 同步本文件 |
| 新增响应字段（只增不删） | 否 | 同步本文件 |
| 重命名 / 删除字段、改路由 | 是 | — |
| 改状态码或错误码语义 | 是 | — |
| 新增错误码 | 是 | — |

**先改本文件，再改实现。实现与本文件不一致时，视为实现有 bug。**

### 0.5 证据要求

合规性的唯一有效证据是**真实 HTTP 请求**（Flask test client 打真实路由，或 curl 打运行中实例）。

| 算证据 | 不算证据 |
|---|---|
| 走完整路由 + 参数解析 + 序列化链路 | 直接调用服务层函数 |
| 断言状态码、响应头、响应体 | 只在数据库夹具上验约束 |
| 真实并发请求 | 断言内部函数返回值 |

每个错误码至少有一条用例能真实触发它。未通过真实请求验证的接口只能标「待接入」，不得写成已完成。

### 0.6 合规检查清单（合并时逐项跑）

```text
1. flask routes 输出 == §3 路由总表（路径与方法均一致）
2. 每个请求/响应字段都能在 §5 找到，拼写与类型一致
3. §7 每个错误码都能被真实请求触发，返回表中所列 HTTP 状态
4. HTML 未登录 302 且 Location 目标正确；JSON 未登录 401 且带 login_url 无 next
5. 账号类 POST 成功 302；业务类 POST 成功 303
6. 任意响应中的 price 恒为两位小数字符串，且不含 price_minor
7. 任意时刻字段恒为 YYYY-MM-DDTHH:MM，无秒、无时区后缀
8. 所有 4xx/5xx 的 JSON 响应都含 error 与 message
9. §8 权限矩阵逐格验证，状态码符合 §8.2
10. 库里不存在 workstation_type 或 reason 的枚举域外值
```

---

## 1. 基线：B 已完成的部分（作为起点，不重写）

### 1.1 文件清单

```text
app.py                  create_app 工厂、注册蓝图、注册错误处理、注册 seed 命令
auth.py                 /auth 蓝图：注册、登录、登出、管理员开号
models.py               8 张表的 SQLAlchemy 模型（唯一一份）
responses.py            wants_json / json_error / 401 / CSRF / HTTP / 500 处理器
money.py                price_to_minor / price_from_minor（Decimal）
seed.py                 flask seed 命令 + 演示数据
templates/auth/base.html    整页模板（导航、角色条件、flash）
templates/auth/form.html    表单页
templates/auth/demo.html    首页
templates/errors/csrf.html
templates/errors/error.html
tests/test_auth.py           9 例
tests/test_booking_rules.py  6 例（T3/T4/T6/T7 的约束行为）
tests/test_contracts.py      6 例
requirements.txt             Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF, SQLAlchemy, WTForms, email-validator
```

### 1.2 已实现路由

```text
GET  /                     200 首页
GET  /auth/register        200 表单（已登录 302 /）
POST /auth/register        302 /auth/login
GET  /auth/login           200 表单
POST /auth/login           302 next 或 /
POST /auth/logout          302 /（GET 405）
GET  /auth/staff           200 开户表单（admin）
POST /auth/staff           302 /auth/staff
```

### 1.3 可复用组件（不得重复实现）

| 组件 | 位置 | 用途 |
|---|---|---|
| `wants_json()` | `responses.py` | 判断当前请求要不要 JSON |
| `json_error(code, message, status, **extra)` | `responses.py` | 生成标准错误体；A/C/D 报业务错误码必须用它 |
| `register_error_handlers(app)` | `responses.py` | 注册 401/CSRF/HTTP/500 处理器 |
| `price_to_minor(value)` | `money.py` | 表单字符串 → 整数最小单位；非法抛 `PriceValidationError` |
| `price_from_minor(value)` | `money.py` | 整数最小单位 → 两位小数字符串 |
| `csrf_token()` meta 标签 | `templates/auth/base.html` | `<meta name="csrf-token">`，fetch 取它填 `X-CSRFToken` |
| `db` / 8 张模型 | `models.py` | 全部数据访问的唯一入口 |

### 1.4 数据模型（以 `models.py` 为准，不得改名）

`PRAGMA foreign_keys = ON` 在每个连接上启用。

```text
user
  id               Integer        PK
  name             String(100)    NOT NULL
  email            String(254)    NOT NULL UNIQUE, collation NOCASE
  password_hash    String(255)    NOT NULL
  role             String(16)     NOT NULL default 'customer'
                                  CHECK role IN ('customer','stylist','admin')
  is_active        Boolean        NOT NULL default TRUE

service
  id                        Integer    PK
  name                      String(100) NOT NULL
  description               Text        NOT NULL
  price_minor               Integer     NOT NULL  CHECK price_minor >= 0
  duration_minutes          Integer     NOT NULL  CHECK duration_minutes > 0 AND duration_minutes % 15 = 0
  required_workstation_type String(40)  NOT NULL
  is_active                 Boolean     NOT NULL default TRUE

staff_service
  stylist_id   Integer  FK user.id      PK（复合主键，无独立 id）
  service_id   Integer  FK service.id   PK

workstation
  id                 Integer    PK
  label              String(80) NOT NULL（不设 UNIQUE）
  workstation_type   String(40) NOT NULL
  is_active          Boolean    NOT NULL default TRUE

working_shift
  id           Integer  PK
  stylist_id   Integer  FK user.id  NOT NULL
  work_date    Date     NOT NULL
  start_time   Time     NOT NULL
  end_time     Time     NOT NULL  CHECK end_time > start_time

unavailability
  id           Integer   PK
  stylist_id   Integer   FK user.id  NOT NULL
  starts_at    DateTime  NOT NULL
  ends_at      DateTime  NOT NULL  CHECK ends_at > starts_at
  reason       String(100) NOT NULL

appointment
  id                 Integer   PK
  customer_id        Integer   FK user.id        NOT NULL
  stylist_id         Integer   FK user.id        NOT NULL
  service_id         Integer   FK service.id     NOT NULL
  workstation_id     Integer   FK workstation.id NOT NULL
  starts_at          DateTime  NOT NULL
  ends_at            DateTime  NOT NULL  CHECK ends_at > starts_at
  agreed_price_minor Integer   NOT NULL  CHECK agreed_price_minor >= 0
  status             String(16) NOT NULL default 'confirmed'
                                CHECK status IN ('confirmed','cancelled','completed','no_show')
  arrived_at         DateTime  NULL
  无 created_at 字段

slot_allocation
  id              Integer   PK
  appointment_id  Integer   FK appointment.id NOT NULL
  stylist_id      Integer   FK user.id        NOT NULL
  workstation_id  Integer   FK workstation.id NOT NULL
  slot_start      DateTime  NOT NULL
  UNIQUE (stylist_id, slot_start)        ← §10 的最终裁定者
  UNIQUE (workstation_id, slot_start)    ← §10 的最终裁定者
```

**类型约定**：`Date` 存日期，`Time` 存时刻，`DateTime` 存日期时间且**无时区信息**，视为 `Asia/Shanghai` 本地时间。ID 为自增整数。

**时区**：全系统 `Asia/Shanghai`，不做 UTC 换算。

---

## 2. 通用约定

### 2.1 命名

全部 `snake_case`。数据库列名、JSON 键、表单字段名、查询参数**完全一致**，不做映射层。例外只有 §5.3 列出的表单→模型转换。

### 2.2 时间

| 项 | 约定 |
|---|---|
| 日期 | `YYYY-MM-DD` |
| 时刻（边界） | `YYYY-MM-DDTHH:MM`，分钟精度，**无秒、无时区后缀** |
| 时刻（数据库 Time 列） | `HH:MM` |
| 区间 | 半开 `[starts_at, ends_at)`，10:00–11:00 与 11:00–12:00 相接不重叠 |
| 栅格 | 所有开始时间与时长对齐 15 分钟栅格 |
| 服务端当前时间 | 用服务器本地时间，不信任客户端 |

### 2.3 金额

```text
数据库     整数，最小货币单位（分），列名 price_minor / agreed_price_minor
表单输入   十进制字符串，恰好两位小数，如 "180.00"
边界输出   十进制字符串，恰好两位小数，如 "180.00"   ← 不输出 price_minor
```

- 解析用 Decimal，**禁止 float**。
- 非法输入（非数字、负数、超过两位小数、非有限值、超出 SQLite 有符号 64 位换算范围）→ `400 VALIDATION_FAILED`，`fields.price` 说明。
- 转换只在边界发生，且必须精确（`"180.00"` ↔ `18000`）。

### 2.4 时长

`duration_minutes` 为整数，15 ≤ 值 ≤ 240，且必须为 15 的整数倍。

### 2.5 会话与认证

| 场景 | 行为 |
|---|---|
| HTML 请求（`Accept` 不含 `application/json`）且未登录 | `302` → `/auth/login?next=<本站相对路径>` |
| JSON 请求（路径以 `/api/` 开头，或 `Accept: application/json`）且未登录 | `401 AUTH_REQUIRED`，响应体带 `login_url` |
| 会话失效 | 按未登录处理，行为同上 |
| `login_url` | 恒为 `/auth/login`，**不带 next** |
| 密码 | 只存 `werkzeug` 哈希；任何响应不含明文或哈希 |
| 停用账号登录 | `VALIDATION_FAILED`，文案与凭据错误完全相同（不暴露账号状态） |
| 角色来源 | 只来自数据库；请求中携带的 `role`、`is_active` 一律忽略 |

`next` 安全规则——只接受本站绝对路径，其余一律回落到 `/`：

| 输入 | 处理 |
|---|---|
| `/my-appointments`、`/appointments/12/reschedule` | 接受 |
| 带 scheme 或 host（`https://evil.example/x`） | 丢弃 → `/` |
| `//evil.example/x` | 丢弃 → `/` |
| 含反斜线 | 丢弃 → `/` |
| 含控制字符（`\n` `\r` `\t` `\0`） | 丢弃 → `/` |
| 编码绕过（`%2f%2f`、`%5c`） | 先解码再判定，命中即丢弃 |
| 含 `..` 路径段 | 丢弃 → `/` |
| 空或缺省 | `/` |

`next` 只能出现在非 JSON 的 GET/HEAD 上。JSON 请求与所有 POST 的成功登录一律回 `/`。

### 2.6 CSRF

| 场景 | 约定 |
|---|---|
| 表单提交 | 表单字段 `csrf_token` |
| fetch 写请求 | 请求头 `X-CSRFToken`，值取自 `<meta name="csrf-token">` |
| 所有 POST | 必须校验；缺失或无效 → `400 CSRF_FAILED` |
| GET / HEAD | 不校验 |

### 2.7 内容协商

| 请求特征 | 响应 |
|---|---|
| 路径以 `/api/` 开头，或 `Accept: application/json` | `application/json` |
| 其余 | `text/html` |

歧义时以路径为准：`/api/*` 恒为 JSON，**永不返回 HTML 页面**。

### 2.8 重定向

| 场景 | 状态码 |
|---|---|
| 受保护 GET 未登录 | `302` |
| **账号类** POST 成功（`/auth/register`、`/auth/login`、`/auth/logout`、`/auth/staff`） | `302` |
| **业务类** POST 成功（`/book`、`/cancel`、`/reschedule`、`/staff/*`、`/admin/*`） | `303` |
| GET 到仅接受 POST 的路由 | `405` |

账号类沿用 302（与现有实现与现有测试一致）；业务类一律 303（PRG 标准码，避免 POST 重放）。两者不得混用。

### 2.9 错误体

JSON 错误响应：

```json
{
  "error": "STABLE_CODE",
  "message": "Human-readable safe message.",
  "fields": {"price": "must be a two-decimal string"},
  "login_url": "/auth/login"
}
```

- `error`、`message` 必有；`fields`、`login_url` 可选。
- `fields` 仅用于字段级校验失败，键为字段名。
- `error` 是稳定标识符，调用方按它分支，**不解析 message**。

HTML 请求的错误以重渲染页面为主，**但 HTTP 状态码必须是 §7 所列的值**（200 只用于成功渲染）。

### 2.10 分页

不提供分页。所有列表必须由 `date` / `status` 等条件限定范围。

---

## 3. 路由总表

状态：`已实现`（B 完成）/ `待接入`（本规格已定，无代码）。

### 3.1 公开与账号

| 方法 | 路径 | 角色 | 状态 |
|---|---|---|---|
| GET | `/` | 公开 | 已实现 |
| GET | `/auth/register` | 访客 | 已实现 |
| POST | `/auth/register` | 访客 | 已实现 |
| GET | `/auth/login` | 访客 | 已实现 |
| POST | `/auth/login` | 访客 | 已实现 |
| POST | `/auth/logout` | 已登录 | 已实现 |
| GET | `/auth/staff` | admin | 已实现 |
| POST | `/auth/staff` | admin | 已实现 |
| GET | `/services` | 公开 | 待接入 |
| GET | `/services/<int:service_id>` | 公开 | 待接入 |

### 3.2 顾客

| 方法 | 路径 | 状态 |
|---|---|---|
| GET | `/api/slots` | 待接入（A） |
| GET | `/book` | 待接入（C） |
| POST | `/book` | 待接入（C） |
| GET | `/my-appointments` | 待接入（C） |
| POST | `/appointments/<int:appointment_id>/cancel` | 待接入（C） |
| GET | `/appointments/<int:appointment_id>/reschedule` | 待接入（C） |
| POST | `/appointments/<int:appointment_id>/reschedule` | 待接入（C） |

### 3.3 发型师

| 方法 | 路径 | 状态 |
|---|---|---|
| GET | `/staff/schedule` | 待接入（D） |
| POST | `/staff/appointments/<int:appointment_id>/arrive` | 待接入（D） |
| POST | `/staff/appointments/<int:appointment_id>/complete` | 待接入（D） |
| POST | `/staff/appointments/<int:appointment_id>/no-show` | 待接入（D） |

### 3.4 管理员

| 方法 | 路径 | 状态 |
|---|---|---|
| GET | `/admin/services` | 待接入（D） |
| GET / POST | `/admin/services/new` | 待接入（D） |
| GET / POST | `/admin/services/<int:service_id>/edit` | 待接入（D） |
| POST | `/admin/services/<int:service_id>/toggle` | 待接入（D） |
| GET | `/admin/staff-services` | 待接入（D） |
| GET / POST | `/admin/staff-services/new` | 待接入（D） |
| POST | `/admin/staff-services/<int:stylist_id>/<int:service_id>/delete` | 待接入（D） |
| GET | `/admin/workstations` | 待接入（D） |
| GET / POST | `/admin/workstations/new` | 待接入（D） |
| GET / POST | `/admin/workstations/<int:workstation_id>/edit` | 待接入（D） |
| POST | `/admin/workstations/<int:workstation_id>/toggle` | 待接入（D） |
| GET | `/admin/shifts` | 待接入（D） |
| GET / POST | `/admin/shifts/new` | 待接入（D） |
| GET / POST | `/admin/shifts/<int:shift_id>/edit` | 待接入（D） |
| POST | `/admin/shifts/<int:shift_id>/delete` | 待接入（D） |
| GET | `/admin/unavailability` | 待接入（D） |
| GET / POST | `/admin/unavailability/new` | 待接入（D） |
| GET / POST | `/admin/unavailability/<int:unavailability_id>/edit` | 待接入（D） |
| POST | `/admin/unavailability/<int:unavailability_id>/delete` | 待接入（D） |
| GET | `/admin/overview` | 待接入（D） |

---

## 4. 接口细则

### 4.1 账号（已实现，不得改动形状）

| 方法 | 路径 | 请求字段 | 成功 | 失败 |
|---|---|---|---|---|
| POST | `/auth/register` | `name, email, password, csrf_token` | 302 `/auth/login` | 400 `VALIDATION_FAILED` |
| POST | `/auth/login` | `email, password, csrf_token`，`next` 可带在查询串 | 302 `next` 或 `/` | 400 `VALIDATION_FAILED`；400 `CSRF_FAILED` |
| POST | `/auth/logout` | `csrf_token` | 302 `/` | 405（GET）；400 `CSRF_FAILED` |
| POST | `/auth/staff` | `name, email, password, csrf_token` | 302 `/auth/staff` | 400 `VALIDATION_FAILED`；403 `FORBIDDEN` |

- `/auth/register` 创建的用户 `role` 恒为 `customer`；`/auth/staff` 创建的恒为 `stylist`。
- 约束：`password` 长度 8–128；`name` ≤ 100；`email` ≤ 254，全局唯一且不区分大小写。
- **无** `password2`、**无** `remember`、无邮件验证、无找回密码、无改密码。

### 4.2 `GET /api/slots`（A 实现）

**唯一的可约时段来源。** 前端不得自行计算、过滤或补全时段。

认证：`customer`。GET 不需要 CSRF。C 的 fetch 必须发送 `Accept: application/json`。

请求使用**互斥的两种模式**，混传为错误：

| 模式 | 必填参数 | 禁止参数 |
|---|---|---|
| 新建 | `service_id`, `stylist_id`, `date` | `appointment_id` |
| 改期 | `appointment_id`, `date` | `service_id`, `stylist_id` |

| 参数 | 类型 | 校验 |
|---|---|---|
| `service_id` | int | 存在且 `is_active = true` |
| `stylist_id` | int | 存在、`is_active = true` 且角色为 stylist |
| `appointment_id` | int | 当前顾客本人、`confirmed`、`now < starts_at` |
| `date` | `YYYY-MM-DD` | 合法日期；`today ≤ date ≤ today + 60 天`（第 60 天含） |

**改期模式附加规则**：

- `service_id`、`stylist_id` 由原预约派生，不得由请求覆盖。
- `duration_minutes` 由原预约 `ends_at - starts_at` 计算，**不读服务当前时长**。
- 计算候选时段时排除该预约自身的旧占用，但仍检查其他预约、技能、班次、不可用区间、工位。
- 只读，不修改任何记录。

成功 `200 application/json`：

```json
{
  "date": "2026-11-20",
  "appointment_id": null,
  "service_id": 3,
  "stylist_id": 2,
  "duration_minutes": 60,
  "slots": ["09:00", "09:15", "10:30"],
  "empty_reason": null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 回显请求日期 |
| `appointment_id` | int \| null | 新建为 `null`，改期为原预约 ID |
| `service_id` / `stylist_id` | int | 服务端实际采用值 |
| `duration_minutes` | int | 服务端实际采用值 |
| `slots` | string[] | 升序，元素 `HH:MM`，每项均已通过完整区间校验 |
| `empty_reason` | string \| null | 非空时为 `null` |

`slots` 为空仍是 `200`（合法的"当天没空档"，不是错误）。

| `empty_reason` | 含义 |
|---|---|
| `NO_SHIFT` | 该发型师当日无班次 |
| `ALL_TAKEN` | 过滤过去起点、占用、不可用后无剩余候选 |
| `NO_WORKSTATION` | 无类型匹配且空闲的工位 |
| `NOT_QUALIFIED` | 该发型师无此服务技能（防御性） |
| `null` | `slots` 非空 |

失败：

| 状态 | 错误码 | 条件 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 缺参数、模式混传、ID/日期格式错、日期早于今天 |
| 400 | `DATE_OUT_OF_RANGE` | 日期超出 60 天窗口（`date > today + 60`） |
| 401 | `AUTH_REQUIRED` | 未登录或会话失效 |
| 403 | `FORBIDDEN` | 非 customer，或预约不属于当前顾客 |
| 404 | `NOT_FOUND` | service / stylist / appointment 不存在 |
| 409 | `INVALID_STATE` | 改期模式下原预约非 `confirmed` 或已开始 |
| 500 | `SERVER_ERROR` | 未捕获异常 |

**边界规则**：查询当天时，不晚于 `now` 的起点只从 `slots` 排除，不把整个查询变成 400；提交时 `starts_at <= now` 才是 400。查询宽松、提交严格。

### 4.3 `GET /services`、`GET /services/<service_id>`

| 方法 | 路径 | 角色 | 成功 | 失败 |
|---|---|---|---|---|
| GET | `/services` | 公开 | 200 列表，仅 `is_active = true`；含名称、描述、`price`、`duration_minutes`、工位类型 | — |
| GET | `/services/<int:service_id>` | 公开 | 200 详情 + 具备该技能且启用的发型师列表 | 404 `NOT_FOUND` |

`price` 为两位小数字符串。

### 4.4 `GET /book`、`POST /book`

| 方法 | 路径 | 角色 | 请求 | 成功 | 失败 |
|---|---|---|---|---|---|
| GET | `/book` | customer | `service_id, stylist_id` | 200 表单页 | 400 / 404 |
| POST | `/book` | customer | `service_id, stylist_id, date, start, csrf_token` | 303 `/my-appointments?booked=<id>` | 见下 |

POST 失败：

| 状态 | 错误码 | 条件 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 字段缺失/格式错、`start` 未对齐 15 分钟、`starts_at <= now`、发型师无该技能、超出班次、撞休息或请假、无兼容工位 |
| 400 | `DATE_OUT_OF_RANGE` | `date > today + 60`（第 60 天含） |
| 401 | `AUTH_REQUIRED` | 未登录 |
| 403 | `FORBIDDEN` | 非 customer |
| 404 | `NOT_FOUND` | 服务/发型师不存在或已停用 |
| 409 | `SLOT_TAKEN` | 该发型师或该工位的某个 15 分钟格已被占用 |
| 500 | `SERVER_ERROR` | 未捕获异常 |

**服务端自行决定，客户端提交了也一律忽略**：`customer_id`、`price`、`ends_at`、`workstation_id`、`status`。

价格、时长与结束时间在创建时冻结；之后改服务不影响已有预约。

### 4.5 `GET /my-appointments`

| 方法 | 路径 | 角色 | 请求 | 成功 |
|---|---|---|---|---|
| GET | `/my-appointments` | customer | `booked?` | 200 仅本人的预约列表 |

每行必须携带操作可行性标志，供模板决定按钮显隐（服务端仍须再次校验）：

```text
can_cancel      = status == 'confirmed' and now < starts_at - 2h
can_reschedule  = status == 'confirmed' and now < starts_at
```

`booked` 为刚创建的预约 ID，用于高亮提示，不参与鉴权。

### 4.6 `POST /appointments/<id>/cancel`

| 状态 | 错误码 | 条件 |
|---|---|---|
| 403 | `FORBIDDEN` | 预约不属于当前顾客 |
| 404 | `NOT_FOUND` | 预约不存在 |
| 409 | `INVALID_STATE` | 状态非 `confirmed` |
| 409 | `CANCEL_WINDOW_CLOSED` | `starts_at - now ≤ 2 小时` |

- 取消**不删除**记录：`status = cancelled`，同时**删除全部占用行**，时段立即重新可选。
- 重复取消 → `409 INVALID_STATE`，不做幂等成功。
- `arrived_at`、`agreed_price_minor`、`ends_at` 保持不变。
- 2 小时窗判定用服务器当前时间，与预约日期无关。`now >= starts_at - 2h` 即拒绝，边界包含在内。

### 4.7 `GET/POST /appointments/<id>/reschedule`

| 方法 | 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| GET | `/appointments/<id>/reschedule` | — | 200 表单 | 404 / 409 |
| POST | `/appointments/<id>/reschedule` | `date, start, csrf_token` | 303 `/my-appointments` | 见下 |

| 状态 | 错误码 | 条件 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 同 §4.4 的输入类条件；目标时段与当前完全相同 |
| 400 | `DATE_OUT_OF_RANGE` | `date > today + 60` |
| 403 | `FORBIDDEN` | 预约不属于当前顾客 |
| 404 | `NOT_FOUND` | 预约不存在 |
| 409 | `INVALID_STATE` | 状态非 `confirmed`，或 `now >= starts_at` |
| 409 | `SLOT_TAKEN` | 目标时段被占 |

**改期时间门限是 `now < starts_at`，不适用 2 小时取消窗。** 刻意非对称：改期保住订单，取消不保。

- 改期**保持原 `agreed_price_minor` 与原时长**，不读服务当前值。
- 失败时原预约与全部旧占用必须完好无损。
- 实现为「删旧占用 + 建新占用 + 更新 `starts_at`/`ends_at`」的单事务。

### 4.8 发型师

成功 POST 一律 303 回 `/staff/schedule`（保留查询参数 `date`）。

| 方法 | 路径 | 请求 | 成功前置条件 |
|---|---|---|---|
| GET | `/staff/schedule` | `date?`（默认今天） | — |
| POST | `/staff/appointments/<id>/arrive` | `csrf_token` | `confirmed` 且 `appointment.stylist_id == current_user.id` |
| POST | `/staff/appointments/<id>/complete` | `csrf_token` | 同上，且 `now >= starts_at` |
| POST | `/staff/appointments/<id>/no-show` | `csrf_token` | 同上，且 `now >= starts_at` |

| 状态 | 错误码 | 条件 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | `date` 格式错 |
| 403 | `FORBIDDEN` | 非 stylist 角色，或（对 `/staff/*` 命名空间）角色不符 |
| 404 | `NOT_FOUND` | 预约不存在 |
| 409 | `INVALID_STATE` | 状态非 `confirmed`；或 complete/no-show 时 `now < starts_at`；或重复 `arrive` |

- `arrive` 无时间门限（可提前记录到店），但**只能成功一次**；写入 `arrived_at = 服务器当前时间`。
- 预约不属于当前发型师 → `403 FORBIDDEN`。
- 管理员**不得**代替发型师执行这三个动作。
- 迟到只记录 `arrived_at`，**不自动顺延后续预约**。

### 4.9 管理员

统一模式：`GET <资源>` 列表、`GET <资源>/new` 新建表单、`POST <资源>/new` 创建、`GET <资源>/<id>/edit` 编辑表单、`POST <资源>/<id>/edit` 更新、`POST <资源>/<id>/toggle` 切换 `is_active`、`POST <资源>/<id>/delete` 删除。成功写 POST 一律 303 回列表。

| 资源 | 字段 | 说明 |
|---|---|---|
| 服务 | `name, description, price, duration_minutes, required_workstation_type, is_active` | `price` 表单为两位小数字符串，服务端转 `price_minor` |
| 技能 | `stylist_id, service_id` | 复合键定位解除，**不虚构 `/id/delete`**；无 `is_active` |
| 工位 | `label, workstation_type, is_active` | |
| 班次 | `stylist_id, work_date, start_time, end_time` | |
| 休息与请假 | `stylist_id, date, start_time, end_time, reason` | 表单拆为 date + time，服务端合并成 `starts_at`/`ends_at` 两个 DateTime |
| 总览 | `date?, stylist_id?, status?` | 只读 |

失败：字段错误 400 `VALIDATION_FAILED`；CSRF 400 `CSRF_FAILED`；非 admin 403 `FORBIDDEN`；资源不存在 404 `NOT_FOUND`。

**运营修改保护**：任何可能使未来 `confirmed` 预约失效的修改（改时长、停用服务或工位、缩短或删除班次、新增或扩大休息区间），必须先检查再保存。

冲突时 → `409 AFFECTED_APPOINTMENTS`，响应体列出受影响预约的 `id` 列表与数量，**不自动处理任何预约**。管理员必须先显式改期或取消那些预约，才能落这条修改。

被预约引用过的记录一律**停用而非删除**，以保留历史外键。

`GET /admin/overview` 响应：

```json
{
  "filters": {"date": "2026-11-20", "stylist_id": null, "status": null},
  "stats": {"total": 12, "confirmed": 7, "completed": 3, "cancelled": 1, "no_show": 1},
  "appointments": [ /* §5.2 */ ]
}
```

参数非法 → 400 `VALIDATION_FAILED`。

---

## 5. 字段字典

### 5.1 服务

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | |
| `name` | string | |
| `description` | string | 可为空字符串 |
| `price` | string | `"180.00"`，两位小数 |
| `duration_minutes` | int | 15–240，15 的倍数 |
| `required_workstation_type` | string | `chair` \| `colour` |
| `is_active` | bool | |

### 5.2 预约

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | |
| `customer_id` / `customer_name` | int / string | `customer_name` 在员工端与管理端必带 |
| `stylist_id` / `stylist_name` | int / string | |
| `service_id` / `service_name` | int / string | |
| `workstation_id` / `workstation_label` | int / string | |
| `starts_at` / `ends_at` | string | `YYYY-MM-DDTHH:MM` |
| `price` | string | `agreed_price_minor` 的两位小数字符串形式 |
| `arrived_at` | string \| null | `YYYY-MM-DDTHH:MM`，未到店为 `null` |
| `status` | string | 见 §6 |
| `can_cancel` / `can_reschedule` | bool | 仅在顾客端"我的预约"出现，供按钮显隐 |

### 5.3 表单 → 模型转换（唯一允许的映射）

| 表单字段 | 模型列 | 规则 |
|---|---|---|
| `price` | `service.price_minor` | `price_to_minor()` |
| `date` + `start_time` + `end_time`（休息/请假） | `unavailability.starts_at` / `ends_at` | 合并为 `DateTime` |

其余字段名与列名完全一致，**不得建立映射层**。

---

## 6. 枚举

| 名称 | 取值 | 说明 |
|---|---|---|
| `role` | `customer` \| `stylist` \| `admin` | |
| `status` | `confirmed` \| `cancelled` \| `completed` \| `no_show` | |
| `workstation_type` | **`chair` \| `colour`** | 注意是 `colour`，不是 `colouring`；`service.required_workstation_type` 与 `workstation.workstation_type` 共用此域 |
| `reason` | `break` \| `leave` | |

**枚举域必须在数据库层加 CHECK 约束**（`user.role`、`appointment.status` 已有，`workstation_type` 与 `reason` 待补，见 §12.3）。

---

## 7. 错误码字典

| 错误码 | HTTP | 触发条件 | 启用 |
|---|---|---|---|
| `VALIDATION_FAILED` | 400 | 字段缺失/格式/范围/业务输入校验 | 是 |
| `CSRF_FAILED` | 400 | token 缺失、无效、过期 | 是 |
| `AUTH_REQUIRED` | 401 | JSON 未登录或会话失效 | 是 |
| `FORBIDDEN` | 403 | 已登录但角色不符，或资源不属于当前用户 | 是 |
| `NOT_FOUND` | 404 | 资源真正不存在 | 是 |
| `SLOT_TAKEN` | 409 | 创建/改期最终占用冲突 | 是 |
| `INVALID_STATE` | 409 | 状态流转非法、重复终态操作、时间前置不满足 | 是 |
| `AFFECTED_APPOINTMENTS` | 409 | 运营修改会作废未来预约 | 是 |
| `DATE_OUT_OF_RANGE` | 400 | 日期超出 60 天窗口（`date > today + 60`） | 是 |
| `CANCEL_WINDOW_CLOSED` | 409 | `starts_at - now ≤ 2 小时` | 是 |
| `SERVER_ERROR` | 500 | 未捕获异常 | 是 |

**无保留码。** §7 表中全部 11 个错误码均已启用，调用方按 `error` 字段分支。

### 7.1 HTTP 状态码语义

| 状态 | 语义 |
|---|---|
| 200 | 成功（GET；查询型 API 成功；**空结果也是 200**） |
| 302 | 临时重定向：未登录 GET；账号类 POST 成功 |
| 303 | PRG：业务类 POST 成功 |
| 400 | 请求错误（字段、格式、范围、CSRF） |
| 401 | JSON 未认证 |
| 403 | 已认证但无权 |
| 404 | 资源不存在 |
| 405 | 方法不允许 |
| 409 | 状态或资源冲突 |
| 500 | 服务器错误 |

### 7.2 冲突后的客户端行为

- **不自动重试、不静默换工位、不静默改时间。**
- `SLOT_TAKEN`：提示 → 重新 `GET /api/slots` → 保留 `service_id`/`stylist_id`/`date`（改期保留 `appointment_id`/`date`）。
- 改期冲突：原预约与旧占用必须完好，用户回到原状态。

---

## 8. 权限

### 8.1 矩阵

| 资源 / 动作 | customer | stylist | admin |
|---|---|---|---|
| 服务列表与详情 | 读 | 读 | 读 + 写 |
| `GET /api/slots` | 读（本人上下文） | 禁 | 禁 |
| 创建预约 | 写 | 禁 | 禁 |
| 自己的预约 | 读 / 改期 / 取消 | 读¹ | 读 + 作废 |
| 他人预约 | 403 | 403 | 读 |
| `/staff/schedule` | 禁 | 读（本人）¹ | 禁 |
| 到店 / completed / no_show | 禁 | 写¹ | 禁 |
| 技能 / 工位 / 班次 / 休息 | 禁 | 读 | 读 + 写 |
| `/admin/overview` | 禁 | 禁 | 读 |

¹ 仅限 `appointment.stylist_id == current_user.id`。

### 8.2 判定顺序（服务端必须按此顺序）

```text
1. 未登录？             → 401 (JSON) / 302 (HTML)
2. 角色不匹配命名空间？  → 403 FORBIDDEN
3. 资源不存在？         → 404 NOT_FOUND
4. 资源不属于当前用户？  → 403 FORBIDDEN
5. 状态/时间前置不满足？ → 409 INVALID_STATE
```

服务层必须**再校验一次归属**，不能只依赖视图装饰器。

> 说明：本规格采用「越权一律 403」，与现有 `auth.py` 的 `abort(403)` 和现有测试一致。不采用"越权返回 404 隐藏存在性"的方案——本项目资源无敏感性，一致性优先。

---

## 9. 状态机

```text
                 ┌──────────────► completed   (stylist, now >= starts_at)
confirmed ───────┼──────────────► no_show     (stylist, now >= starts_at)
                 └──────────────► cancelled   (customer 取消 / admin 作废)
```

| 规则 | 说明 |
|---|---|
| 只有 `confirmed` 可被改动 | 改期、取消、到店、结果标记都要求 `confirmed` |
| 终态不可流转 | 再操作 → 409 `INVALID_STATE` |
| 取消不删记录 | 改 `status` + 删除全部占用行 |
| 快照不重写 | `agreed_price_minor`、`ends_at`、`arrived_at` 在状态变化时保持不变 |

---

## 10. 并发与事务

- **唯一约束是最终裁定者**：`UNIQUE(stylist_id, slot_start)`、`UNIQUE(workstation_id, slot_start)`。
- 应用层校验失败 → 400 或"该时段不可选"；唯一约束冲突 → 409 `SLOT_TAKEN`。
- 预约与全部占用行**同一事务**提交或回滚；失败后库内不得残留任何行。
- 15 分钟网格：60 分钟服务 = 4 行 `slot_allocation`（`start`, `+15`, `+30`, `+45`）。
- 捕获 `IntegrityError` → `rollback` → 抛 `SlotTaken`。
- **不做自动重试**（重试会挑另一个工位，用户没同意）。
- 背靠背允许（A.end == B.start），重叠不允许。
- 并发验收：20 个并发请求打同一时段 → **恰好 1 个成功、19 个 409**，库中该 60 分钟预约占用行恰为 4 行。

---

## 11. 幂等性

本系统**没有幂等写接口**。任何写操作的重复提交都必须被显式拒绝，不得静默成功。

| 重复操作 | 响应 |
|---|---|
| 重复 `cancel` | 409 `INVALID_STATE` |
| 重复 `arrive` | 409 `INVALID_STATE` |
| 重复 `complete` / `no-show` | 409 `INVALID_STATE` |
| 改期到与当前完全相同的时段 | 400 `VALIDATION_FAILED` |
| 重复 `POST /book` 同一时段 | 第二次 409 `SLOT_TAKEN` |

前端不得自动重试任何 POST；重试必须由用户重新确认。

---

## 12. 文件归属与注册约定

### 12.1 归属表（并行开发的防撞车约定，必须遵守）

| 文件 / 目录 | 唯一负责人 | 说明 |
|---|---|---|
| `app.py` | **B**（组长指定，D1） | 其他人**不得修改**；只需交付自己蓝图的对象名 |
| `models.py` | B | 其他人不得改 |
| `auth.py` | B | |
| `responses.py`、`money.py` | B | 其他人只调用，不改 |
| `seed.py` | B | 场景扩充需求提给 B |
| `booking.py`、`availability.py` | A | 与 `models.py` 同级 |
| `customer.py` | C | 与 `auth.py` 同级 |
| `staff.py`、`admin.py` | D | 与 `auth.py` 同级 |
| `templates/base.html` | **B**（D1） | 由 `templates/auth/base.html` **上移一次**，之后三端共用 |
| `templates/customer/*` | C | |
| `templates/staff/*`、`templates/admin/*` | D | |
| `templates/errors/*` | B | |
| `static/css/app.css` | C | D 直接复用，不新建 |
| `static/js/*` | C | |
| `tests/test_auth.py`、`test_contracts.py` | B | |
| `tests/test_booking_rules.py` | A | |
| `tests/test_customer.py`、`test_staff_admin.py` | C / D | 各自新建 |

### 12.2 注册约定

```python
# app.py —— 只有 B 改这一段
from auth import auth
from customer import customer      # C 交付
from staff import staff            # D 交付
from admin import admin            # D 交付

app.register_blueprint(auth)
app.register_blueprint(customer)
app.register_blueprint(staff)
app.register_blueprint(admin)
```

- 每个蓝图模块必须导出一个名为 `customer` / `staff` / `admin` 的 `Blueprint` 对象，`url_prefix` 在模块内定义。
- C / D **不提交 `app.py` 的改动**，只在消息里告知蓝图对象名。
- 模板统一 `{% extends "base.html" %}`，不得 import `auth/base.html`。

### 12.3 需要 B 执行的 3 条约束

```python
# service
db.CheckConstraint("required_workstation_type IN ('chair','colour')", name="ck_service_ws_type")
# workstation
db.CheckConstraint("workstation_type IN ('chair','colour')", name="ck_workstation_type")
# unavailability
db.CheckConstraint("reason IN ('break','leave')", name="ck_unavailability_reason")
```

目的：把枚举域写进数据库，防止 `colouring` / `coloring` / `chair ` 之类的值进库。加完需重建库（见 §12.4）。

### 12.4 数据库初始化

本项目**不使用迁移工具**。`seed.py` 使用 `db.metadata.create_all()`。

schema 变更后，全组统一执行：

```powershell
Remove-Item instance\salon.sqlite3 -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m flask --app app seed
```

`instance/` 已在 `.gitignore` 中，不进版本库。**任何人不许提交 `.sqlite3` 文件。**

### 12.5 运行环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app seed
.\.venv\Scripts\python.exe -m flask --app app run
```

不新增 `requirements.txt` 之外的依赖。

---

## 13. A 暴露给 C/D 的函数签名

A 必须严格按此签名导出。C/D 依赖这些签名写路由，**不得各自直接写事务逻辑**。

```python
# booking.py
class SlotTaken(Exception):
    """占用冲突，由唯一约束触发。视图层映射为 409 SLOT_TAKEN。"""

class InvalidState(Exception):
    """状态或时间前置不满足。视图层映射为 409 INVALID_STATE。"""

class ValidationFailed(Exception):
    def __init__(self, field: str, message: str): ...

def create_appointment(
    customer_id: int,
    service_id: int,
    stylist_id: int,
    date: datetime.date,
    start: datetime.time,
) -> Appointment:
    """创建 confirmed 预约并占用全部 15 分钟格。
    服务端计算 ends_at、agreed_price_minor、workstation_id。
    违反 §4.4 的任一输入规则抛 ValidationFailed；
    占用冲突抛 SlotTaken（事务已回滚，库内无残留）。"""

def reschedule(
    appointment_id: int,
    date: datetime.date,
    start: datetime.time,
) -> Appointment:
    """在同一事务内替换全部占用并更新 starts_at/ends_at。
    保持原 agreed_price_minor 与原时长。
    失败时原预约与旧占用必须完好。"""

def cancel(appointment_id: int) -> None:
    """status = cancelled 并删除全部占用行，同事务。
    改期、取消都必须自己再校验归属、状态与时间前置。"""

# availability.py
def available_slots(
    service_id: int,
    stylist_id: int,
    date: datetime.date,
    now: datetime.datetime | None = None,
) -> tuple[list[datetime.time], str | None]:
    """返回 (升序时段列表, empty_reason)。empty_reason 为 None 表示非空。
    now 参数仅用于测试注入，生产传 None 表示取服务器当前时间。"""

def available_slots_for_reschedule(
    appointment_id: int,
    date: datetime.date,
    now: datetime.datetime | None = None,
) -> tuple[list[datetime.time], str | None]:
    """改期模式的时段查询。从原预约派生 service_id/stylist_id/时长，
    排除该预约自身旧占用。只读，不写任何记录。"""

def blocking_appointments(
    *,
    service_id: int | None = None,
    workstation_id: int | None = None,
    stylist_id: int | None = None,
    interval: tuple[datetime.datetime, datetime.datetime] | None = None,
) -> list[int]:
    """运营修改保护（§6.2 / §4.9）。返回会被该修改作废的未来 confirmed 预约 ID 列表。
    空列表表示可以保存；非空时视图层返回 409 AFFECTED_APPOINTMENTS 并列出这些 ID。

    语义（按传入的选择器判定，只考虑 starts_at > now 且 status='confirmed' 的预约）：
      service_id       → 引用了该服务的预约（停用服务、改时长前调用）
      workstation_id   → 引用了该工位的预约（停用或改类型前调用）
      stylist_id + interval → 与该时间区间重叠的预约
                             （缩短/删除班次、新增/扩大休息请假前调用）
    只读，不修改任何记录。"""
```

**调用约定**：

- C/D 的视图只做「取参数 → 调函数 → 翻错误码 → 重定向/渲染」，**不写可用性算法、不写事务**。
- C/D 捕获这三个异常并映射为 409/409/400，不直接暴露异常信息给浏览器。
- `available_slots` 返回 `empty_reason` 为 `None` 且 `slots` 为空，在契约上视为 `ALL_TAKEN`（防御性）。
- D 的每个管理端写操作，**必须在保存前调用 `blocking_appointments()`**，结果非空则拒绝保存。这是 §4.9 运营修改保护的唯一实现方式，不得在路由里自己拼查询。

---

## 14. 验收断言（契约条款 → 可执行断言）

每条都必须有真实 HTTP 请求证据。

| 编号 | 场景 | 断言 |
|---|---|---|
| V-01 | 未登录访问 `/book` | 302，Location 为 `/auth/login?next=/book` |
| V-02 | 未登录请求 `/api/slots`（Accept: json） | 401 `AUTH_REQUIRED`，含 `login_url`，不含 next |
| V-03 | POST 不带 csrf_token | 400 `CSRF_FAILED` |
| V-04 | `next=https://evil.example/x` | 登录后回 `/` |
| V-05 | `next=//evil.example/x` | 登录后回 `/` |
| V-06 | `next=/a/../admin` | 登录后回 `/` |
| V-07 | customer 访问 `/admin/services` | 403 `FORBIDDEN` |
| V-08 | customer 访问他人 `/appointments/<id>/cancel` | 403 `FORBIDDEN` |
| V-09 | stylist 访问 `/staff/appointments/<他人预约>/complete` | 403 `FORBIDDEN` |
| V-10 | `/api/slots` 同时传 `service_id` 与 `appointment_id` | 400 `VALIDATION_FAILED` |
| V-11 | `/api/slots` 改期模式传非 confirmed 预约 | 409 `INVALID_STATE` |
| V-12 | `/api/slots` 当日无班次 | 200，`slots == []`，`empty_reason == "NO_SHIFT"` |
| V-13 | 服务需 `colour` 台，只有 chair 空闲 | 200，`empty_reason == "NO_WORKSTATION"` |
| V-14 | 提交 `start=09:10` | 400 `VALIDATION_FAILED` |
| V-15 | 提交过去时间 | 400 `VALIDATION_FAILED` |
| V-16 | 10:00–11:00 与 11:00–12:00 同一发型师 | 两单都成功 |
| V-17 | 10:00–11:00 与 10:30–11:30 同一发型师 | 第二单 409 `SLOT_TAKEN` |
| V-18 | 同理发师同时刻两单 | 409 `SLOT_TAKEN`，第一单仍 confirmed |
| V-19 | 同工位同时刻两单（不同发型师） | 409 `SLOT_TAKEN` |
| V-20 | 让 slot 插入失败 | `appointment` 也不存在（回滚） |
| V-21 | 60 分钟服务的占用行数 | 恰为 4 |
| V-22 | 20 并发请求同一时段 | 恰 1 成功、19 个 409，占用行恰 4 |
| V-23 | 移除两个唯一约束后重跑 V-22 | 出现多于 1 个成功（证明约束在兜底），随后恢复 |
| V-24 | 取消后查同一时段 | 该时段重新出现在 `slots` |
| V-25 | 重复取消 | 409 `INVALID_STATE` |
| V-26 | 对 completed 改期 | 409 `INVALID_STATE` |
| V-27 | 改期到已占时段 | 409 `SLOT_TAKEN`，原预约与旧占用不变 |
| V-28 | 改价后查历史预约 | `price` 不变 |
| V-29 | 同一预约 `arrive` 两次 | 第二次 409 `INVALID_STATE` |
| V-30 | admin 调 `/staff/appointments/<id>/complete` | 403 `FORBIDDEN` |
| V-31 | 停用被未来预约引用的工位 | 409 `AFFECTED_APPOINTMENTS`，含预约 id 列表 |
| V-32 | 任意响应中的 `price` | 恒为两位小数字符串，无 `price_minor` 字段 |
| V-33 | 任意时刻字段 | 匹配 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$` |
| V-34 | 账号类 POST 成功 | 302 |
| V-35 | 业务类 POST 成功 | 303 |
| V-36 | `flask seed` 连跑两次 | 数据条数与列值不变 |
| V-37 | `GET /auth/logout` | 405 |
| V-38 | 开始前 1 小时取消 | 409 `CANCEL_WINDOW_CLOSED`，预约与占用不变 |
| V-39 | 开始前 1 小时改期 | **成功**（改期无 2 小时窗），303 |
| V-40 | 预约日期 = today + 61 | 400 `DATE_OUT_OF_RANGE` |
| V-41 | 预约日期 = today + 60 | **成功**（第 60 天含） |

---

## 15. 已决项（组长已拍板，全部生效）

### D1 集成负责人 → **B**

`app.py` 与 `templates/base.html` 由 B 独占修改。其他人的蓝图与模板自行开发，只向 B 交付蓝图对象名（§12.2）。

B 因此同时持有全部共享文件（`models.py`、`auth.py`、`responses.py`、`money.py`、`seed.py`、`app.py`、`base.html`）。B 的共享文件工作必须在其他人接入前完成，具体是：§12.3 的 3 条约束、`base.html` 上移、注册块预留 4 行。其余部分已在 §1 基线中完成。

### D2 时间窗口规则 → **全部启用**

| 规则 | 生效行为 | 契约条款 |
|---|---|---|
| 取消需在开始前 2 小时以上 | `409 CANCEL_WINDOW_CLOSED` | §4.6、§7 |
| 预约日期不超出 today + 60 天（第 60 天含） | `400 DATE_OUT_OF_RANGE` | §4.2、§4.4、§4.7、§7 |
| 改期**不**受 2 小时窗限制，只要 `now < starts_at` | 正常改期 | §4.7 |

验收见 V-38 至 V-41。

**演示数据要求**：所有演示预约必须落在 60 天窗口内；用于演示"取消成功"的预约，开始时间必须距离当前 2 小时以上；用于演示"取消被拒"的预约，开始时间必须距离当前 2 小时以内。

---

## 16. 任务分解与提示词模板

### 16.1 执行顺序

依赖关系：`B-0` 是所有人的前置；`A-1` 解锁 C 的时段查询；`A-2`/`A-3` 解锁 C 的写操作与 D 的管理端保护。

```text
B-0 ──┬─► A-1 ──► A-2 ──► A-3 ──┐
      │                          ├─► C-4
      ├─► C-1 ──► C-2 ──► C-3 ───┘
      │
      └─► D-1 ──► D-2 ──► D-3 ──► D-4
```

| 步 | 负责人 | 内容 | 依赖 | 对应验收 |
|---|---|---|---|---|
| B-0 | B | §12.3 三条约束、`base.html` 上移、`app.py` 预留注册位 | 无 | §0.6 全项 |
| A-1 | A | `availability.py` 两个函数 | B-0 | V-12 V-13 |
| A-2 | A | `create_appointment` + 三个异常 | A-1 | V-16～V-22 |
| A-3 | A | `reschedule` / `cancel` / `blocking_appointments` | A-2 | V-24～V-28、V-31 |
| C-1 | C | `/services` 列表与详情 | B-0 | §4.3 |
| C-2 | C | `/my-appointments` + 两个可用性标志 | B-0 | §4.5 |
| C-3 | C | `/book` 表单 + `fetch /api/slots` 渲染 | A-1 | V-10～V-15 |
| C-4 | C | 三个写路由 | A-2 A-3 | V-17～V-25、V-27 |
| D-1 | D | 员工日程 + arrive/complete/no-show | B-0 | V-29 V-30 |
| D-2 | D | 服务 / 技能 / 工位维护 | A-3 | V-31 |
| D-3 | D | 班次 / 休息请假维护 | A-3 | V-31 |
| D-4 | D | 运营总览 | D-2 D-3 | §4.9 |

每一步完成即交付一次，不得攒着一起交。

### 16.2 提示词模板

**通用前缀（所有任务都要带）**

> 你先完整读《COMP3019J 开发前统一规格 v1.0（AI 执行版）》再动手。
> 硬约束：只改 §12.1 归属表里属于你的文件；不改 `app.py`、`models.py`、`responses.py`、`money.py`；字段名以 §5 为准；服务端重新校验一切；错误码只用 §7 表内的；不新增依赖。
> 交付格式见 §16.3，自检清单见 §16.4。

**B-0**

> 我负责 B 的收尾，只做三件事：
> 1. 按 §12.3 给 `models.py` 补三条枚举 CHECK 约束。
> 2. 把 `templates/auth/base.html` 上移为 `templates/base.html`，并把 `auth/` 下的模板改成 `{% extends "base.html" %}`。
> 3. 在 `app.py` 的注册区按 §12.2 预留 `customer` / `staff` / `admin` 三行，先注释掉。
> 加完约束要重建库（§12.4）并重跑全部现有测试。不得改动任何业务逻辑。

**A**

> 我负责 A：数据与预约规则。
> 只允许创建/修改 `booking.py`、`availability.py`、`tests/test_booking_rules.py`。
> 必须严格按 §13 导出 6 个函数与 3 个异常，**签名与 docstring 语义不得改动**。
> 核心要求：占用最终由 `slot_allocation` 的两个唯一约束裁定；创建/改期/取消均为单事务；捕获 `IntegrityError` 后 `rollback` 并抛 `SlotTaken`；**不做自动重试**；失败后库内不得残留任何行。
> 改期必须保持原 `agreed_price_minor` 与原时长，并排除自身旧占用；`blocking_appointments` 只读。
> 不得写路由、不得写模板、不得改 `models.py`。

**C**

> 我负责 C：顾客端。
> 只允许创建/修改 `customer.py`、`templates/customer/*`、`static/css/app.css`、`static/js/*`、`tests/test_customer.py`。
> 时段数据**只来自** `GET /api/slots`，前端不得计算可约性、不得自行过滤或补全。
> 写操作必须带 CSRF（fetch 用 `X-CSRFToken`，值取自 `<meta name="csrf-token">`）。
> `409 SLOT_TAKEN` 时保留用户已选并重新拉取时段，不自动重试。
> 按钮显隐用服务端给的 `can_cancel` / `can_reschedule`，但服务端仍会重新校验。
> 不得改 `app.py`（蓝图对象名告知 B）、不得改 `booking.py` / `availability.py`、不得改 `models.py`。

**D**

> 我负责 D：员工端与管理端。
> 只允许创建/修改 `staff.py`、`admin.py`、`templates/staff/*`、`templates/admin/*`、`tests/test_staff_admin.py`。
> 发型师只能操作 `appointment.stylist_id == current_user.id` 的预约；管理员**不得**代替发型师标记 completed / no_show。
> 每个管理端写操作在保存前**必须**调用 `blocking_appointments()`，结果非空则返回 `409 AFFECTED_APPOINTMENTS` 并列出预约 ID。
> 被预约引用过的记录一律停用而非删除。
> 不得改 `app.py`、不得重算可用性、不得改 `models.py`。

### 16.3 交付格式

```text
任务：<B-0 / A-1 / A-2 / C-3 / D-2 ...>
改动：<文件列表>
验证：<命令> → <实际输出摘要，含通过/失败数>
契约变更：<无 / 具体条款编号>
未完成：<列表 或 无>
```

### 16.4 每次交付前的自检

- [ ] 只碰了 §12.1 归属表里属于自己的文件
- [ ] 新增或修改的字段都能在 §5 找到
- [ ] 新出现的错误码都在 §7 表内
- [ ] 该步对应的 V- 断言全部跑通，且都是真实 HTTP 请求
- [ ] 没有把「待接入」写成「已完成」

---

## 附录：本规格相对既有材料的变更摘要

| 项 | 既有材料 | 本规格 | 理由 |
|---|---|---|---|
| `workstation_type` 取值 | 文档写 `colouring`，代码写 `colour` | **统一为 `colour`** | 靠向已实现代码，避免改数据 |
| `created_at` | 三方文档有，代码无 | **从契约删除** | 无任何页面使用 |
| `Workstation.label` | 原设计要 UNIQUE | **不设 UNIQUE** | 靠向代码；补约束的收益低于改动成本 |
| `password2` | 原契约要求 | **删除** | 靠向代码；不影响质量 |
| `remember` / 30 分钟空闲超时 | 原契约要求 | **删除** | 靠向代码；不影响质量 |
| 越权状态码 | 原开工包要求一律 404 | **403** | 靠向代码与现有测试 |
| POST 成功码 | 原契约一律 303 | **账号类 302 / 业务类 303** | 靠向代码与现有测试 |
| `/health` | 原开工包 F20 要求 | **不做** | O 级；无实际用途 |
| 2 小时窗 / 60 天窗 | 待确认 | **全部启用**（§15-D2） | 组长已拍板 |
| 改期时间门限 | 未定义 | **`now < starts_at`** | 补空白 |
| 运营修改保护 | 无 | **`AFFECTED_APPOINTMENTS`** | 补空白 |
| 时段查询双模式 | 无改期上下文 | **新建/改期互斥** | 补空白 |
| 幂等性 | 未定义 | **§11** | 补空白 |
| 文件归属 | 无 | **§12.1** | 防并行撞车 |
| A 的函数签名 | 只说"稳定签名" | **§13 完整签名** | 解 C/D 阻塞 |
