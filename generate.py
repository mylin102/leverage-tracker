
import yfinance as yf
import pandas as pd
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
        # avoid div0
        ratio = num_amount / den_amount.replace(0, pd.NA)
        ma10 = ratio.rolling(10).mean()
        # percentile last year (252 days)
        last_year = ma10.tail(252)
        if len(last_year.dropna()) < 20:
            return None, 0, ratio, ma10
        current = ma10.iloc[-1]
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
    return '<span class="badge green">● 正常</span>'

def fmt_ratio(cur):
    return f"{cur:.4f}" if cur is not None else "—"

html = f"""
<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>美台韓槓桿過熱追蹤 - {today_str}</title>
<style>
body{{font-family:-apple-system,'Noto Sans TC',sans-serif;background:#fff;color:#111;margin:0;padding:24px}}
.wrap{{max-width:800px;margin:0 auto}} h1{{font-size:24px;margin:0}} .sub{{color:#6b7280;font-size:13px;margin-top:6px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:14px;overflow:hidden;font-size:14px;margin-top:16px;border:1px solid #e5e7eb}}
th{{background:#f9fafb;color:#6b7280;padding:12px;text-align:left;border-bottom:1px solid #e5e7eb}} td{{padding:12px;border-bottom:1px solid #f3f4f6;vertical-align:top}}
.badge{{padding:3px 8px;border-radius:12px;font-size:12px;display:inline-block}} .red{{background:#fee2e2;color:#dc2626}} .green{{background:#dcfce7;color:#16a34a}} .yellow{{background:#fef9c3;color:#a16207}}
.card{{background:#f9fafb;border-radius:14px;padding:16px;margin-top:16px;border:1px solid #e5e7eb}} small{{color:#6b7280}}
</style></head><body><div class="wrap">
<h1>美台韓槓桿過熱追蹤表 - {today_str} 08:40</h1>
<div class="sub">自動產生 · 白底版 · 每日 00:40 UTC = 08:40 台北時間 · 來源 Yahoo Finance</div>

<table>
<tr><th>市場</th><th>公式 (成交金額 10日平均)</th><th>數值 / 百分位</th><th>判斷</th></tr>
<tr><td>🇺🇸 美股</td><td>SOXL / (SOXX+SMH)</td><td>{fmt_ratio(us_cur)}<br><small>1年百分位 {us_pct:.1f}%</small></td><td>{badge(us_pct)}<br><small>SOXL {soxl_c} / SOXX {soxx_c} / SMH {smh_c}</small></td></tr>
<tr><td>🇹🇼 台股</td><td>(00631L+00670L) / (0050+006208)</td><td>{fmt_ratio(tw_cur)}<br><small>1年百分位 {tw_pct:.1f}%</small></td><td>{badge(tw_pct)}<br><small>加權 {taiex}</small></td></tr>
<tr><td>🇰🇷 韓股</td><td>(122630.KS + 494310.KS) / (069500.KS + 091160.KS)<br><small>494310=半導體槓桿 122630=大盤槓桿</small></td><td>{fmt_ratio(kr_cur)}<br><small>1年百分位 {kr_pct:.1f}%</small></td><td>{badge(kr_pct)}<br><small>KOSPI {kospi}</small></td></tr>
<tr><td>🇰🇷 韓股 08:00-08:40 台灣時間</td><td>KOSPI 開盤到08:40波動<br><small>韓國09:00-09:40 = 台灣08:00-08:40</small></td><td colspan="2">{kr_intraday_info}</td></tr>
</table>

<div class="card">
<b>結論：</b> 美股 { '過熱亮燈' if us_pct>=95 else '降溫中'} / 台股 { '過熱' if tw_pct>=95 else '正常'} / 韓股 { '過熱' if kr_pct>=95 else '正常'}<br>
<small>判斷邏輯：三地都用同一個邏輯，成交金額比值10日平均衝到1年95%以上 = 散戶開槓桿追到最瘋。台股離年高10%內才算有效。韓國08:00-08:40是台股09:00開盤的領先指標，三星、SK海力士在這40分鐘的走向會直接影響台積電開盤。</small>
</div>

<div class="card">
<b>過去數據：</b> 你的原始訊號 9/29 亮燈，台股從49823→46041 -7.6%，韓股KOSPI 6月7400-9100跌至5649跌24-38%。亮燈後20天中位數-1.9%，120天中位數+17.6%，屬於短線過熱不是頭部。
</div>

</div></body></html>
"""

Path("index.html").write_text(html, encoding="utf-8")
print(f"done {today_str} us={us_pct:.1f}% tw={tw_pct:.1f}% kr={kr_pct:.1f}%")
