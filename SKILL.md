---
name: 供应商表格抓取
description: 供应商店铺（至尊宝插件）全店采集 → 临时表 → 本地总表精确同步 → 与金山共享表核对 → 新上架 N 款字段抓取（袋规/直径/广告图/JAN）→ 写共享表 → 落地真表的全链路。当用户说"供应商表格抓取/采集供应商店铺/全店抓取/写共享表/同步总表/核对共享表/新增写入/下架删除"时使用。已取代旧技能「采集同步共享表」「pifa-xie-gongxiangbiao」「供应商全店抓取」。含 CDP9333 统一浏览器、拟人防风控、按表头名定位、完全一致匹配、图片内嵌保密、JAN 四重验证、下架剔除、三道人工门禁、watchdog 全程监控。
agent_created: true
---

# 供应商表格抓取（全链路唯一主线）

> 2026-11-22 由「pifa-xie-gongxiangbiao」+「供应商全店抓取」+ 中间合并版「采集同步共享表」整合重写。
> 三个旧技能保留作知识备份，**不再调用**；本技能是唯一入口。
> 数据量、行号、file_id 每次都变，文档里的数字都是**示例**，一律按实际替换。

## 0. 一条链在干什么

以「供应商店铺当前在售」为真源，把本地总表和对外共享表对齐：

| 情况 | 动作 |
|---|---|
| 采集到、表里没有 | 新增写入（总表插行 + 共享表插行 + 抓字段） |
| 表里有、采集不到 | 删除（总表删行 + 共享表删行） |
| 价格 > 700 **或 < 200**，或标题不含"扭蛋" | 两边都删（用**原始标题**判断）。上下限从 config 读：`price_purge_above` / `price_purge_below`；低价剔除用于挡引流/邮费/吧唧等非扭蛋（2026-11-22 加） |
| 新上架的 N 款 | 抓 袋规/直径/广告图/JAN，回填后写共享表 |

```
淘宝供应商店铺 ─至尊宝全选复制→ 临时表.xlsx
                              │ ①双向精确匹配（原始标题）
                              ▼
                  总表.xlsx（全盘底账，只改测试副本）
                              │ ②清洗后标题精确对齐
                              ▼
        金山共享表 商品总表.xlsx（对外批发展示，图片内嵌）
```
**为什么必须留总表**：它是全盘底账（成本、历史、已同步字段都在里面），也是共享表袋价的唯一成本来源。共享表发给协作者，绝不能存成本价。跳过总表 = 丢掉可回溯底账，不做。

---

## 1. 环境与配置（唯一配置源 = config.yaml）

**先读 `config.yaml`**（技能根目录），所有路径/端口/标识/阈值都从这里取，脚本里禁止硬编码。改环境只改这一处。

