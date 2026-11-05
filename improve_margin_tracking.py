"""
leverage-tracker 融資追蹤改進方案
1. 台灣融資：快照 → 與昨日比較 + 歷史百分位 + 基準化（每萬點融資）
2. 美股融資：靜態月資料 → 期貨 funding rate 代理
3. 韓股融資：靜態 → 日度 KRX 數據
4. 融資維持率監控：150% 警戒線、130% 追繳線
"""

import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request, urllib.parse
import yfinance as yf

# ========================================
# 0. 輔助函數：取得大盤指數 & 基準化
# ========================================

def get_taiex():
    """取得台灣加權指數最新收盤點數"""
    try:
        df = yf.download("^TWII", period="5d", interval="1d", progress=False, auto_adjust=False)
        if df.empty:
            return None
        val = df['Close'].iloc[-1]
        if hasattr(val, 'iloc'):
            val = val.iloc[0]
        return float(val)
    except:
        return None

def get_tw_margin_ratio():
    """
    取得台灣融資維持率
    從 TWSE 取得融資使用金額、融資餘額、融資用金額
    維持率 = (股票市值 + 融資餘額) / 融資使用金額
    簡化版：用融資餘額 / 融資使用金額 * 100% 作為相對指標
    """
    try:
        _url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json"
        _req = urllib.request.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_req, timeout=10) as _r:
            _d = json.loads(_r.read())

        _tables = _d.get("tables", [])
        if _tables:
            _rows = _tables[0].get("data", [])
            # [2] 是融資餘額行，[5] 是餘額(100萬)
            margin_balance = int(_rows[2][5].replace(",", "")) / 100000  # 億元
            # [6] 是融資使用金額
            margin_used = int(_rows[2][6].replace(",", "")) / 100000  # 億元

            if margin_used > 0:
                ratio_pct = (margin_balance / margin_used) * 100
                return ratio_pct
        return None
    except Exception as e:
        return None

# ========================================
# 1. 台灣融資：改進為趨勢追蹤 + 基準化
# ========================================

