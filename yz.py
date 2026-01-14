import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import os
import json
import time

# ====================== 配置 ======================
CONSECUTIVE_YANG = 3
VOL_MULTIPLIER = 2.0
VOL_PERIOD = 5
ZT_THRESHOLD = 0.099
RECENT_DAYS = 10
MAX_THREADS = 10          # 降低并发，避免被限流
CACHE_FILE = "main_board_cache.json"  # 股票列表缓存
CACHE_EXPIRE_HOURS = 6    # 缓存有效期

# ====================== 工具函数 ======================
def is_up_limit(prev_close, today_close):
    if prev_close <= 0:
        return False
    return (today_close - prev_close) / prev_close >= ZT_THRESHOLD

def has_gap_up(df):
    for i in range(1, len(df)):
        if df['low'].iloc[i] > df['high'].iloc[i-1]:
            return True
    return False

def load_or_fetch_main_board():
    """带缓存的获取主板股票列表"""
    now = datetime.now()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cache_time = datetime.fromisoformat(data['timestamp'])
            if (now - cache_time).total_seconds() / 3600 < CACHE_EXPIRE_HOURS:
                print(f"使用缓存股票列表（{len(data['codes'])}只），更新于 {cache_time}")
                return data['codes']

    print("正在获取主板股票列表（可能需要10-60秒）...")
    for attempt in range(3):
        try:
            stock_list = ak.stock_zh_a_spot_em()
            # 过滤逻辑（剔除ST/创业/科创/北交）
            stock_list = stock_list[~stock_list['名称'].str.contains("ST|退市", na=False)]
            condition = (
                (stock_list['代码'].str.startswith(('60', '000', '001', '002', '003'))) & 
                (~stock_list['代码'].str.startswith(('30', '688', '8', '43')))
            )
            df_main = stock_list[condition].copy()
            df_main['代码'] = df_main['代码'].astype(str).str.zfill(6)
            codes = df_main['代码'].tolist()

            # 保存缓存
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': now.isoformat(),
                    'codes': codes
                }, f, ensure_ascii=False)

            print(f"成功获取 {len(codes)} 只主板非ST股票")
            return codes
        except Exception as e:
            print(f"尝试 {attempt+1}/3 失败: {e}")
            time.sleep(5)
    raise Exception("获取股票列表失败，请检查网络或稍后再试")

def screen_stock(code):
    try:
        # 动态往前30-40天
        start_str = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start_str,
                                end_date=datetime.now().strftime("%Y%m%d"),
                                adjust="qfq")
        
        if len(df) < 12:
            return False, None

        df = df.tail(15).copy()
        for col in ['收盘', '开盘', '最高', '最低', '成交量']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['收盘','开盘','最高','最低','成交量'])
        if len(df) < VOL_PERIOD + 2:
            return False, None

        df.rename(columns={'收盘':'close', '开盘':'open', '最高':'high', 
                           '最低':'low', '成交量':'volume', '日期':'date'}, inplace=True)

        # ① 最近涨停
        has_zt = False
        zt_date = None
        for i in range(1, min(RECENT_DAYS+1, len(df))):
            if is_up_limit(df['close'].iloc[i-1], df['close'].iloc[i]):
                has_zt = True
                zt_date = df['date'].iloc[i]
                break
        if not has_zt:
            return False, None

        # ② 连续阳线
        yang_count = 0
        for i in range(1, CONSECUTIVE_YANG + 1):
            if i >= len(df): break
            if df['close'].iloc[-i] > df['open'].iloc[-i]:
                yang_count += 1
            else:
                break
        if yang_count < CONSECUTIVE_YANG:
            return False, None

        # ③ 缺口（最近8天）
        if not has_gap_up(df.tail(8)):
            return False, None

        # ④ 量放大
        recent_vol = df['volume'].iloc[-1]
        prev_mean = df['volume'].iloc[-1-VOL_PERIOD:-1].mean()
        if recent_vol < prev_mean * VOL_MULTIPLIER:
            return False, None

        # 命中
        name = "未知"
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            if not info_df.empty and 'value' in info_df.columns:
                name = info_df['value'].iloc[0]
        except:
            pass

        return True, {
            '代码': code,
            '名称': name,
            '涨停日期': zt_date,
            '连续阳线': yang_count,
            '最新收盘': round(df['close'].iloc[-1], 2),
            '最新量': int(recent_vol),
            '前{}日均量'.format(VOL_PERIOD): round(prev_mean, 0)
        }

    except Exception:
        return False, None


if __name__ == "__main__":
    codes = load_or_fetch_main_board()

    result_list = []
    lock = threading.Lock()

    print(f"\n开始多线程扫描 {len(codes)} 只股票（线程数: {MAX_THREADS}）...")

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(screen_stock, code): code for code in codes}
        for future in tqdm(as_completed(futures), total=len(codes), desc="扫描进度"):
            match, info = future.result()
            if match:
                with lock:
                    result_list.append(info)
                    print(f"【命中】 {info['代码']} {info['名称']}")

    if result_list:
        df_result = pd.DataFrame(result_list)
        today = datetime.now().strftime("%Y%m%d")
        filename = f"涨停前四信号_{today}.csv"
        df_result.to_csv(filename, index=False, encoding="utf_8_sig")
        print(f"\n完成！共找到 {len(result_list)} 只符合股票")
        print("结果已保存:", filename)
        print(df_result)
    else:
        print("\n今天没有同时满足4个特征的股票")
