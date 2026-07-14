# 美股 QDII 基金额度看板

按基金公司分组，展示旗下**美股 QDII 基金**的申购状态、单日限额、最新净值/盘中涨跌、场内溢价率的每日看板。

> 数据来自天天基金网（非官方接口），仅供参考，**不构成投资建议**。
> “申购状态 / 单日限额”仅间接反映 QDII 额度松紧；机构总额度以国家外汇管理局按月公布为准。

## 结构

```
scraper/fetch.py          # 抓取脚本：列表→筛美股→取状态/限额/净值→写 docs/data.json
scraper/funds_whitelist.json  # 人工补漏的美股 QDII 名单
scraper/lof_map.json      # 场外代码→场内代码，用于算溢价率
docs/                     # GitHub Pages 根目录（index.html / app.js / data.json / history/）
.github/workflows/update.yml  # 定时抓取工作流
```

## 本地运行

```bash
pip install -r requirements.txt
python scraper/fetch.py          # 生成 docs/data.json
cd docs && python -m http.server 8000   # 浏览器打开 http://localhost:8000
```

## 部署到 GitHub Pages

1. 新建仓库并推送本项目。
2. **Settings → Pages**：Source 选 `main` 分支、`/docs` 目录。
3. **Settings → Actions → General → Workflow permissions**：选 **Read and write permissions**。
4. **Actions** 页手动运行一次 `update-qdii-data` 验证能生成 `docs/data.json`。
5. 访问 `https://<用户名>.github.io/<仓库名>/`。

## 注意

- 接口为非官方，字段/结构可能随对方改版变化，脚本已做容错，出问题优先看日志核对字段。
- 关键词筛选可能漏/误，用 `scraper/funds_whitelist.json` 人工校准。
- cron 时间为 **UTC**，注意换算北京时间（+8）。
