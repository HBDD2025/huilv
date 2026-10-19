# 汇率瞭望台

自用的汇率与理财数据页，放在 GitHub Pages 上，打开网址即可。

## 结构

- `index.html` — 页面本身。中间价、各国央行参考汇率来自 Frankfurter，各国数据来自世界银行，都是打开页面时由浏览器直接请求。
- `data/card_rates.json` — 银联、万事达、中国银行牌价，由定时任务抓取后写入，页面读这个文件。
- `scripts/fetch_rates.py` — 抓取脚本，三个来源互相独立，失败的保留上次结果并标记过期。
- `.github/workflows/update-rates.yml` — 定时任务，北京时间每天 10:40 和 18:10 各跑一次，也可以在 Actions 页面手动点 Run workflow。

## 常改的地方

- 存款利率：`index.html` 里的 `DEPOSIT`。
- 货币列表：`index.html` 的 `CURRENCIES` 和 `scripts/fetch_rates.py` 的 `CODES` 保持一致。
- 手续费备忘、自定义链接：在页面里直接增删，存在浏览器本地，不进仓库。

## 本地查看

直接双击 `index.html` 也能看汇率和各国数据，但浏览器不允许本地文件读取 `data/card_rates.json`，刷卡汇率那张表只在网站上显示。
