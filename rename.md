# rename.md — 文件 / 表 / 字段重命名映射与规范

> 目的：把"原始库 → 清洗库 → 分析报表"全链路的命名对应关系写清楚，保证面试/实训交付时能讲清"每个名字从哪来、改了哪、为什么改"。
> 依据：`data_clean_demo.py` + `user_orders.sql` + `data_clean/` 实际产物。

---

## 1. 命名总览（三条命名主线）

| 主线 | 命名规则 | 示例 |
|---|---|---|
| 原始表 → 清洗表 | 原表名 + `_clean` 后缀 | `user` → `user_clean` |
| 原始文件 → 清洗文件 | 同名 + `_clean.csv` | `user.csv` → `user_clean.csv` |
| 分析报表 | `rpt_` + 业务名 前缀 | `rpt_rfm`、`rpt_product_abc` |

---

## 2. 文件 / 表重命名映射

### 2.1 原始 → 清洗

| 原始（data/） | 清洗后（data_clean/） | 库表（ecommerce_clean） | 说明 |
|---|---|---|---|
| `user.csv` | `user_clean.csv` | `user_clean` | 用户维表，16 列，98,673 行 |
| `orders.csv` | `orders_clean.csv` | `orders_clean` | 订单事实表，25 列，75,702 行 |

### 2.2 分析报表（仅 MySQL 库表，导出为同名 csv）

| 库表 | 对应 csv | 内容 | 行数 |
|---|---|---:|---:|
| `rpt_rfm` | `rpt_rfm.csv` | RFM 根因表（R/F/M + 打分 + 分群） | 46,786 |
| `rpt_user_priority` | `rpt_user_priority.csv` | 用户分层名单 + 运营优先级 | 46,786 |
| `rpt_product_gmv` | `rpt_product_gmv.csv` | 商品 GMV 聚合 | 1,000 |
| `rpt_product_abc` | `rpt_product_abc.csv` | 商品 ABC 分层 | 1,000 |
| `rpt_product_seg` | `rpt_product_seg.csv` | 商品四象限 | 1,000 |

> `rpt_*` 前 4 张由 SQL ④⑤⑥ 建表，`rpt_rfm`/`rpt_user_priority` 由 SQL ①②③ 建表。

---

## 3. 字段级重命名 / 新增 / 语义变更

### 3.1 用户表 `user_clean`（保持 16 列，仅做清洗，无改名）

| 字段 | 变更 | 说明 |
|---|---|---|
| `register_time` / `last_purchase_time` | 类型变更 | `str → datetime`，供时间计算 |
| — | 去重 | 按 `user_id` 保留首条 |
| `age_band`（仅内存） | 派生但**未落库** | Python 侧算的年龄段，如需落库另加列 |

### 3.2 订单表 `orders_clean`（23 → 25 列，新增 2 列）

| 字段 | 变更类型 | 说明 |
|---|---|---|
| `promotion_type` | 值重命名/填充 | 缺失约 70% → 填充 `"无促销"` |
| `has_promotion` | **新增** | 促销缺失标志：`0/1`（`np.where(isnull,0,1)`） |
| `is_closed`（Python 侧）/ `fulfillment_valid`（导出列） | **新增** | 成交口径标志：Delivered/Shipped/Paid=1，否则 0 |
| `fulfillment_time` | 语义标注 | 1970 占位值 → 判定为无真实履约时长（见 SQL ⑪） |
| — | 去重 | 按 `order_id` 保留首条 |

> 注意：Python 清洗脚本内存中新增 `is_closed` 与 `has_promotion` 两列；实际导出到 `data_clean/orders_clean.csv` 的列名为 `has_promotion` + `fulfillment_valid`。若要对账，以 `orders_clean.csv` 的实际表头为准。

### 3.3 报表表新增字段

| 表 | 新增字段 | 说明 |
|---|---|---|
| `rpt_rfm` | `R_days/F/M/R_score/F_score/M_score/segment` | R/F/M 打分 + 八分群 |
| `rpt_user_priority` | `priority` | P0~P3 运营优先级 |
| `rpt_product_abc` | `cum_share/abc_class` | 累计 GMV 占比 + A/B/C 档 |
| `rpt_product_seg` | `gmv_half/unit_half/quadrant` | GMV/销量二分 + 四象限名 |

---

## 4. 命名规范约定（后续复用）

1. **清洗表统一加 `_clean` 后缀**：一眼区分原始与清洗，避免误用脏数据。
2. **分析表统一 `rpt_` 前缀**：`rpt` = report，用于所有派生报表，防止与业务表混用。
3. **布尔标志统一 `is_` / `has_` 前缀**：`is_closed`、`has_promotion`，值为 0/1。
4. **派生字段用下划线小写**：`R_days`、`F_score`、`abc_class`、`gmv_half`，与 MySQL 命名一致。
5. **口径字段显式命名**：成交口径命名 `is_closed`（或 `fulfillment_valid`），避免用裸 `order_status` 到处判状态。

---

## 5. 命名冲突与易错提醒

- Python 侧 `is_closed` 与导出列 `fulfillment_valid` 不一致：**读 CSV 时以 `orders_clean.csv` 表头为准**，不要假设 Python 内存列名。
- `age_band` 未落库：面试若引用年龄段分层，需说明它在 Python 内存计算、未写入 `user_clean`。
- SQL ⑦"未购名单"注释写"预期 0 行"，但实际约 51,887 人未成交：文档以**实际数据**为准，首单转化是机会点。
- SQL 中 R 的锚点实际用 `2025-02-01`（非注释中的 `MAX(order_time)`）：口径以代码为准。
