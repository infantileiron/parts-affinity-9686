# 远航 · 维保备件联用发现

将维保作业中的备件集合变成可解释的联用规则，让维修策划组核对兼容性后形成备件包方案，并按作业与已签核备件包联合备料。

## 场景和业务模块

远航设备服务的维修策划组负责泵组、压缩机、风机三类设备，现有180张历史作业。每天从维修记录导出 `远航_维保用件_20261115.xlsx`，人工划线找共同用件，再把经验写进指引。三个痛点是重复备件把次数放大、只看一起出现而忽略总体使用率、方案缺少来源证据。上游为实际维保作业；本项目替代集合整理、关联挖掘和兼容性审阅；下游为组长编写作业指引。本项目不管理库存、采购或销售订单。

五模块是作业清单（录入/修订）、阈值配置（异步挖掘）、规则解释（支持度/置信度/提升度）、备件包（来源规则/说明/签核/废止）、联合备料（试算/确认/取消/逐单对账）。实体 Job、MiningRun、AssociationRule、Kit、KittingPlan 都真实持久化；规则按批次单独入表，备件包通过rule_id关联；班组按单挑备件包会重复备料，联备方案把多张作业与多个已签核包联合求解，每单可选多包、用件取并集、逐件对账。

|角色|页面权限|典型动作|
|---|---|---|
|admin|全部，独占审计和签核|签核适用范围、废止备件包|
|analyst|业务读写、挖掘、导出|配置阈值并起草备件包；试算/确认/取消联备方案|
|viewer|全部业务只读、导出|核对来源规则与逐单对账；后端禁止写入/计算|

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18207](http://localhost:18207)，后端 [localhost:19207/docs](http://localhost:19207/docs)，MySQL端口17707。账号为 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。`SEED_DEMO=true` 自动执行种子；手动再跑自然键幂等，不覆盖人工修订。初始3账号、180作业、12类标准备件，无预制计算结果。

## 一天的工作剧本

1. 08:50 viewer 打开YH-1115-001至180，核对泵组作业背景。
2. 09:00 analyst 查看目录：轴承、密封圈、润滑脂、滤芯、垫片、联轴器、皮带、紧固件、叶轮、阀片、传感器、清洗剂。
3. 09:10 录入 `YH-1115-181`，泵组，用件“轴承,润滑脂,密封圈”。
4. 09:20 检查重复用件会去重，不因领了两份润滑脂而计两次事务。
5. 09:30 建立“11月泵组联用复核”，支持度0.15、置信度0.6、提升度1。
6. 09:40 worker完成后刷新，进入规则解释，核对共同作业数和分母。
7. 10:00 选择有业务价值的一条规则，点击起草备件包，写“仅限同规格泵组，核对密封材质和数量”。
8. 10:10 admin签核；10:20 viewer下载 `parts-affinity-<run-id>.json`。
9. 10:30 analyst 打开联合备料，勾选本班组作业与已签核包，携带件种上限设 6，试算得到草案：覆盖 4/6、闲置 5 件，逐单对账核对每单分配包、并集与闲置件，未覆盖单标注“无已签核包提供”或“受携带件种上限约束”。
10. 10:40 确认生效，作业被方案占用；另一班组对同一作业的确认被拒。10:50 取消方案释放占用，重复取消不影响其他方案。

## 联合备料算法与状态机口径

优化目标按字典序：在携带件种上限内，先最多完整覆盖作业（需要件 ⊆ 所分包并集），再最少逐单闲置件总数（Σ|并集−需要件|）。件种全集即12项标准目录，求解器按件集合位掩码精确枚举携带方案（2^|U|），对每个需求集合用子集和DP求任意携带集合下的最小闲置，复杂度与作业数线性；平局按件种少、掩码小取确定解。件种规模超过20时回退贪心近似并在结果中标注 `solver=greedy-fallback`。未覆盖作业逐件解释：该件无已签核包提供（no_approved_kit），或有包含的包但受携带上限约束未携带（over_carry_limit，注明引入该件至少额外占用的件种数）。

方案状态机：草案 draft → 生效 active → 已取消 cancelled。草案不占用作业；确认生效才写入占用（占用表对作业唯一约束，同一作业不会被多个生效方案占用，并发确认由数据库兜底不超占）；取消按方案id精确释放占用，重复取消幂等、绝不误释放其他方案。确认/取消携带幂等键，同键重试返回原结果，不重复占用。试算冻结依据快照（作业/备件包的 revision 与签核状态）并生成指纹；确认时锁定依据行逐条比对，试算之后作业修订或来源包变化（含废止）即拒绝生效并要求重新试算；修订与确认竞争时由行锁序列化，只保留一个一致版本。生效后依据与结果不再变化（冻结依据）；被生效方案占用的作业不可修订、被使用的备件包不可废止，取消方案后解锁。已签核包可经 admin 废止，废止后不再参与联备。

接口：`POST /plans/trial`（试算生成草案）、`GET /plans`、`GET /plans/{id}`（逐单对账）、`POST /plans/{id}/confirm`、`POST /plans/{id}/cancel`、`POST /kits/{id}/revoke`（admin）。试算同步求解（180单/4包约0.2秒），不走队列。

## 算法口径和失败态

Python标准库实现Apriori，最大频繁项集长度3。每张含备件的有效作业是一个事务，parts转集合后计数，空事务排除并记录excluded；有效事务N至少2。每张作业内的重复件不增加支持度。最小计数ceil(N×min_support)，用1e−12容差避免浮点整数边界。

对不相交非空A/B，support=count(A∪B)/N，confidence=count(A∪B)/count(A)，lift=confidence/support(B)。候选由上一层频繁项集连接，先检查所有子集频繁再计数。按提升度、置信度、支持度排序，签名作稳定次序。用户可配置支持度(0,1]、置信度(0,1]、提升度[0,50]，只接受12项标准目录。阈值太高时成功完成但没有规则，页面提示降低阈值或增加同类作业；不伪造规则。样本不足则任务failed。相同来源作业生成稳定checksum；提交即冻结样本，后续修订不改变已有报告。

关联不是必须联换，提升度也不证明因果。备件包用件来自规则并集，人工只能填写名称、适用性和限制；已签核不可覆盖。没有数量推算、设备兼容性数据库或采购动作。

## 工程与目录

|层|实现|
|---|---|
|前端|原生HTML/CSS/ES modules，Nginx|
|后端|Python3.11、FastAPI、SQLAlchemy、PyJWT|
|后台|Redis队列，独立worker执行Apriori，文件心跳|
|数据库|MySQL8.0，Redis7|

恰好frontend/backend/worker/db/redis五服务，全部healthcheck。backend等db/Redis健康，worker额外等backend，frontend等backend。数据库、Redis与计算产物各用命名卷；worker结果在共享`/artifacts`。Nginx `/api/` 转发到后端根路由；Redis和worker不映射宿主端口。`docker compose down -v --remove-orphans` 清理本项目数据。

`backend/src`分routes/controllers/services/models/schemas/middlewares/config/utils/constants；`frontend/src`分api/stores/pages/components/common/hooks/utils/router/constants/types。共用表格、字段、状态标签，表单hooks与HTML转义；请求ID和安全响应头中间件，业务写入审计。首次启动ORM建表，migrations保存实际DDL，不含版本迁移执行器。

本地开发：先起db/redis，backend安装requirements，配置DATABASE_URL/REDIS_URL/JWT_SECRET后 `uvicorn src.main:app --reload`；前端使用Nginx同源代理或本地同源开发代理。环境变量为COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET，见.env.example。当前显式子网10.253.108.0/24用于规避本机默认池耗尽，迁移可调整。演示凭据与JWT密钥部署时需替换。

枚举ROLES/STATES/EQUIPMENT/PARTS/PLAN_STATES分别在后端`src/constants/enums.py`、输入schema及前端`src/constants/enums.js`；实体列见models/entities.py。测试与截图在`../../test-artifacts/gb-3108/`。

后端测试在`backend/tests/`（优化器精确性/字典序目标/联合优于逐单贪心、状态机并发与幂等、依据冻结与竞争一致性），本地运行：`pip install pytest httpx && cd backend && python -m pytest tests/ -q`（测试用SQLite，无需MySQL/Redis）。

已知范围：逐条表单/API录入，无CSV导入/删除/分页；规则单worker计算，最大项集3件，签核在站内完成，无采购、外部通知或自动作业指令；联备按件种对账不推算数量，未覆盖单不被方案占用。Google Fonts离线时回退字体；未做大规模压测。许可证MIT，见LICENSE。
