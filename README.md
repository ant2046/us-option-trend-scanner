# 美股盘前趋势扫描器

在每个美股交易日开盘前约 60 分钟扫描：

`SPY QQQ AAPL MSFT GOOGL AMZN NVDA META TSLA`

程序使用上一完整交易日的日线判断趋势和“回调转强／平台突破”信号，再结合盘前价格标记“允许关注、跳空偏高不追、信号失效或数据异常”。行情与新闻优先读取 Massive，失败或数据陈旧时自动降级到 Yahoo；当前套餐不支持的基本面和期权仍由 Yahoo 提供。技术规则仍是唯一入选条件；入选后再补充市场环境、基本面、事件消息和期权可交易性，生成观察分与风险标签，最后通过企业微信群机器人推送适合手机阅读的图片。它不会连接券商或自动下单，也不推荐具体期权合约。

## 筛选规则

- 最近收盘价高于 MA20，且 MA20 高于 5 个交易日前；
- 回调转强：最近 5 日最低价进入各自 MA20 上下 2%，最新收盘重新站上前一日最高价；
- 平台突破：最新收盘突破此前 10 日高点，成交量不低于此前 20 日均量的 1.2 倍；
- 盘前涨幅超过 3% 标记为不追；盘前跌破 MA20 或参考失效位则标记为失效。

## 五维观察分与风险标签

每个候选按以下五个维度展示；新增维度只帮助判断质量与风险，不会把原技术候选过滤掉：

- 技术结构 `30` 分：趋势、均线结构、高低点、回调转强和平台突破；
- 市场环境 `20` 分：SPY/QQQ 趋势、20 日相对强弱和波动率位置；
- 基本面质量 `20` 分：营收、利润、现金流、利润率和负债；SPY/QQQ 显示不适用；
- 事件消息 `15` 分：财报、重要宏观事件和规则命中的负面标题；
- 期权可交易性 `15` 分：14–45 天到期、接近平值合约的价差、持仓量、成交量和当前 IV。

报告同时显示 `已得分/可得分` 和数据完整度。某项数据缺失时显示 `--`，不会按零分扣分；只有完整度达到 70% 才显示归一化的 0–100 综合观察分。该分数不是历史胜率、上涨概率或收益预测，候选顺序仍以原技术排序为准。

风险标签独立于分数展示，避免高分掩盖风险：

- 高风险：3 天内财报、重大宏观事件日、盘前信号失效、期权无有效报价；
- 谨慎：盘前跳空偏高、期权价差偏大或流动性偏低、波动率异常、近期负面标题；
- 信息：基本面、消息或期权数据暂缺。

补充数据由独立提供者并发获取。任一免费接口超时、限流、字段缺失或格式变化时，只将对应维度降级为“数据暂缺”，技术报告仍会生成并发送。宏观事件优先读取在线日历，失败后使用仓库内的 `data/macro_events.json`；若本地日历已过有效期，报告会标记“宏观日历可能已过期”。可用 `MACRO_CALENDAR_URL` 覆盖在线日历地址。

## 本地运行

验证期间 GitHub Actions 在纽约时间工作日 08:30 只执行 dry-run（休市跳过取数），不配置企业微信 Webhook。每次运行的 Artifacts 保留 90 天，JSON 包括候选、评分、风险标签及候选和 SPY/QQQ 的报价来源、时间、请求时的报价年龄和回退原因。报价年龄不等于供应商的固定延迟。手动触发同样只运行 dry-run；下面的本地发送命令不受影响。

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest -q
python -m market_scanner.main --dry-run
```

`--dry-run` 是默认模式，只打印报告，不需要企业微信地址。

启用 Massive 主数据源需要环境变量 `MASSIVE_API_KEY`；未配置时程序自动使用 Yahoo，不影响本地开发：

```powershell
$env:MASSIVE_API_KEY="在 Massive 后台生成的密钥"
python -m market_scanner.main --dry-run
```

本机真实发送前，需要提供企业微信地址：

```bash
# PowerShell
$env:WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
python -m market_scanner.main --send
```

图片默认在 Windows 使用微软雅黑，在 GitHub Actions 使用 Noto Sans CJK。其他系统可以通过 `SCANNER_FONT_PATH` 指定支持中文的 `.ttf` 或 `.ttc` 字体。候选较多时会自动拆分为多张图片并按顺序发送；如果当天没有候选标的，机器人仍会发送一张“今日无符合条件标的”的图片。

## 配置企业微信群机器人

1. 在目标企业微信群中添加“群机器人”。
2. 复制机器人 Webhook 地址，不要提交到仓库。
3. 打开 GitHub 私有仓库的 **Settings → Secrets and variables → Actions**。
4. 新建 Repository secret：`WECOM_WEBHOOK_URL` 保存完整 Webhook 地址，`MASSIVE_API_KEY` 保存 Massive 密钥。
5. 打开 **Actions → Premarket trend scan → Run workflow**：
   - `send=false`：只执行 dry-run；
   - `send=true`：进行一次真实测试推送。

定时任务按 `America/New_York` 时区在工作日 08:30 触发；程序会再用 NYSE 日历判断是否开市，周末和休市日不发送。GitHub Actions 会安装 Noto Sans CJK 字体，并从 Repository Secret 读取 Webhook 与 Massive 密钥；敏感值不会写入代码或日志。

## 排障

- `DATA_FAILED`：检查 Massive 与 Yahoo 是否临时限流、权限不足或缺少行情；
- `DELIVERY_FAILED`：检查 Secret 名称、Webhook 是否过期、机器人是否仍在群中；
- GitHub Actions 定时任务可能有排队延迟，因此本工具是盘前研究提醒，不是自动交易基础设施；
- Massive 当前套餐返回延迟行情，期权快照无权限；程序会校验时间戳并按维度降级到 Yahoo。外部数据仍可能延迟、缺失、被修订或改变字段口径，新闻判断只使用保守关键词，期权部分展示当前 IV 而不伪造 IV Rank。

> 本项目仅供个人研究，不构成投资建议。观察分用于整理已获得的信息，不代表胜率或涨跌预测；请在交易前自行核对行情、事件和合约流动性。
