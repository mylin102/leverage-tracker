
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from pathlib import Path

tz = pytz.timezone('Asia/Taipei')
now = datetime.now(tz)
today_str = now.strftime('%Y-%m-%d')

def get_daily(tickers, period="400d"):
    # tickers: list
    try:
        df = yf.download(tickers, period=period, interval="1d", progress=False, auto_adjust=False, group_by='ticker')
        return df
    except Exception as e:
        print("download fail", e)
        return pd.DataFrame()

def amount_ratio(ticker_num, ticker_den, period="400d"):
    """
    ticker_num: list numerator
    ticker_den: list denominator
    return current ma10, percentile, history
    amount = Close * Volume
    """
    all_tickers = list(set(ticker_num + ticker_den))
    df = yf.download(all_tickers, period=period, interval="1d", progress=False, auto_adjust=False)
    # df structure: MultiIndex (Price, Ticker)
    try:
        # Try to build amount
        closes = df['Close']
        vols = df['Volume']
        amount = closes * vols
        # sum
        num_amount = amount[ticker_num].sum(axis=1) if len(ticker_num)>1 else amount[ticker_num[0]]
        den_amount = amount[ticker_den].sum(axis=1) if len(ticker_den)>1 else amount[ticker_den[0]]
        # 過濾 volume=0 的休市日（yfinance 對台韓股補 0），避免 dtype=object 破壞 rolling
        valid = (num_amount > 0) & (den_amount > 0)
        num_amount = num_amount[valid].astype(float)
        den_amount = den_amount[valid].astype(float)
        ratio = num_amount / den_amount
        ma10 = ratio.rolling(10).mean()
        # percentile last year (252 days)
        last_year = ma10.dropna().tail(252)
        if len(last_year) < 20:
            return None, 0, ratio, ma10
        current = last_year.iloc[-1]
        if pd.isna(current):
            return None, 0, ratio, ma10
        pct = (last_year <= current).mean() * 100
        return float(current), float(pct), ratio, ma10
    except Exception as e:
        print(f"amount_ratio error {ticker_num}/{ticker_den}: {e}")
        return None, 0, pd.Series(), pd.Series()

# 1) 美股 SOXL / (SOXX+SMH)
us_num = ["SOXL"]
us_den = ["SOXX","SMH"]
us_cur, us_pct, us_ratio, us_ma = amount_ratio(us_num, us_den)

# 2) 台股 (00631L.TW + 00670L.TW) / (0050.TW + 006208.TW)
tw_num = ["00631L.TW","00670L.TW"]
tw_den = ["0050.TW","006208.TW"]
tw_cur, tw_pct, tw_ratio, tw_ma = amount_ratio(tw_num, tw_den)

# 3) 韓股 (122630.KS + 494310.KS) / (069500.KS + 091160.KS)
# 122630 KODEX Leverage, 494310 KODEX Semiconductor Leverage (from search)
# 069500 KODEX 200, 091160 KODEX Semiconductor
kr_num = ["122630.KS","494310.KS"]
kr_den = ["069500.KS","091160.KS"]
kr_cur, kr_pct, kr_ratio, kr_ma = amount_ratio(kr_num, kr_den)

# ── 融資餘額 ──────────────────────────────────────────────
import urllib.request, json as _json

# 台股：TWSE MI_MARGN API（每日自動抓）
tw_margin_bil = None   # 億元
tw_margin_note = ""
try:
    _url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json"
    _req = urllib.request.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(_req, timeout=10) as _r:
        _d = _json.loads(_r.read())
    _tables = _d.get("tables", [])
    if _tables:
        _rows = _tables[0].get("data", [])
        # row[2] = 融資金額(仟元)，col[5] = 今日餘額
        _val_str = _rows[2][5].replace(",", "")
        tw_margin_thou = int(_val_str)           # 仟元
        tw_margin_bil = tw_margin_thou / 100000  # 億元
        tw_margin_note = f"{tw_margin_bil:,.0f}億（歷史天量約 6,533億）"
except Exception as _e:
    tw_margin_note = f"抓取失敗：{_e}"

# 韓股：靜態（金融監督院數據，每週更新一次）
kr_margin_note = "30.15兆韓元(10/23)｜高峰38.63兆(6/24)｜金監院10/27召集10家券商施壓"

# 美股：靜態（FINRA 每月公布）
us_margin_note = "1.48兆美元(9月)｜高峰1.502兆(6月)｜較一年前1.06兆暴增40%"

