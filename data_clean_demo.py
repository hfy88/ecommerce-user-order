import json
from pathlib import Path
import numpy as np                # 数值计算：np.where / np.mean 等
import pandas as pd               # 表格处理：读文件、清洗、写库
import pymysql                   # 连接 MySQL（用于建库）
from sqlalchemy import create_engine  # 建引擎，pandas 靠它写表

# 脚本所在目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# MySQL 连接参数
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PWD  = "123456"
TARGET_DB  = "ecommerce_clean"          # 目标库

print("=" * 60)
print("数据库连接成功")
print("目标库：", TARGET_DB)
print("=" * 60)

# =====================================================================
# 第1步：pandas 读取文件
# =====================================================================
user_df   = pd.read_csv(DATA_DIR / "user.csv",   encoding="utf-8-sig")
orders_df = pd.read_csv(DATA_DIR / "orders.csv", encoding="utf-8-sig")
print(f"[第1步] 读取文件完成：user {user_df.shape[0]} 行 × {user_df.shape[1]} 列；"
      f"orders {orders_df.shape[0]} 行 × {orders_df.shape[1]} 列")

# =====================================================================
# 第2步：清洗与预处理
# =====================================================================
# 2.1 时间类型转换
for col in ["register_time", "last_purchase_time"]:
    user_df[col] = pd.to_datetime(user_df[col])
for col in ["order_time", "launch_date"]:
    orders_df[col] = pd.to_datetime(orders_df[col])

# 2.2 缺失值统计
user_missing   = int(np.sum(user_df.isnull().values))
orders_missing = int(np.sum(orders_df.isnull().values))
print(f"[第2步-缺失] user 缺失单元格 {user_missing} 个；orders 缺失单元格 {orders_missing} 个")
print("   订单表 promotion_type 缺失占比：",
      round(float(orders_df["promotion_type"].isnull().mean() * 100), 1), "%")

#orders 缺失单元格 52778 个，查询所缺失字段
orders_missing_cols = orders_df.isnull().sum()
orders_missing_cols = orders_missing_cols[orders_missing_cols > 0]
print("订单表含缺失的字段：")
print(orders_missing_cols)

# 2.3 缺失处理：促销字段缺失约70% → 填成"无促销"，并加一个标志列
orders_df["has_promotion"] = np.where(orders_df["promotion_type"].isnull(), 0, 1)   # numpy 条件生成
orders_df["promotion_type"] = orders_df["promotion_type"].fillna("无促销")           # pandas 填充

# 2.4 去重
before_u = user_df.shape[0]
user_df= user_df.drop_duplicates(subset=["user_id"],keep=["first"])
before_o = orders_df.shape[0]
orders_df = orders_df.drop_duplicates(subset=["order_id"],keep=["first"])
print(f"[第2步-去重] user {before_u}→{user_df.shape[0]}；orders {before_o}→{orders_df.shape[0]}")

# 2.5 成交口径：只有这三种状态算"成交订单"（Cancelled/Pending 剔除）
CLOSED_STATUS = ("Delivered", "Shipped", "Paid")
orders_df["is_closed"] = np.where(orders_df["order_status"].isin(CLOSED_STATUS), 1, 0)

# 2.5b 履约有效性标志：与 SQL 第⑪条 `YEAR(fulfillment_time)=1970` 对齐
#      全量命中(全 0) → 无真实履约时长，不做时效分析
orders_df["fulfillment_valid"] = np.where(
    pd.to_datetime(orders_df["fulfillment_time"], errors="coerce").dt.year != 1970, 1, 0)

# 2.6 简单派生特征：给用户表加年龄段（方便以后分组看）
user_df["age_band"] = np.where(user_df["age"] < 20, "20岁以下",
                     np.where(user_df["age"] < 30, "20-29岁",
                     np.where(user_df["age"] < 40, "30-39岁",
                     np.where(user_df["age"] < 50, "40-49岁", "50岁及以上"))))

# =====================================================================
# 第3步：连接 MySQL，把清洗结果写入新库 items_demo
# =====================================================================
# 3.1 用 pymysql 先"建库"（如果不存在）
admin = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PWD, charset="utf8mb4")
with admin.cursor() as cur:
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {TARGET_DB} DEFAULT CHARACTER SET utf8mb4")
admin.commit()
admin.close()

# 3.2 用 SQLAlchemy 引擎让 pandas 直接写表（if_exists='replace'：重跑会先删旧表再建，幂等）
engine = create_engine(
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PWD}@{MYSQL_HOST}:3306/{TARGET_DB}?charset=utf8mb4"
)
user_df.to_sql("user_clean",   engine, if_exists="replace", index=False)
orders_df.to_sql("orders_clean", engine, if_exists="replace", index=False)
print(f"[第3步] 已写入 {TARGET_DB} 库：user_clean / orders_clean 两张表")

# =====================================================================
# 第4步：验证（回读 MySQL，确认写进去的行数一致）
# =====================================================================
back_u  = pd.read_sql("SELECT COUNT(*) AS n FROM user_clean",   engine)["n"][0]
back_o  = pd.read_sql("SELECT COUNT(*) AS n FROM orders_clean", engine)["n"][0]
gmv     = float(pd.read_sql(
    "SELECT SUM(CASE WHEN is_closed=1 THEN amount ELSE 0 END) AS g FROM orders_clean", engine)["g"][0])
closed  = int(pd.read_sql("SELECT SUM(is_closed) AS c FROM orders_clean", engine)["c"][0])
print(f"[第4步] 回读验证：user_clean {back_u} 行 ✓ / orders_clean {back_o} 行 ✓")
print(f"        成交 GMV ¥{gmv:,.2f}，成交订单 {closed} 单")

# =====================================================================
# 第4.5步：导出清洗结果 CSV（列名与 SQL 口径对齐：is_closed / has_promotion）
# =====================================================================
OUT_DIR = BASE_DIR / "data_clean"
OUT_DIR.mkdir(exist_ok=True)
user_df.drop(columns=["age_band"]).to_csv(OUT_DIR / "user_clean.csv", index=False, encoding="utf-8-sig")
orders_df.to_csv(OUT_DIR / "orders_clean.csv", index=False, encoding="utf-8-sig")
print(f"[第4.5步] 已导出：data_clean/user_clean.csv、data_clean/orders_clean.csv（含 is_closed）")

# 质量报告落盘（可拿去和 SQL 对账）
report = {
    "source": "ecommerce.user / ecommerce.orders（DBeaver localhost）",
    "target_db": TARGET_DB,
    "user_rows": int(back_u), "orders_rows": int(back_o),
    "gmv": gmv, "closed_orders": closed,
}
(BASE_DIR / "output_data_quality.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("[完成] 质量报告已保存：output_data_quality.json")