| 项 | 本机实值（config.yaml 中） |
|---|---|
| Python | `C:/Users/TEKYKOO/.workbuddy/binaries/python/envs/default/Scripts/python.exe`（default venv，禁裸 Python） |
| 浏览器 | Chrome + `--no-proxy-server --remote-debugging-port=9333 --user-data-dir=C:\Chrome-Direct-Test` |
| 至尊宝 | v30.3.4，**解压加载**于 `C:\Chrome-Direct-Test\Default\UnpackedExtensions\`（不在 Preferences 标准扩展列表，属正常） |
| 主表 | `E:/影刀表格保存/总表.xlsx`；备份 `E:/影刀表格保存/备份` |
| 共享表 | file_id `R9WyNygaJrMDRfpUadTHrxEmzqeMPMKrY`，sheetId=1，商品从第5行(0-based row4)起 |
| 云盘备份 | drive_id `2640171226`（**不要**用共享表自己的盘 2640171225，会报 drive 类型错误） |

**浏览器串联铁律**：单实例 + 单一 profile + 固定 9333。同 profile 开多个 Chrome 实例会让调试端口失效。启动命令由 `env_doctor.py launch` 打印；必须先退出全部 chrome.exe 再启动。9222(拼多多)/9223(小红书) 不碰。

---

## 2. 全局铁律（违反任一条就地停止）

1. **完全一致匹配**：只认字符串完全相等。禁止模糊/智能/同款/改名推断，不主动输出"疑似同款"判定。
2. **覆盖率护栏**：采集数 ÷ 总表行数 < 0.9（或删除比例 > 30%）→ 禁止反向删除，停下问。防"误选分类/新品筛选把总表整片删掉"。
3. **共享表核对阶段只读**：发现共享表独有标题，列清单 + 停（门禁 B），绝不自行删。
4. **先备份再动**：本地 `table_ops.py backup` + 共享表 `save_as_file` 到个人云盘。
5. **图片必须内嵌**：`sheet_pic_type_attachment` + object_id。禁 `tag:"url"` 外链——外链 picData 是明文 URL，含供应商 UID，协作者可反查供应商。
6. **JAN 原样完整**：13 位就 13 位。机器解码 + GS1 + 放大图肉眼复核，冲突**以放大原图为准**并标注请用户复核。
7. **遇淘宝验证框/风控页立即停止**通知用户，不点、不重试。
8. **先测试副本，最后落真表**；每阶段验收，不跳步。
9. **下架/售罄立即剔除**：详情页显示"商品已经下架啦"/售罄/无法下单 → 不抓字段、不录入、并从总表删行。抓得到不代表能卖。
10. **采集期不碰 DOM**：只发真实鼠标事件；`evaluate` 仅允许读 href/title/视口。业务数据一律截图肉眼识别，截图用完即删。
11. **按表头名定位列**：读写前先读表头建 `名称→列` 映射（脚本内置 `table_ops.py headers`），禁止硬编码 A/B/G。
12. **袋价换算**：`ceil(cost × 1.13 / 5) × 5`，严禁把成本价填进共享表 D 列。

---

## 3. 自动化边界（脚本 vs AI）

### A. 纯脚本（无人值守，`scripts/` 里）
| 环节 | 命令 |
|---|---|
| 配置/环境自检 | `env_doctor.py check` |
| 备份（带时间戳不覆盖） | `table_ops.py backup` |
| 表头解析/列映射/歧义报错 | `table_ops.py headers` |
| 临时表↔总表双向 diff + 护栏 | `table_ops.py sync_plan` |
| 落地副本：删行/插行/清洗/粉标 | `table_ops.py sync_apply` |
| 置顶标红、非目标清标 | `table_ops.py mark` |
| 字段回填（编码强制文本） | `table_ops.py fill` |
| 落地前验收 | `table_ops.py verify` |
| 总表↔共享表标题 diff | `table_ops.py diff_kdocs` |
| 批量标题清洗 | `table_ops.py clean` |
| 袋价换算 + payload 拼装 | `gen_kdocs_payload.py` |
| 条码解码/裁剪放大/GS1 | `jan_verify.py` |
| CDP 探测/鼠标/滚轮/截图 | `browser_ctl.py` |
| 状态机/日志/超时/失败定位/重试 | `watchdog.py` + `run.py` |

### B. 必须 AI 介入（保留 AI 节点）
| 环节 | 为什么 |
|---|---|
| 截图定位分类/排序/全选/复制坐标 | 窗口/吸顶位置每次不同，无法预存 |
| 判断到底/加载中/风控验证框 | 语义判断，文案不固定 |
| 判断商品下架/售罄 | 看页面状态与按钮文案 |
| 识别 SKU「原袋××个」「Φ××mm」 | 图像识别，写法五花八门 |
| 判定印 JAN 的竖版广告图 | UID/长宽比/是否印条码综合判断 |
| zxing 与放大图冲突终审 | 机器误读只能人眼兜底 |
| 直径三特殊情形 | 业务判断 + 用户拍板 |
| 三道门禁汇报与等确认 | 必须人来决策 |

### C. 混合（脚本算，AI 看一眼放行）
- 共享表写入回读验收（脚本比对 + AI 抽查标题/袋价）
- 行高 2025 twip 设完（AI 截图确认图片不被压扁）
- 采集条数 vs 临时表行数（脚本统计 + AI 判是否漏加载）

---

## 4. 九阶段编排（含 watchdog 埋点）

主入口 `run.py` 自动在每步前后打 watchdog 点；AI 按下面顺序调。

### 阶段0 · 准备（全脚本）
```bash
PY="C:/Users/TEKYKOO/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
R="C:/Users/TEKYKOO/.workbuddy/skills/供应商表格抓取/scripts/run.py"
"$PY" "$R" init-run run=<工作区/run_日期>
"$PY" "$R" stage0-env run=<同上>          # env_doctor check：CDP+插件+依赖+路径
```
- 若 E010（CDP 不可达）：`"$(...env_doctor.py)" launch` 打印命令 → 退出全部 chrome → 重启 → 重跑 check。
- 共享表表头：AI 用 kdocs `sheet.get_range_data` 读第1行，核对 B~F 位置后再定 cols。

### 阶段1 · 全店采集（AI 视觉 + 脚本动作）
1. `browser_ctl.py guard` 截图 → AI 确认无风控 → 识别分类/排序/全选/复制坐标（截图用完删）。
2. `browser_ctl.py click` 点分类、排序，每次点完截图确认选中态。
3. 分批滚动：`browser_ctl.py wheel ... steps=7 pause=0.5 jitter=6`，每批后截图判「到底/加载中/验证框」。加载中 10s 无新增 → 回滚几屏再往下（拟人）。
4. 重新截图定位吸顶工具栏 → 点全选（确认 `全选(N/N)`）→ 点复制 → 至尊宝协议弹窗点"同意并继续" → 立即截图读提示"复制...数量:N"。
5. 剪贴板落临时表（PowerShell `Get-Clipboard -Raw`，格式 `标题\t\t链接\t\t价格`），校验行数=N、链接/价格格式全对。
> 细节见 `references/01_collect.md`。

### 阶段2 · 同步本地总表（脚本）→ 门禁 A
```bash
"$PY" "$R" stage2-backup run=<run>
"$PY" "$R" stage2-sync run=<run> tmp=<临时表>
```
- `sync_plan` 只算不写，产出新增/删除/剔除/护栏/重名与链接不一致告警。
- **门禁 A**：AI 把 diff 报给用户（新增 N、删除 N、剔除 N、覆盖率），确认后才落地。
- 确认后：`stage2-sync ... approved=1`（护栏未过且确属全店时加 `force=1`）。产出 `总表_测试.xlsx` + `总表_基准.xlsx`。
- 护身行（空标题/`联系VX…`/合计行）不参与匹配、不删。
> 规则见 `references/02_sync_local.md`、`05_table_rules.md`。

### 阶段3 · 核对共享表（脚本 diff + AI 汇报）→ 门禁 B
```bash
# AI 用 kdocs 读共享表 B 列 → 落成 {"start_row":5,"titles":[...]}
"$PY" "$R" stage3-diff run=<run> kdocs=<kdocs_titles.json>
```
- `local_only` = 待写入 N 款；`kdocs_only` = 共享表独有 → **门禁 B**，列清单给用户，确认后按行号自下而上删（`sheet.delete_range_data`, `shift_type=shift_up`），删前逐行重读 B 列核对。
- 比对键是**清洗后标题**（不是原始标题）。两个键两个场景，别混用。

### 阶段4 · 抓 N 款字段（AI 为主）→ 门禁 C
```bash
"$PY" "$R" stage4-mark run=<run> titles=<titles.json>   # 置顶标红到第2~(N+1)行
```
- 每个链接只打开一次：先看是否下架 → 截图识 SKU 袋规/直径 → 取广告图 URL → 下载图片经 `jan_verify.py` 抓 JAN。全程不读 DOM 文字。
- 字段 JSON：`[{"row":2,"title":清洗后标题,"color":...,"dia":...,"jan":...,"img":...,"cost":成本}]`
- 下架款不写 JSON，并回删总表整行（先备份、核对标题、删后复核行数）。
- **门禁 C**：下架剔除、尺寸三特殊、JAN 存疑当场报用户，不擅自决定。
> 识别与 JAN 四重验证见 `references/03_field_scrape.md`。

### 阶段5 · 回填与写共享表（脚本拼装 + MCP 执行）
```bash
"$PY" "$R" stage5-fill run=<run> fields=<fields.json>
# AI 上传图片：sheet.get_attachment_url → object_id → 塞进 fields 的 oid
"$PY" "$R" stage5-payload run=<run> oid=<fields_oid.json>
```
1. AI 用 kdocs `sheet.insert_rows_cols` 一次性插 N 行（`row_from=4, row_to=3+N`）——**不要逐行插**，会顺序反转。
2. AI 提交 `pay_text.json`/`pay_pic.json` 的 range_data 给 `sheet.range_data_batch_update`（worksheet_id=1）。
3. AI 设行高 `sheet.set_range_width_height` height=**2025 twip**（≈135px），新增行一律 135px，不改老行。
4. 回读 row4~(3+N) 六列验收：标题/袋规/袋价/尺寸/编码全对、编码13位文本、图片 `tag:"attachment"` 且 picData 无 URL。
> kdocs 接口坑见 `references/04_kdocs_write.md`。

### 阶段6 · 落地真表（脚本 + MCP）
```bash
"$PY" "$R" stage6-verify run=<run> n=<N>
```
- 验收口径：维度一致、非抓取列集合一致、前 N 行 颜色/广告图/编码齐全（**直径允许空**）、标红恰好第2~(N+1)行。
- 通过 → 备份真表 → 用测试副本覆盖 → 再 headers+verify 复核一次。

### 阶段7 · 收尾
AI 输出作业报告（新增/删除/剔除/下架/JAN存疑/袋价样例）→ 清理临时截图与 payload → 保留 diff.json、fields.json、state.json 作审计。
```bash
"$PY" "$R" status run=<run>; "$PY" "$R" failpoint run=<run>
```
- **⚠️ 流程全部完成后必须关闭本项目后台保活进程**（用户 2026-11-26 明确要求：每次整条流程跑完都要关）。
  - 仅关闭命令行含 `skills/供应商表格抓取/scripts/keep_browser.py` 的 python 进程，**严禁误杀其他项目的 python**（如 pdd_batch_v3 拼多多发布进程）。
  - 用 PowerShell 按 CommandLine 精确匹配 PID 后 `Stop-Process`，删掉多余保活实例；CDP 9333 的浏览器可一并关闭。
  - 中途因风控/门禁暂停时不要关（流程未结束）；只有全流程落地复核通过后执行。

---

## 5. 三道门禁（不可自动化，必须人点头）

| 门禁 | 位置 | 停什么 |
|---|---|---|
| A | 阶段2后 | 总表新增/删除/剔除清单，尤其删除条数 |
| B | 阶段3后 | 共享表独有行清单（要删云表数据） |
| C | 阶段4后 | 下架剔除、尺寸特殊、JAN 存疑 |

---

## 6. 全流程监控（旧技能没有，本次新增）

- **日志**：`<run>/events.jsonl`，每条含 ts/阶段/步骤/状态/耗时/错误码；只记坐标/状态，**不落截图原文**（保密）。
- **状态**：`<run>/state.json` 每步原子写（tmp→replace），崩溃后从最后成功点恢复。
- **超时**：单步默认 120s，超出记 `timeout_warn`。
- **失败定位**：`run.py failpoint` 给最后成功点、失败步骤、耗时异常、缺失产物、自修复建议。
- **重试**：脚本类 `watchdog.py retry` 计数（默认 3 次）；**风控 E040 / 门禁未确认一律不重试**。
- **错误码**：E010 CDP、E012 插件、E020 表头、E021 护栏、E022 数据一致性、E023 标题未命中、E030/31/32 JAN、E040 风控、E050 共享表回读。详见 `scripts/common.py`。
- **汇报**：`watchdog.py report` 生成 markdown 作业报告。

---

## 7. 两个旧脚本串联时的冲突与规避（已固化在设计中）

| 冲突 | 规避 |
|---|---|
| 浏览器实例/端口不一致 | 统一单实例 Chrome + 9333，废止 Edge9333/9334/9336 约定 |
| 代理设置 | `--no-proxy-server` 直连写进 config，禁止任何步骤另起带代理实例 |
| user-data-dir 多实例 | 单 profile 只开一个 Chrome，启动前必须全退 |
| 列定位两套（硬编码 vs 表头名） | 统一 `table_ops.py headers`，硬编码作废 |
| 两套匹配键 | 临时表↔总表用原始标题（链接做删除键）；总表↔共享表用清洗后标题，config/文档显式声明 |
| 底色语义冲突（粉标 vs 红标） | sync_apply 粉标=采集新增，mark 红标=待抓；mark 会清掉非目标底色，故顺序固定为"先 sync_apply → 后 mark"，不可颠倒 |
| verify 对照物不同 | 统一用同步后基准快照 `总表_基准.xlsx`（不是改动前真表） |
| 下架回删 | 阶段4下架款回删总表，且不得进入 fields.json；若已写共享表需同步删该行 |
| 剪贴板竞态 | 采集期独占系统剪贴板，脚本校验行数/格式，异常提示重复制 |
| 截图保密 vs 监控留证 | 日志只存状态不存图；guard 截图存 logs/，用完即删 |

---

## 8. 潜在风险清单

淘宝风控/验证、插件失效或协议弹窗变化、登录态过期、误删整片总表（护栏拦截）、图片外链泄密、JAN 误读、行号漂移、复制格式变化、共享表权限/云盘 drive 类型错、窗口尺寸变化致坐标失效、截图残留、旧技能误调用（已在旧技能加 DEPRECATED 标记）。

---

## 9. 脚本速查

| 脚本 | 作用 |
|---|---|
| `config.yaml` | 唯一配置源 |
| `common.py` | 配置读取/错误码/JSON IO |
| `env_doctor.py` | 环境自检/启动命令/快速探活 |
| `browser_ctl.py` | 自包含 CDP 拟人鼠标（port 从 config） |
| `cdp_client.py` | 内置纯标准库 CDP 客户端 |
| `table_ops.py` | 所有确定性表格运算（按表头名） |
| `jan_verify.py` | 条码解码/放大/GS1 |
| `gen_kdocs_payload.py` | 袋价换算 + 文本/图片 payload |
| `watchdog.py` | 状态机/日志/失败定位/重试 |
| `run.py` | 统一编排入口（九阶段 + 埋点） |

## 10. 与旧技能的关系
三个旧技能（`pifa-xie-gongxiangbiao`、`供应商全店抓取`、`采集同步共享表`）已加 DEPRECATED 标记，保留作知识备份，**不再调用**。本技能对旧脚本的关键改动：路径全部配置化（去 Administrator 硬编码）、错误码化、全链路 watchdog 监控、浏览器统一为 CDP9333 单实例、配置/脚本按表头名定位。