# ── 組合判斷訊號 ───────────────────────────────────────────
def combo_signal(heat_pct, margin_high):
    """heat_pct: 成交熱度百分位；margin_high: 融資是否偏高"""
    if heat_pct is None:
        return ""
    if heat_pct >= 95 and margin_high:
        return '<span class="badge red">⚠ 最危險：熱度過高+融資堆積 → 多殺多風險</span>'
    if heat_pct >= 95:
        return '<span class="badge red">⚠ 成交過熱</span>'
    if heat_pct <= 15 and margin_high:
        return '<span class="badge blue">↗ 短線冷卻+融資未退：偏多但不追高，注意監管壓力</span>'
    if heat_pct <= 15:
        return '<span class="badge blue">↗ 極冷：籌碼乾淨，反彈條件成熟</span>'
    return ""

us_combo  = combo_signal(us_pct, True)
tw_combo  = combo_signal(tw_pct, tw_margin_bil is not None and tw_margin_bil >= 6000)
kr_combo  = combo_signal(kr_pct, True)   # 韓股融資仍在歷史高位

# 4) 指數最新
def last_close(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=False)
        if df.empty: return None
        val = df['Close'].iloc[-1]
        # yfinance 新版單 ticker 也可能回傳 Series
        if hasattr(val, 'iloc'):
            val = val.iloc[0]
        return float(val)
    except:
        return None

taiex = last_close("^TWII")
kospi = last_close("^KS11")
soxl_c = last_close("SOXL")
soxx_c = last_close("SOXX")
smh_c = last_close("SMH")

# 5) 韓股 08:00-08:40 台灣時間波動 = 韓國 09:00-09:40
# 用 30m 數據
kr_intraday_info = "抓取失敗"
try:
    df_intra = yf.download("^KS11", period="2d", interval="30m", progress=False, auto_adjust=False)
    if not df_intra.empty:
        # 轉成台北時間
        df_intra.index = df_intra.index.tz_convert('Asia/Taipei') if df_intra.index.tz is not None else df_intra.index.tz_localize('UTC').tz_convert('Asia/Taipei')
        today_intra = df_intra[df_intra.index.date == now.date()]
        if not today_intra.empty:
            # 韓股 09:00 KST = 08:00 TPE，找最接近的
            # 開盤那根
            def _scalar(val):
                """確保從 Series/DataFrame 取出純量"""
                if hasattr(val, 'iloc'):
                    val = val.iloc[0]
                return float(val)

            open_price = _scalar(today_intra['Open'].iloc[0])
            # 08:40 對應 09:40 KST = 08:40 TPE，大約第2根30m
            # 取到 08:40 前的最後一筆
            cutoff = today_intra[today_intra.index.time <= pd.to_datetime("08:40").time()]
            if not cutoff.empty:
                price_0840 = _scalar(cutoff['Close'].iloc[-1])
                chg = (price_0840 - open_price) / open_price * 100 if open_price else 0
                kr_intraday_info = f"開盤 {open_price:.2f} → 08:40 {price_0840:.2f} {chg:+.2f}%"
            else:
                kr_intraday_info = f"開盤 {open_price:.2f} (尚未到08:40)"
        else:
            kr_intraday_info = "今日尚未開盤"
except Exception as e:
    kr_intraday_info = f"error {e}"

def badge(pct):
    if pct is None: return '<span class="badge yellow">待計算</span>'
    if pct >= 95: return '<span class="badge red">● 亮燈(>95%)</span>'
    if pct >= 80: return '<span class="badge yellow">● 偏熱(>80%)</span>'
    if pct <= 15: return '<span class="badge blue">● 極冷(&lt;15%)</span>'
    return '<span class="badge green">● 正常</span>'

def fmt_ratio(cur):
    return f"{cur:.4f}" if cur is not None else "—"

