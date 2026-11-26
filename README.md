# 理发店预约系统

这是 COMP3019J 小组项目的单店理发店预约系统。项目采用 Flask + SQLite + SQLAlchemy，统一接口与数据契约见 [统一规格 docs/spec.md](docs/spec.md)，开发与测试说明见 [AGENTS.md](AGENTS.md)。

**当前进度**：角色 B 底座（八张表、注册登录与权限、精确金额转换、JSON/HTML 错误约定、演示数据）、角色 A（`/api/slots` 与预约/改期/取消事务）和角色 C（服务目录、预约下单、我的预约、改期与取消页面）均已接入；角色 D 的员工端 `/staff/*` 与管理端 `/admin/*` 待接入。`instance/salon.sqlite3` 不纳入版本库。

## 本地启动与验收

### 1. 安装课程项目依赖

先在独立环境中安装依赖，方便组员用同一套 Flask、SQLAlchemy 和表单组件复现。准备 Python 3.10 或更高版本，在项目目录打开 PowerShell 后执行以下命令。`.venv` 将本项目的依赖和电脑上其他 Python 项目隔开。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

如果项目目录已有 `.venv`，先直接执行最后一条命令。显示 `No broken requirements found.` 时，依赖检查通过，可以开始初始化数据库。

### 2. 初始化演示数据库并打开应用

在接调度和页面之前，先验证空数据库能建表并生成一套关系完整的演示数据。种子命令只给空数据库导入数据，因此日常重跑会保留已有的账号和预约。所有演示账号默认共用固定本地演示密码 `SalonDemo123!`（如需自定义，可在运行 `seed` 前设置 8–128 位非空白环境变量 `SEED_PASSWORD`；如果本地已有旧数据库，需先删除 `instance\salon.sqlite3` 再重跑 `seed`）。

```powershell
.\.venv\Scripts\python.exe -m flask --app app seed
.\.venv\Scripts\python.exe -m flask --app app run
```

在浏览器打开 `http://127.0.0.1:5000/`。确认首页可打开、`instance/salon.sqlite3` 已生成，并能用种子账号登录。`admin@example.com` 是管理员，`stylist1@example.com` 和 `stylist2@example.com` 是发型师，`customer1@example.com` 和 `customer2@example.com` 是顾客。它们共用本地演示密码（默认 `SalonDemo123!`，或导入前通过 `SEED_PASSWORD` 指定的密码）。

如需在重启应用后保留浏览器会话，在启动前通过 PowerShell 的 `SECRET_KEY` 环境变量提供你自己生成的随机密钥。应用使用它签名会话与 CSRF 令牌。环境变量缺省时，应用在每次启动时生成临时密钥，重启后要重新登录。

### 3. 用不同角色检查权限

页面接入前先确认同一个浏览器请求会按服务端身份得到对应权限。你可以先注册一个新顾客，查看首页显示的角色，退出后改用演示管理员登录。用管理员打开 `/auth/staff`，创建一个发型师账号，再用新账号登录验证角色。最后切回顾客访问 `/auth/staff`，应返回 `403`。公开注册的角色由服务器固定为顾客，员工账号通过管理员入口创建。

### 4. 运行自动测试

合入各角色模块前先记录 B 的验收结果。测试使用独立 SQLite 测试库，覆盖登录与权限、JSON 401/400/403、安全 next、金额精确转换、模型字段/复合键、预约唯一约束、回滚、取消释放和 seed 全表内容保留。请在项目目录执行并记录末尾的通过数量，交给 D 汇总。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前全量测试为 **Ran 138 tests，OK**（`test_auth.py` 9、`test_contracts.py` 11、`test_booking_rules.py` 68、`test_customer.py` 50）。角色 D 的员工/管理页面测试待接入后补充。

## 课程交付

交接前请亲手复跑并讲清一个案例，例如改期失败时数据库如何还原原预约和原来的时段。课程项目说明第 2 页要求团队对提交内容负责并能解释实现，AI 使用及注明方式以课程和学院的规定为准。
