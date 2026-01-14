import akshare as ak
import time

print("测试 AKShare 版本和基本接口...")
print("版本:", ak.__version__)

start = time.time()
try:
    df = ak.stock_zh_a_spot_em()
    print(f"成功获取 {len(df)} 条股票数据，用时 {time.time() - start:.2f} 秒")
    print(df.head(3))
except Exception as e:
    print("出错:", str(e))