# AI 結論（DeepSeek，格式與 OpenAI 相容）
ai_conclusion = ""
try:
    import os
    from openai import OpenAI
    _client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    _prompt = f"""你是台灣期貨市場的資深分析師。根據以下數據，用繁體中文寫一段60字以內的今日開盤判斷，語氣簡潔直接，不要廢話，結尾給一個操作方向。

判斷邏輯參考：
- 百分位 >95% = 散戶槓桿追到最瘋 → 過熱警告
- 百分位 80-95% = 偏熱，注意風險
- 百分位 <20% = 槓桿極冷、籌碼乾淨 → 反彈條件成熟，不是危險訊號
- 成交熱度 >95% + 融資餘額高 = 最危險，多殺多
- 成交熱度 <15% + 融資餘額高 = 短線冷了不會再崩，但上去有監管壓力，偏多但不追高
- 韓股是台股開盤的領先指標，KOSPI 開盤漲跌方向通常預示台積電開盤走勢

數據：
- 美股 SOXL/(SOXX+SMH) 成交金額比值 10日MA = {fmt_ratio(us_cur)}，1年百分位 {us_pct:.1f}%，融資：{us_margin_note}
- 台股 (00631L+00670L)/(0050+006208) 成交金額比值 10日MA = {fmt_ratio(tw_cur)}，1年百分位 {tw_pct:.1f}%，融資：{tw_margin_note}
- 韓股槓桿比值 10日MA = {fmt_ratio(kr_cur)}，1年百分位 {kr_pct:.1f}%，融資：{kr_margin_note}
- KOSPI 今日開盤波動：{kr_intraday_info}
- 加權指數前收：{taiex}，KOSPI：{kospi}
- SOXL 最新收盤：{soxl_c}，SOXX：{soxx_c}，SMH：{smh_c}
- 今日日期：{today_str}"""

    _resp = _client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": _prompt}],
        max_tokens=200,
        temperature=0.4,
    )
    ai_conclusion = _resp.choices[0].message.content.strip()
except Exception as _e:
    ai_conclusion = f"（AI結論產生失敗：{_e}）"

html = f"""
<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>美台韓槓桿過熱追蹤 - {today_str}</title>
<style>
body{{font-family:-apple-system,'Noto Sans TC',sans-serif;background:#fff;color:#111;margin:0;padding:24px}}
.wrap{{max-width:800px;margin:0 auto}} h1{{font-size:24px;margin:0}} .sub{{color:#6b7280;font-size:13px;margin-top:6px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:14px;overflow:hidden;font-size:14px;margin-top:16px;border:1px solid #e5e7eb}}
th{{background:#f9fafb;color:#6b7280;padding:12px;text-align:left;border-bottom:1px solid #e5e7eb}} td{{padding:12px;border-bottom:1px solid #f3f4f6;vertical-align:top}}
.badge{{padding:3px 8px;border-radius:12px;font-size:12px;display:inline-block}} .red{{background:#fee2e2;color:#dc2626}} .green{{background:#dcfce7;color:#16a34a}} .yellow{{background:#fef9c3;color:#a16207}} .blue{{background:#dbeafe;color:#1d4ed8}}
.card{{background:#f9fafb;border-radius:14px;padding:16px;margin-top:16px;border:1px solid #e5e7eb}} small{{color:#6b7280}}
</style></head><body><div class="wrap">
<h1>美台韓槓桿過熱追蹤表 - {today_str} 08:40</h1>
<div class="sub">自動產生 · 白底版 · 每日 00:40 UTC = 08:40 台北時間 · 來源 Yahoo Finance</div>

<table>
<tr><th>市場</th><th>公式 (成交金額 10日平均)</th><th>成交熱度 / 百分位</th><th>融資餘額</th><th>判斷</th></tr>
<tr><td>🇺🇸 美股</td><td>SOXL / (SOXX+SMH)</td><td>{fmt_ratio(us_cur)}<br><small>1年百分位 {us_pct:.1f}%</small></td><td><small>{us_margin_note}</small></td><td>{badge(us_pct)}<br>{us_combo}<br><small>SOXL {soxl_c} / SOXX {soxx_c} / SMH {smh_c}</small></td></tr>
<tr><td>🇹🇼 台股</td><td>(00631L+00670L) / (0050+006208)<br><small>分子：元大台灣50正2 + 富邦台灣加權正2<br>分母：元大台灣50 + 富邦台灣加權<br>邏輯：散戶搶買正2槓桿ETF的成交熱度，相對於大盤ETF成交量的比值；比值衝高代表散戶用槓桿追漲到極端</small></td><td>{fmt_ratio(tw_cur)}<br><small>1年百分位 {tw_pct:.1f}%</small></td><td><small>{tw_margin_note}</small></td><td>{badge(tw_pct)}<br>{tw_combo}<br><small>加權 {taiex}</small></td></tr>
<tr><td>🇰🇷 韓股</td><td>(122630.KS + 494310.KS) / (069500.KS + 091160.KS)<br><small>494310=半導體槓桿 122630=大盤槓桿</small><br><small style="color:#1d4ed8">📌 極冷(&lt;15%)代表融資幾乎洗乾淨，是反彈的必要條件。搭配當日開盤強彈才算有說服力的訊號。單獨極冷不代表會漲，還需要殖利率不急升、基本面未惡化。</small></td><td>{fmt_ratio(kr_cur)}<br><small>1年百分位 {kr_pct:.1f}%</small></td><td><small>{kr_margin_note}</small></td><td>{badge(kr_pct)}<br>{kr_combo}<br><small>KOSPI {kospi}</small></td></tr>
<tr><td>🇰🇷 韓股 08:00-08:40 台灣時間</td><td>KOSPI 開盤到08:40波動<br><small>韓國09:00-09:40 = 台灣08:00-08:40</small></td><td colspan="3">{kr_intraday_info}</td></tr>
</table>

<div class="card">
<b>🤖 今日判斷：</b> {ai_conclusion}
</div>

<div class="card">
<b>數值結論：</b> 美股 { '過熱亮燈' if us_pct>=95 else '降溫中'} / 台股 { '過熱' if tw_pct>=95 else '正常'} / 韓股 { '過熱' if kr_pct>=95 else '正常'}<br>
<small>判斷邏輯：三地都用同一個邏輯，成交金額比值10日平均衝到1年95%以上 = 散戶開槓桿追到最瘋。台股離年高10%內才算有效。韓國08:00-08:40是台股09:00開盤的領先指標，三星、SK海力士在這40分鐘的走向會直接影響台積電開盤。</small><br><br>
<small>📊 <b>百分位怎麼看：</b>「1年百分位 X%」代表過去一年有 X% 的交易日，槓桿熱度比今天低（或等於）。例如 49% = 中性；>95% = 過去一年最熱的前5%，亮燈警告；&lt;20% = 接近一年低點，籌碼乾淨，反彈條件成熟。</small>
</div>

<div class="card">
<b>過去數據：</b> 你的原始訊號 9/29 亮燈，台股從49823→46041 -7.6%，韓股KOSPI 6月7400-9100跌至5649跌24-38%。亮燈後20天中位數-1.9%，120天中位數+17.6%，屬於短線過熱不是頭部。
</div>

</div></body></html>
"""