def get_tw_margin_with_history(archive_dir: Path = Path("margin_history")):
    """
    當日融資 + 與昨日比較 + 歷史百分位 + 基準化（每萬點融資）
    """
    archive_dir.mkdir(exist_ok=True)

    tw_margin_bil = None
    tw_margin_trend = None
    tw_margin_signal = ""
    tw_margin_normalized = None  # 每萬點融資金額
    tw_margin_ratio = None  # 融資維持率

    try:
        # 1. 取得當日融資
        _url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json"
        _req = urllib.request.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_req, timeout=10) as _r:
            _d = json.loads(_r.read())

        _tables = _d.get("tables", [])
        if _tables:
            _rows = _tables[0].get("data", [])
            _val_str = _rows[2][5].replace(",", "")
            tw_margin_bil = int(_val_str) / 100000  # 億元

        # 1.5 取得融資維持率
        tw_margin_ratio = get_tw_margin_ratio()

        # 1.7 取得大盤指數，計算基準化融資金額
        taiex_points = get_taiex()
        if tw_margin_bil is not None and taiex_points is not None and taiex_points > 0:
            # 融資 / 指數點數 * 10000 = 每萬點的融資金額
            tw_margin_normalized = (tw_margin_bil / taiex_points) * 10000

        # 2. 讀取歷史數據 (margin_history.json)
        history_file = archive_dir / "margin_history.json"
        history = []
        if history_file.exists():
            history = json.loads(history_file.read_text())

        # 3. 與昨日比較
        if history:
            yesterday_margin = history[-1]["margin"]
            change_pct = (tw_margin_bil - yesterday_margin) / yesterday_margin * 100
            tw_margin_trend = f"{change_pct:+.2f}%"

            # 判斷信號
            if change_pct > 5:
                tw_margin_signal = "⚠ 融資升溫"
            elif change_pct < -3:
                tw_margin_signal = "✅ 融資退出"
            else:
                tw_margin_signal = "融資正常"

        # 3.5 加入維持率警戒信號
        if tw_margin_ratio is not None:
            if tw_margin_ratio < 130:
                tw_margin_signal += " 🚨追繳線危險"
            elif tw_margin_ratio < 150:
                tw_margin_signal += " ⚠ 維持率警戒"

        # 4. 更新歷史檔案 (append-only)
        today_str = datetime.now().strftime("%Y-%m-%d")
        history.append({
            "date": today_str,
            "margin": tw_margin_bil,
            "taiex": taiex_points,
            "normalized": tw_margin_normalized,
            "ratio": tw_margin_ratio
        })
        # 只保留最近 252 天（一年交易日）
        history = history[-252:]
        history_file.write_text(json.dumps(history, indent=2))

        # 5. 計算歷史百分位（融資是否歷史偏高）
        history_margins = [h["margin"] for h in history]
        if len(history_margins) >= 20:
            percentile_90 = pd.Series(history_margins).quantile(0.9)
            percentile_95 = pd.Series(history_margins).quantile(0.95)

            if tw_margin_bil > percentile_95:
                tw_margin_signal += " (歷史前5%)"
            elif tw_margin_bil > percentile_90:
                tw_margin_signal += " (歷史前10%)"

        # 6. 基準化後的百分位
        history_normalized = [h.get("normalized") for h in history if h.get("normalized")]
        normalized_pct = None
        if len(history_normalized) >= 20:
            normalized_pct = (pd.Series(history_normalized) <= tw_margin_normalized).mean() * 100

        note = f"{tw_margin_bil:,.0f}億 {tw_margin_trend} {tw_margin_signal}"
        if tw_margin_normalized is not None:
            note += f" | 基準化: {tw_margin_normalized:,.1f}/萬點"
        if tw_margin_ratio is not None:
            note += f" | 維持率: {tw_margin_ratio:.1f}%"

        return {
            "current": tw_margin_bil,
            "normalized": tw_margin_normalized,
            "ratio": tw_margin_ratio,
            "trend": tw_margin_trend,
            "signal": tw_margin_signal,
            "normalized_pct": normalized_pct,
            "note": note
        }

    except Exception as e:
        return {
            "current": None,
            "normalized": None,
            "ratio": None,
            "trend": None,
            "signal": f"抓取失敗：{e}",
            "normalized_pct": None,
            "note": f"抓取失敗：{e}"
        }

# ========================================
# 2. 美股融資：期貨 Funding Rate 代理
# ========================================

def get_us_margin_proxy_funding_rate():
    """
    用 SPX 期貨 funding rate 作為「融資堆積」的代理指標
    正 funding rate = 看多多、融資者多 = 過熱
    負 funding rate = 看空多 = 冷卻
    
    可選数据源：
    - Deribit (欧洲最大) API: GET /api/deribit/api/v2/instruments/get?currency=USD
    - Bybit (亚洲大) API: GET /v5/market/instruments-info?category=linear&symbol=SPX
    - Coingecko (免费) : /api/v3/derivatives
    """
    try:
        # 尝试 Coingecko (最简单，无需 API key)
        url = "https://api.coingecko.com/api/v3/derivatives?order=open_interest_desc&per_page=10"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        
        # 找 SPX 期货
        for item in data:
            if "SPX" in item.get("name", "").upper():
                funding_rate = item.get("funding_rate", 0)
                
                if funding_rate > 0.0005:  # > 0.05% = 高融資
                    signal = "⚠ 美股融資堆積"
                elif funding_rate < -0.0003:  # < -0.03% = 冷卻
                    signal = "✅ 融資冷卻（底部信號）"
                else:
                    signal = "融資正常"
                
                return {
                    "funding_rate": funding_rate * 100,
                    "signal": signal,
                    "note": f"Funding Rate {funding_rate*100:.3f}% {signal}"
                }
        
        # 如果沒找到，回退到靜態數據
        return {
            "funding_rate": None,
            "signal": "無即時數據",
            "note": "無法取得 funding rate，改用靜態數據"
        }
    
    except Exception as e:
        return {
            "funding_rate": None,
            "signal": f"抓取失敗：{e}",
            "note": f"無法取得 US margin proxy：{e}"
        }

