# 美股盘前趋势扫描器

在每个美股交易日开盘前约 60 分钟扫描：

`SPY QQQ AAPL MSFT GOOGL AMZN NVDA META TSLA`

程序使用上一完整交易日的日线判断趋势和“回调转强／平台突破”信号，再结合盘前价格标记“允许关注、跳空偏高不追、信号失效或数据异常”，最后通过企业微信群机器人推送“清晰摘要”图片。它不会连接券商或自动下单，也不推荐具体期权合约。

## 筛选规则

- 最近收盘价高于 MA20，且 MA20 高于 5 个交易日前；
- 回调转强：最近 5 日最低价进入各自 MA20 上下 2%，最新收盘重新站上前一日最高价；
- 平台突破：最新收盘突破此前 10 日高点，成交量不低于此前 20 日均量的 1.2 倍；
- 盘前涨幅超过 3% 标记为不追；盘前跌破 MA20 或参考失效位则标记为失效。

## 本地运行

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest -q
python -m market_scanner.main --dry-run
```

`--dry-run` 是默认模式，只打印报告，不需要企业微信地址。

本机真实发送前，需要提供企业微信地址：

```bash
# PowerShell
$env:WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
python -m market_scanner.main --send
```

图片默认在 Windows 使用微软雅黑，在 GitHub Actions 使用 Noto Sans CJK。其他系统可以通过 `SCANNER_FONT_PATH` 指定支持中文的 `.ttf` 或 `.ttc` 字体。如果当天没有候选标的，机器人仍会发送一张“今日无符合条件标的”的图片。

## 配置企业微信群机器人

1. 在目标企业微信群中添加“群机器人”。
2. 复制机器人 Webhook 地址，不要提交到仓库。
3. 打开 GitHub 私有仓库的 **Settings → Secrets and variables → Actions**。
4. 新建 Repository secret：名称为 `WECOM_WEBHOOK_URL`，值为完整 Webhook 地址。
5. 打开 **Actions → Premarket trend scan → Run workflow**：
   - `send=false`：只执行 dry-run；
   - `send=true`：进行一次真实测试推送。

定时任务按 `America/New_York` 时区在工作日 08:30 触发；程序会再用 NYSE 日历判断是否开市，周末和休市日不发送。GitHub Actions 会安装 Noto Sans CJK 字体，并从 Repository Secret 读取 Webhook；Webhook 不会写入代码或日志。

## 排障

- `DATA_FAILED`：检查 Yahoo Finance 是否临时限流或缺少行情；
- `DELIVERY_FAILED`：检查 Secret 名称、Webhook 是否过期、机器人是否仍在群中；
- GitHub Actions 定时任务可能有排队延迟，因此本工具是盘前研究提醒，不是自动交易基础设施。

> 本项目仅供个人研究，不构成投资建议。免费行情可能延迟、缺失或被修订，请在交易前自行核对。