Path("index.html").write_text(html, encoding="utf-8")

# ── 歷史存檔 ──
# 1. 把今天的頁面另存為 archive/YYYY-MM-DD.html
archive_dir = Path("archive")
archive_dir.mkdir(exist_ok=True)
archive_file = archive_dir / f"{today_str}.html"
archive_file.write_text(html, encoding="utf-8")

# 2. 重建 archive/index.html：列出所有已存檔日期（最新在上）
archive_files = sorted(archive_dir.glob("????-??-??.html"), reverse=True)

history_rows = ""
for f in archive_files:
    date_str = f.stem  # e.g. 2026-10-27
    history_rows += f'<li><a href="{f.name}">{date_str}</a></li>\n'

history_html = f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>槓桿追蹤歷史紀錄</title>
<style>
body{{font-family:-apple-system,'Noto Sans TC',sans-serif;background:#fff;color:#111;margin:0;padding:24px}}
.wrap{{max-width:600px;margin:0 auto}} h1{{font-size:22px}} ul{{line-height:2.2em;padding-left:1.2em}}
a{{color:#2563eb;text-decoration:none}} a:hover{{text-decoration:underline}}
.back{{display:inline-block;margin-bottom:16px;color:#6b7280;font-size:13px}}
</style></head><body><div class="wrap">
<a class="back" href="../">← 回最新頁面</a>
<h1>📅 歷史紀錄</h1>
<ul>
{history_rows}</ul>
</div></body></html>
"""
(archive_dir / "index.html").write_text(history_html, encoding="utf-8")

# 3. 在主頁面加入「歷史紀錄」連結（插入到 </div></body> 前）
main_with_link = html.replace(
    "</div></body></html>",
    '<div style="margin-top:12px;text-align:right"><a href="archive/" style="color:#6b7280;font-size:13px">📅 歷史紀錄</a></div>\n</div></body></html>'
)
Path("index.html").write_text(main_with_link, encoding="utf-8")

print(f"done {today_str} us={us_pct:.1f}% tw={tw_pct:.1f}% kr={kr_pct:.1f}% archive={archive_file}")
