# Massive 主数据源与 Yahoo 降级设计

## 意图

将盘前趋势扫描器从 Yahoo 单一数据源改造成可降级的数据提供层。定时任务优先使用已配置的 Massive API 获取行情与新闻；当套餐无权限、接口失败或数据不完整时，仅对受影响维度回退 Yahoo，保证企业微信盘前报告能够继续生成。

## 目标

- 日线与盘前分钟线优先由 Massive 提供。
- 新闻优先由 Massive 提供。
- 当前套餐不支持的基本面与期权维度继续使用 Yahoo。
- Massive 请求异常、限流、超时、空数据或返回结构异常时自动回退 Yahoo。
- 报告和评分模型保持数据源无关，不改变现有交易筛选规则。
- GitHub Actions 安全读取 `MASSIVE_API_KEY`，日志不泄露密钥或完整请求 URL。
- 每个结果保留实际来源与降级信息，便于排查数据质量。

## 非目标

- 不接入 Massive MCP/AI 插件作为生产运行时；GitHub Actions 使用官方 REST API。
- 不扩展观察池，不改变 SPY、QQQ 和七姐妹的筛选范围。
- 不改变日线顺势、盘前确认、风险评分和企业微信图片布局的业务含义。
- 不通过缺省值伪造当前套餐没有权限的期权或财务数据。
- 本次不购买或升级 Massive 套餐。

## 反目标

- Massive 任一接口失败导致整次扫描中断。
- Yahoo 回退悄悄发生、报告与日志完全不可追踪。
- 为了统一接口而降低已有日线完整性、时区、上一交易日校验或盘前新鲜度校验。
- 在代码、测试、日志、文档或 GitHub 工作流中写死 API Key。

## 已验证约束

2026-11-20 使用当前 Massive 账户实测：

- 股票日线聚合：可用，响应状态 `DELAYED`。
- 股票分钟聚合：可用，响应状态 `DELAYED`。
- 标的信息：可用。
- 新闻：可用。
- 期权快照：HTTP 403，当前套餐无权限。
- 财务接口：当前请求不可用，因此不作为首期生产依赖。

盘前报告在美东 08:30 运行。Massive 响应标记为延迟数据，因此实现必须基于返回时间戳进行新鲜度判断；超过现有 `quote_stale_minutes` 阈值时标记为 stale，并允许 Yahoo 提供更新的盘前报价。

## 方案比较

### 方案 A：完全替换 Yahoo

所有维度只使用 Massive。结构简单，但当前套餐缺少期权权限，财务接口也不可用；任何 Massive 故障都会直接影响报告完整性，不采用。

### 方案 B：Massive 主数据源，按维度自动回退 Yahoo（选定）

新增 Massive 客户端与标准提供者，在组合层按请求/维度执行主备切换。行情与新闻优先 Massive，基本面和期权当前直接使用 Yahoo。兼顾数据质量、可用性与未来套餐升级后的替换空间。

### 方案 C：保留 Yahoo，仅增加 Massive 数据对照

风险最低，但不能实现用户要求的替换，且双份数据只用于对照会增加请求与维护成本，不采用。

## 架构

### Massive 客户端

新增一个小型 REST 客户端，统一负责：

- API Key 请求参数或认证头；
- 连接和读取超时；
- 对 429 与 5xx 做有限重试和退避；
- 分页读取；
- 将 HTTP 错误、权限错误、空响应和解析错误转换为稳定的内部异常；
- 错误消息只包含接口类别、状态码和请求标识，不包含密钥与完整 URL。

首期直接使用现有 `requests` 依赖，避免为了少量端点引入额外 SDK 版本耦合。

### 行情提供者

新增 `MassiveMarketData`，实现现有 `daily_history` 和 `premarket_quote` 约定：

- 日线使用股票 aggregate bars，转换为项目现有的 `Open/High/Low/Close/Volume` DataFrame。
- 继续执行 OHLCV 完整性、NaN、上一交易日和至少所需历史长度校验。
- 盘前分钟线只接受美东当日 04:00–09:30、时间不晚于当前时刻的数据。
- 根据返回分钟时间戳计算新鲜度；超过阈值返回 `STALE`。

新增 `FallbackMarketData`：先调用 Massive；若请求失败、数据为空、结构无效或最终结果为 `ERROR/MISSING/STALE`，调用 Yahoo。若 Yahoo 返回更新且有效的数据则使用 Yahoo，否则保留信息量更高的结果。日线 Massive 失败时直接回退 Yahoo。

### 新闻提供者

新增 `MassiveEventNewsProvider`，读取 Massive 新闻，映射为现有事件/新闻证据模型，继续执行时间窗口、去重和负面关键词判断。宏观日历继续使用仓库内本地文件。

新增 `FallbackEventNewsProvider`：Massive 新闻请求失败或没有可用新闻时调用现有 `YahooEventNewsProvider`。最终证据记录 `source=massive` 或 `source=yahoo_fallback`。

### 基本面与期权

首期保持：

- `YahooFundamentalsProvider`
- `YahooOptionsProvider`

它们仍通过现有 provider 接口输出标准模型。未来 Massive 套餐开放对应端点后，可新增实现并复用相同组合方式，不改评分与报告。

### 依赖装配

`main._dependencies` 根据 `MASSIVE_API_KEY` 装配：

- 有 Key：行情与新闻启用 Massive 主源 + Yahoo 降级。
- 无 Key：完整使用 Yahoo，并输出一次不含敏感信息的降级提示；本地开发仍可运行。

`Settings` 新增 Massive Key、基础 URL、请求超时与重试配置。Key 仅从环境变量读取。

### GitHub Actions

发送步骤新增：

```yaml
MASSIVE_API_KEY: ${{ secrets.MASSIVE_API_KEY }}
```

测试步骤不读取真实 Secret，全部使用固定响应。定时任务继续在美东工作日 08:30 运行。

## 数据来源可见性

每次运行输出一行汇总，例如：

```text
providers market=massive news=massive fundamentals=yahoo options=yahoo fallbacks=0
```

发生降级时记录标的、维度、主源错误类别和备用源，不记录 Key、Webhook 或完整 URL。图片报告首期不增加来源文字，避免挤压版面；详细来源保留在运行日志和内部证据中。

## 错误处理

- 401/403：视为当前端点不可用，本次运行直接回退，不重复请求。
- 429/5xx/网络超时：按配置有限重试，失败后回退。
- 200 但空数据、列缺失或时间不合法：视为数据质量失败并回退。
- Massive 与 Yahoo 都失败：保持现有 `DATA_FAILED`、维度错误和报告降级行为。
- 单个标的失败不影响其他标的。

## 测试与验收

- Massive 日线映射、复权字段、时间戳、分页及上一交易日校验。
- Massive 盘前过滤未来/常规时段数据，并正确判断 stale。
- 401、403、429、5xx、超时、空响应和坏结构均不泄露密钥。
- 主源成功时不调用 Yahoo；主源失败或 stale 时只调用必要的备用源。
- Massive 新闻映射、去重、时间窗和负面标签与现有口径一致。
- 无 Key 时全量使用 Yahoo。
- GitHub Actions 静态测试确认发送步骤注入 `MASSIVE_API_KEY`。
- 全量 pytest 通过；使用真实 Key 做一次只读 dry-run，不发送企业微信消息。

## 实现者可决定

- Massive 客户端的文件拆分和内部异常名称。
- DataFrame 转换辅助函数的组织方式。
- 在不改变上述语义的前提下，来源元数据放在现有 evidence detail 还是新增内部运行统计对象。

