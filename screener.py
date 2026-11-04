import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
from FinMind.data import DataLoader

# 系統常數設定
API_LIMIT = 570
STATE_FILE = "state.json"
RESULTS_FILE = "results.json"
HTML_FILE = "index.html"

# 時間設定 (回推 120 個交易日約半年，籌碼看近 7 天確保有 5 個交易日)
TODAY_STR = datetime.now().strftime("%Y-%m-%d")
START_120D = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
START_INST = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

# 登入 FinMind
token = os.environ.get("FINMIND_TOKEN", "")
api = DataLoader()
if token:
    api.login_by_token(api_token=token)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": 0, "completed": False}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def get_stock_list():
    df_info = api.taiwan_stock_info()
    # 過濾上市櫃、代碼長度為4、且非 00 開頭的股票
    df_stocks = df_info[
        (df_info['type'].isin(['twse', 'tpex'])) & 
        (df_info['stock_id'].str.len() == 4) & 
        (~df_info['stock_id'].str.startswith('00'))
    ]
    # 將代碼與名稱配對成字典以便取用名稱
    return df_stocks[['stock_id', 'stock_name', 'industry_category']].to_dict('records')

def generate_html(results):
    # 輕量級 HTML 樣式，引入 DataTables 達成排序與搜尋功能
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>跌深優質股監控儀錶板</title>
        <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
        <style>
            body {{ font-family: 'Microsoft JhengHei', sans-serif; padding: 20px; background-color: #f8f9fa; }}
            h2 {{ color: #333; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .highlight-red {{ color: #d9534f; font-weight: bold; }}
            .highlight-green {{ color: #5cb85c; font-weight: bold; }}
            a {{ color: #0275d8; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .update-time {{ color: #666; font-size: 0.9em; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📉 跌深反彈與法人進場監控儀錶板</h2>
            <div class="update-time">最後更新時間：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            <table id="stockTable" class="display" style="width:100%">
                <thead>
                    <tr>
                        <th>代碼名稱</th>
                        <th>產業類別</th>
                        <th>最新股價</th>
                        <th>120日高點</th>
                        <th>回檔跌幅</th>
                        <th>近月均量(張)</th>
                        <th>近5日外資買賣超</th>
                        <th>近5日投信買賣超</th>
                    </tr>
                </thead>
                <tbody>
    """
    for r in results:
        # 跳轉 Goodinfo 的超連結
        link = f"<a href='https://tw.stock.yahoo.com/quote/{r['id']}' target='_blank'>{r['id']} {r['name']}</a>"
        drawdown_color = "highlight-green" if r['drawdown'] <= -35 else ""
        
        html_content += f"""
                    <tr>
                        <td>{link}</td>
                        <td>{r['industry']}</td>
                        <td>{r['price']:.2f}</td>
                        <td>{r['high_120']:.2f}</td>
                        <td class="{drawdown_color}">{r['drawdown']:.1f}%</td>
                        <td>{r['volume']:.0f}</td>
                        <td>{r['foreign_buy']:.0f}</td>
                        <td>{r['trust_buy']:.0f}</td>
                    </tr>
        """
        
    html_content += """
                </tbody>
            </table>
        </div>
        <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
        <script>
            $(document).ready(function() {
                $('#stockTable').DataTable({
                    "order": [[ 4, "asc" ]], // 預設依回檔跌幅排序
                    "language": { "url": "//cdn.datatables.net/plug-ins/1.13.6/i18n/zh-HANT.json" }
                });
            });
        </script>
    </body>
    </html>
    """
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    api_calls = 0
    state = load_state()
    results = load_results()
    
    # 若已經跑完，直接結束 (可設定定時清除機制，這裡預設手動或每日重置)
    if state.get("completed"):
        print("本輪已全數掃描完畢。若要重新掃描，請刪除 state.json。")
        return

    stock_list = get_stock_list()
    total_stocks = len(stock_list)
    start_idx = state.get("last_index", 0)
    
    print(f"總計 {total_stocks} 檔普通股，本次從第 {start_idx} 檔開始掃描...")

    for i in range(start_idx, total_stocks):
        if api_calls >= API_LIMIT:
            print(f"\n[配額控制] 已達本次 API 呼叫上限 ({api_calls}次)。儲存斷點: 第 {i} 檔。")
            state["last_index"] = i
            save_state(state)
            save_results(results)
            return

        stock = stock_list[i]
        stock_id = stock['stock_id']
        
        try:
            # 濾網一：價格與均量
            df_price = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_120D, end_date=TODAY_STR)
            api_calls += 1
            time.sleep(0.3) # 避免呼叫過於密集

            if df_price.empty or len(df_price) < 20:
                continue

            current_price = df_price['close'].iloc[-1]
            if current_price > 200:
                continue # 過濾高價股

            high_120 = df_price['max'].max()
            drawdown = ((current_price - high_120) / high_120) * 100
            if drawdown > -30:
                continue # 未跌滿 30%

            # 均量 (FinMind 單位是「股」，轉換為「張」)
            vol_mean = df_price.tail(20)['Trading_Volume'].mean() / 1000
            if vol_mean < 3000:
                continue # 流動性不足

            # 濾網二：法人籌碼 (近 5 日)
            df_inst = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=START_INST, end_date=TODAY_STR)
            api_calls += 1
            time.sleep(0.3)

            if df_inst.empty:
                continue

            foreign = df_inst[df_inst['name'] == 'Foreign_Investor']
            trust = df_inst[df_inst['name'] == 'Investment_Trust']
            
            foreign_buy = foreign['buy'].sum() - foreign['sell'].sum() if not foreign.empty else 0
            trust_buy = trust['buy'].sum() - trust['sell'].sum() if not trust.empty else 0
            
            if foreign_buy <= 0 and trust_buy <= 0:
                continue # 法人未買超

            # 濾網三：Q1 與 Q2 EPS 獲利
            df_eps = api.taiwan_stock_financial_statement(stock_id=stock_id, start_date="2026-01-01", end_date="2026-08-15")
            api_calls += 1
            time.sleep(0.3)

            if df_eps.empty:
                continue

            eps_data = df_eps[df_eps['type'] == 'EPS']
            if len(eps_data) < 2:
                continue # 財報資料不足
                
            # 檢查前兩筆 EPS 是否大於 0
            eps_values = eps_data.tail(2)['value'].tolist()
            if any(v <= 0 for v in eps_values):
                continue # 前兩季未賺錢

            print(f"[命中] {stock_id} {stock['stock_name']} - 跌幅 {drawdown:.1f}%")
            results.append({
                "id": stock_id,
                "name": stock['stock_name'],
                "industry": stock['industry_category'],
                "price": current_price,
                "high_120": high_120,
                "drawdown": drawdown,
                "volume": vol_mean,
                "foreign_buy": foreign_buy / 1000, # 換算為張
                "trust_buy": trust_buy / 1000      # 換算為張
            })

        except Exception as e:
            print(f"Error at {stock_id}: {e}")

    # 全部股票掃描完畢
    print("\n🎉 全台股掃描完畢！正在產生 HTML 儀錶板...")
    state["last_index"] = 0
    state["completed"] = True
    save_state(state)
    save_results(results)
    
    # 產生並寫入 HTML 檔案
    generate_html(results)

if __name__ == "__main__":
    main()
