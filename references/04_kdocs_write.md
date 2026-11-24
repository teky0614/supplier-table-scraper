# 04 · 核对并写入共享表（kdocs）

共享表：`商品总表.xlsx`，工作表「现货」sheetId=1。列（0-based）：

| 列 | 内容 | 来源 |
|---|---|---|
| 0 A | 主图预览 | 内嵌图片（attachment） |
| 1 B | 标题 | 清洗后标题，原样 |
| 2 C | 袋规 | 字段 color |
| 3 D | 袋价 | `ceil(cost×1.13/5)×5`，**严禁填成本价** |
| 4 E | 扭蛋尺寸 | 字段 dia，空则跳过 |
| 5 F | 编码 | 字段 jan，前置 `'` 强制文本 |

## 核对（只读）

```bash
# MCP 读 B 列标题 -> {"start_row":5,"titles":[...]}
"$PY" "$S/table_ops.py" diff_kdocs master=<总表_测试> kdocs=<json> out=<kd_diff.json>
```

- `local_only` → 待写入的 N 款（门禁 B 之后进阶段 4/5）。
- `kdocs_only` → 列清单 + 停，用户确认后删。
- 比对键是**清洗后标题**；共享表存的本来就是清洗后的，别拿原始标题去比。
- 数据量大时 `get_range_data` 结果先落盘再让脚本解析，别让模型读几万字符。

## 删行

```
sheet.delete_range_data {"file_id":<id>,"worksheet_id":1,
                          "range_data":[{"col_from":0,"col_to":5,"row_from":r,"row_to":r}],
                          "shift_type":"shift_up"}
```

- ⚠️ **`range_data` 必须是数组 `[{...}]`**，写成对象 `{...}` 会报 `proto: syntax error (line 1:39): unexpected token {`（2026-11-22 实测）。
- **自下而上**删，避免行号漂移。
- 每删前重读该行 B 列，与清单完全一致才删。
- ⚠️ **行号基准（v1.0.1 起明确）**：`diff_kdocs` 输出两套行号——`row` 是 1-based（Excel 行号，给人看）、`origin_row = row-1` 是 0-based，直接填 `row_from/row_to`。删行优先用 `origin_row`；**删前仍必须重读该行 B 列核对标题**（历史曾因混用两套基准误删相邻行）。`get_range_data` 返回的 `originRow` 是 0-based，与 `origin_row` 同一基准。
- 删后读相邻两行确认正确上移（`get_sheets_info` 的 rowTo 可能不立即更新，以内容为准）。
- 备份用 `save_as_file`，参数是 `dst_drive_id`/`dst_parent_id`（不是 drive_id/parent_id），drive 用个人云盘 2640171226（不要用共享表自己的盘）。

## 插行

```
sheet.insert_rows_cols {"type":"row","row_from":4,"row_to":3+N}
```

- 0-based，商品从第 5 行起 → `row_from=4`。
- **一次性插 N 行**，再按序写。逐行插会顺序反转（踩过）。
- 插完确认老商品整块下移、行数 +N。

## 写文本

```bash
"$PY" "$S/gen_kdocs_payload.py" fields=<fields_oid.json> file_id=<id> start_row=4 \
        prefix=<工作区>/pay cols=1,2,3,4,5
```

把 `pay_text.json` 的 `range_data` 交给 `sheet.range_data_batch_update`（`worksheet_id=1`）。

- `op_type` 只有四种：`cell_operation_type_formula` / `picture` / `format` / `merge`。文本也用 `formula`。
- `formula` 操作是 **col_from~col_to 整段填同一个值**，批量写不同值必须逐格一条。
- 值以 `+ - =` 开头会被当公式，写字面文本前置 `'`（存储不带引号）。
- 编码纯数字长串必须前置 `'`，否则显示成 `4.90479E+12`。

## 写图片（唯一正确写法）

1. 上传拿 object_id：

```
sheet.get_attachment_url {"file_id":"<id>","filename":"a.jpg","url":"<图片URL>"}
```

2. 写入：

```json
{"op_type":"cell_operation_type_picture","row_from":4,"row_to":4,"col_from":0,"col_to":0,
 "cell_pic_info":{"tag":"sheet_pic_type_attachment","pic_content":"<object_id>",
                  "width":-1,"height":-1}}
```

- 下划线版接口的图片字段统一叫 `pic_content`；attachment 就是把 object_id 填进 `pic_content`。
- 写后读回应为 `tag:"attachment"`、`picData:"<内部ID>"`（**不含 URL**）、`isCellPic:true`、`=DISPIMG(...)`。
- ❌ 报 400100 或不生效的写法：`update_range_data` 的 picture+attachmentId；`sheet_pic_type_local`+uploadId；`sheet_pic_type_attachment`+attachmentId（字段名错）。
- ❌ `tag:"sheet_pic_type_url"` 能出图，但 `picData` 是完整外链 URL，含供应商卖家 UID，协作者可反查 → **禁用**。

## 行高

```
sheet.set_range_width_height {"range":{"row_from":4,"row_to":3+N,"col_from":0,"col_to":5},
                               "height":2025}
```

- 2025 twip ≈ 135px（twip = px × 15）。
- **用户已确认：新增行一律 135px 完整显示图片，不要再问，也不要压成老行的 60px 小缩略图。** 老行是历史状态，不动。
- `sheet.auto_fit` 按图片比例自适应会导致各行不齐，别用。

## 回读验收

读 row4~(3+N) 六列，逐条核：

- [ ] 标题 = 清洗后标题
- [ ] 袋规 = color
- [ ] 袋价 = 换算值（抽 3 条手算）
- [ ] 尺寸 = dia（空的确实空）
- [ ] 编码 13 位、是文本、不是科学计数法
- [ ] 图片 `tag:"attachment"`、`picData` 无 URL

浏览器只读预览可截图确认图片没被压扁（未登录会弹「快捷登录并查看」，关掉即可；滚动不稳可用名称框输入 A4 跳转）。

## 读取注意

| 字段 | 含义 |
|---|---|
| `cellText` | 显示值（看到什么就是什么） |
| `originalCellValue` | 公式栏原值 |
| `fmlaText` | 仅公式有 |
| `isCellPic` / `cellPicInfo` | 是否图片格 |

## 落地（写回本地真表）

共享表写完 ≠ 本地总表已更新。最后一步：

1. `table_ops.py verify real=<总表_基准> test=<总表_测试> n=<N>`
2. 备份真表
3. 用测试副本覆盖真表
4. 再 `headers` + `verify` 复核一次
5. 输出报告、清理临时文件（截图、payload、中间 json 按需保留审计）

## 坑

| 现象 | 原因 |
|---|---|
| 400100 | 图片字段名写错，看上面唯一正确写法 |
| 图片列显示裂图 | 用了 url 外链被拒 / object_id 已过期，重新上传 |
| 编码变成 `4.9E+12` | 忘了前置 `'` 或没设 `@` 格式 |
| 行顺序反了 | 逐行插行导致的，改一次性插 N 行 |
| 图片被压成一条缝 | 没设行高，或设了 auto_fit |
| 共享表行数没变 | `insert_rows_cols` 的 row_to 算错（应为 3+N，不是 4+N） |
