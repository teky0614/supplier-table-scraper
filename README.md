# 供应商表格抓取

> 淘宝供应商店铺（至尊宝插件）全店采集 → 本地总表同步 → 金山共享表核对 → 新品字段抓取 → 写共享表 → 落地真表的全链路技能。
> 由 `pifa-xie-gongxiangbiao` + `供应商全店抓取` + `采集同步共享表` 三个旧技能整合重写，本技能是**唯一入口**，旧技能已标记 DEPRECATED 不再调用。

---

## 一、它能做什么

以「供应商店铺当前在售」为真源，把本地总表和对外共享表对齐：

| 情况 | 动作 |
|---|---|
| 采集到、表里没有 | 新增：总表插行 + 抓字段 + 共享表插行 |
| 表里有、采集不到 | 删除：总表删行 + 共享表删行 |
| 价格 > 700 或 < 200，或标题不含「扭蛋」 | 两边都删（用**原始标题**判断） |
| 新上架的 N 款 | 抓 袋规/直径/广告图/JAN，回填后写共享表 |

**为什么必须留总表**：它是全盘底账（成本、历史、已同步字段都在里面），也是共享表袋价的唯一成本来源。共享表发给协作者，绝不能存成本价。跳过总表 = 丢掉可回溯底账。

---

## 二、换电脑安装（重点）

### 第 1 步：装 Python 依赖

本技能**必须用 WorkBuddy 的 default venv**，禁止裸 Python 3.11。

venv 路径（新机按实际 WorkBuddy 安装位置调整）：
```
C:/Users/<你的用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe
```

在这个 venv 里装依赖（九州源/阿里源可加速）：
```bash
PIP="C:/Users/<用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pip"
"$PIP" install openpyxl Pillow zxing-cpp -i https://pypi.tuna.tsinghua.edu.cn/simple
```

`zxing-cpp` 若报 DLL 缺失（找不到 `MSVCP140.dll` 等），安装 **Visual C++ Redistributable 2015-2022 x64** 后重启。

### 第 2 步：装浏览器与插件

1. Chrome 装到默认路径（脚本按 `config.yaml` 的 `chrome_exe` 找）。
2. 在专用 profile 里**手动安装至尊宝插件 v30.3.4**（解压加载，Chrome 137+ 已忽略 `--load-extension`，必须手装）。
3. 淘宝账号登录到该 profile（登录态过期时脚本会停下提示你手动登录，不会自动填账号）。
4. 浏览器由 `scripts/keep_browser.py` 保活启动，命令由 `env_doctor.py launch` 打印。**必须先退出全部 chrome.exe 再启动**，单实例 + 单一 profile + 固定 9333。

### 第 3 步：放技能目录

把整个仓库目录复制到 WorkBuddy 技能目录：
```
C:/Users/<用户名>/.workbuddy/skills/供应商表格抓取/
```
（目录名必须保持「供应商表格抓取」，SKILL.md 的触发词绑定了这个名字。）

### 第 4 步：改 config.yaml

`config.yaml` 是**唯一配置源**，所有路径/端口/标识/阈值都从这里取，脚本里禁止硬编码。换电脑后逐项核对：

| 配置项 | 换机要做什么 |
|---|---|
| `python_exe` | 改成新机 default venv 路径 |
| `chrome_exe` | 改成新机 Chrome 路径 |
| `chrome_flags` / `cdp_port` | 端口 9333 一般不变；确认无其他程序占用 |
| `master_xlsx` / `backup_dir` / `workspace_dir` | 改成新机的表格存放路径 |
| `kdocs_file_id` / `kdocs_worksheet_id` | 共享表没换就保留；换新表则替换 |
| `kdocs_backup_drive_id` | 个人云盘 drive_id，换账号要改（**不要**用共享表自己的盘） |
| 业务阈值 | `price_purge_above=700`、`price_purge_below=200`、`min_coverage_ratio=0.9` 等按业务调整 |

### 第 5 步：验证

```bash
PY="C:/Users/<用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" "scripts/env_doctor.py" check    # CDP + 插件 + 依赖 + 路径全绿即可用
```

---

## 三、目录结构

```
供应商表格抓取/
├── SKILL.md                    # 技能主文档：九阶段流程、铁律、脚本/AI 边界、监控、风险
├── config.yaml                 # 唯一配置源
├── README.md                   # 本文件（换电脑安装说明）
├── CHANGELOG.md                # 版本历史
├── VERSION                     # 当前版本号
├── references/                 # 细粒度规则文档
│   ├── 01_collect.md           # 全店采集（至尊宝/防风控/剪贴板）
│   ├── 02_sync_local.md        # 本地总表同步
│   ├── 03_field_scrape.md      # 新品字段抓取 + JAN 四重验证
│   ├── 04_kdocs_write.md       # 金山共享表写入（接口坑）
│   └── 05_table_rules.md       # 表格通用规则（按表头名定位）
└── scripts/
    ├── run.py                  # 统一编排入口（九阶段 + watchdog 埋点）
    ├── common.py               # 配置读取/错误码/JSON IO
    ├── env_doctor.py           # 环境自检/启动命令/探活
    ├── browser_ctl.py          # 自包含 CDP 拟人鼠标（port 从 config）
    ├── cdp_client.py           # 纯标准库 CDP 客户端
    ├── table_ops.py            # 确定性表格运算（按表头名）
    ├── jan_verify.py           # 条码解码/放大/GS1
    ├── gen_kdocs_payload.py    # 袋价换算 + payload 拼装
    ├── watchdog.py             # 状态机/日志/失败定位/重试
    └── keep_browser.py         # 浏览器保活（防被沙箱回收）
```

---

## 四、三道人工门禁（不可自动化）

| 门禁 | 位置 | 停什么 |
|---|---|---|
| A | 阶段 2 后 | 总表新增/删除/剔除清单，尤其删除条数 |
| B | 阶段 3 后 | 共享表独有行清单（要删云表数据） |
| C | 阶段 4 后 | 下架剔除、尺寸特殊、JAN 存疑 |

---

## 五、版本管理

版本号遵循语义化版本 `MAJOR.MINOR.PATCH`，见 `VERSION` 与 `CHANGELOG.md`。每次发布打 Git tag（如 `v1.0.0`）。

换电脑更新流程：
```bash
cd <技能目录>
git pull                       # 拉取最新版本
git checkout v1.0.1            # 或切到指定 tag
```
更新后**重新核对 config.yaml**（新版本可能新增配置项），再跑 `env_doctor.py check`。

---

## 六、注意事项

- 浏览器端口 9333 专用；9222（拼多多）/9223（小红书）等不要碰。
- 共享表图片必须内嵌（`attachment` + object_id），禁外链 URL——外链含供应商 UID，协作者可反查。
- `logs/` 下会生成原始剪贴板/截图，**用完即删**，不要提交到仓库。
- 全程只改测试副本，最后一步才落地真表；每阶段验收，不跳步。
- 遇淘宝验证框/滑块立即停止，不点、不重试。