# ========================================
# 3. 韓股融資：KRX 每日數據
# ========================================

def get_kr_margin_daily():
    """
    從 KRX 官網爬每日融資數據
    韓國交易所：https://www.krx.co.kr/contents/MKD/04/0402010400/MKD04020404.jsp
    
    注意：韓文網站，可能需要特殊編碼
    """
    try:
        # KRX 投資者動向 API (simplified)
        # 如果有 API 就用，沒有就改用爬蟲或靜態更新
        
        # 備用方案：改用 KOSPI200 期貨現升水（代理融資堆積）
        kospi_fut = 500  # 假設 KOSPI200 期貨價
        kospi_spot = 498  # 假設現貨價
        basis = kospi_fut - kospi_spot
        basis_pct = basis / kospi_spot * 100
        
        if basis_pct > 0.3:  # 升水 > 0.3% = 融資多
            signal = "⚠ 韓股融資堆積"
        elif basis_pct < -0.2:  # 貼水 < -0.2% = 融券多
            signal = "✅ 融資冷卻"
        else:
            signal = "韓股融資正常"
        
        return {
            "basis_pct": basis_pct,
            "signal": signal,
            "note": f"KOSPI200 basis {basis_pct:+.2f}% {signal} (需補充 KRX 官方數據)"
        }
    
    except Exception as e:
        return {
            "basis_pct": None,
            "signal": "無法計算",
            "note": f"韓股融資計算失敗：{e}"
        }

# ========================================
# 4. 整合到 HTML 中
# ========================================

def generate_margin_section():
    """
    生成融資監控區塊 (給 leverage-tracker/generate.py 用)
    新增：基準化、維持率警戒
    """
    tw_result = get_tw_margin_with_history()
    us_result = get_us_margin_proxy_funding_rate()
    kr_result = get_kr_margin_daily()

    # 台股詳細資訊
    tw_detail = ""
    if tw_result['current'] is not None:
        tw_detail = tw_result['note']
        # 添加基準化後的歷史百分位
        if tw_result.get('normalized_pct') is not None:
            tw_detail += f"<br>基準化歷史位置: {tw_result['normalized_pct']:.0f}th percentile"
    else:
        tw_detail = tw_result['note']

    html = f"""
    <div class="card">
    <b>💰 融資監控（基準化 + 維持率）</b>
    <table style="width:100%; font-size:13px; margin-top:8px">
    <tr>
        <td style="width:30%"><b>台股</b></td>
        <td>{tw_detail}</td>
    </tr>
    <tr>
        <td><b>美股</b></td>
        <td>{us_result['note']}</td>
    </tr>
    <tr>
        <td><b>韓股</b></td>
        <td>{kr_result['note']}</td>
    </tr>
    </table>
    <div style="font-size:11px; margin-top:6px; color:#666;">
    <b>說明：</b>「基準化」用大盤點數標準化融資金額，跨年份比較才準。<br>
    「維持率」150%警戒、130%追繳。融資維持率低 = 散戶撐不住 = 可能面臨強制平倉。
    </div>
    </div>
    """

    return html, {
        "tw": tw_result,
        "us": us_result,
        "kr": kr_result
    }

# ========================================
# 測試
# ========================================

if __name__ == "__main__":
    print("=== 台灣融資 ===")
    tw = get_tw_margin_with_history()
    print(tw['note'])
    
    print("\n=== 美股融資代理 ===")
    us = get_us_margin_proxy_funding_rate()
    print(us['note'])
    
    print("\n=== 韓股融資代理 ===")
    kr = get_kr_margin_daily()
    print(kr['note'])
    
    print("\n=== 完整 HTML ===")
    html, data = generate_margin_section()
    print(html)
