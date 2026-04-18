# earnings-ics

自选美股公司 → 多源聚合财报日 → 生成 `.ics` → Google Calendar 订阅。

## 特性

- 多数据源合并去重，单源挂掉不影响输出：
  - **yfinance** — 免费、无需 key，按 ticker 查
  - **Nasdaq 公共 calendar API** — 免费、无需 key，按日期区间查
  - **Finnhub**（可选）— 需要免费 API key，提供一致预期、营收预期
- 事件标题带盘前/盘后标记：`AAPL · AMC · EPS est 1.50`
- 描述里附：公司名、财季、EPS 一致预期、实际 EPS、营收预期、数据源
- BMO → 事件落在 07:00–08:00 ET；AMC → 16:30–17:30 ET；未知时段 → 全天事件
- GitHub Actions 每天自动更新并 commit `earnings.ics`

## 快速开始

### 1. 本地试跑

```bash
cd D:/GitHub/earnings-ics
pip install -r requirements.txt
python main.py
# 生成 earnings.ics
```

用记事本/VS Code 打开 `earnings.ics` 看一眼事件对不对。

### 2. 推到 GitHub

```bash
cd D:/GitHub/earnings-ics
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/earnings-ics.git
git push -u origin main
```

（仓库建议设为 **Public**，这样 `.ics` 链接才能被 Google Calendar 拉取。
如果要 Private，需要走 GitHub Pages 或别的托管。）

### 3. （可选）加 Finnhub key 拿一致预期

- 去 <https://finnhub.io/> 注册，免费层 60 次/分钟
- GitHub → Settings → Secrets → Actions → New secret
- 名字：`FINNHUB_API_KEY`，值：你的 token

### 4. 订阅到 Google Calendar

1. 在 GitHub 仓库里找到 `earnings.ics`，点 **Raw**，复制地址：
   `https://raw.githubusercontent.com/<你>/earnings-ics/main/earnings.ics`
2. 打开 <https://calendar.google.com>
3. 左侧「其他日历」旁 `+` → 「通过网址添加」
4. 粘贴链接 → 添加

Google Calendar 每几小时拉一次，Actions 每天早上更新一次，节奏刚好。

## 自定义关注列表

编辑 `watchlist.txt`，一行一个代码，`#` 是注释：

```
AAPL
MSFT
NVDA
# 新加一只
PLTR
```

commit 后 GitHub Actions 自动触发（workflow 里监听了 `watchlist.txt` 的改动）。

## 常见改动

- **拉长时间窗口**：`main.py` 的 `NasdaqSource().fetch_range(days=60)`、
  `FinnhubSource().fetch_range(days=90)` 两处调大即可
- **换日历名**：`python main.py --name "我的美股财报"`
- **加新源**：在 `sources.py` 里实现 `fetch(ticker)` 或 `fetch_range(tickers)`，
  然后在 `main.py::fetch_all` 里加一行；`merge_events` 会自动去重
- **改时间映射**：`main.py` 里的 `TIME_BLOCK` dict

## 排障

- yfinance 偶尔返回空：yfinance 底层在调 Yahoo 的非官方接口，短时 429 比较常见，
  下次 Actions 跑时一般自愈。Nasdaq 源会兜底。
- Nasdaq 返回 403：User-Agent 被拒，换一个 UA 即可（`sources.py::NasdaqSource.HEADERS`）
- 事件不更新：检查 Actions 运行日志；Google Calendar 端的缓存最多可能拖到 24 小时
