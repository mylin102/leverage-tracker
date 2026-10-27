
# 美台韓槓桿過熱追蹤 - 一步到位版

這版已經把三個市場都寫好了，直接丟上GitHub就能每天08:40自動產生白底網頁。

## 包含
- 🇺🇸 SOXL / (SOXX+SMH) 成交金額10日平均 + 1年95百分位
- 🇹🇼 (00631L.TW + 00670L.TW) / (0050.TW + 006208.TW)
- 🇰🇷 (122630.KS KODEX槓桿 + 494310.KS 半導體槓桿) / (069500.KS KODEX200 + 091160.KS 半導體) — 494310就是KODEX Semiconductor Leverage，個人一週買超2564億韓元那檔
- 🇰🇷 韓股08:00-08:40台灣時間波動：抓 ^KS11 的30分K，開盤→08:40漲跌幅

## 部署
1. GitHub新建public repo，例如 leverage-tracker
2. 上傳 generate.py, index.html, .github/workflows/daily.yml
3. Settings > Pages > Source選 main / root
4. Actions > Run workflow手動跑一次

之後每天 https://你的帳號.github.io/leverage-tracker/ 自動更新。

## 自訂
- 美債20年、實質殖利率、MM製造業週期要加的話，可以在 generate.py裡面再串 FRED API (DGS10, TIPS) 和你的MM來源
- 想要歷史存檔：把index.html另存到 docs/2026-10-27.html
