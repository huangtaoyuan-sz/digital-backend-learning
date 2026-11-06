# 2026-11-06 学习日志：从“时序脚本”到“全栈全自动体检 Pipeline”

## 📌 背景
此前我编写的 STA 分析脚本仅聚焦于读取 `.rpt` 文件中的 `VIOLATED` 关键字。在导师的指点下，我意识到真实的工业排错绝不能“头痛医头”。
隐藏在 `warnings.log` 中的 ERC 错误（如 Decap 子电路缺失）以及 `logs/` 下的 Fatal Error，才是真正会导致流片失败的致命伤。为此，我利用 AI 辅助，对原有的 Python 脚本进行了史诗级的重构。

## 🚀 核心重构点（工程化进阶）

1. **多文件全方位扫描**：
   不再只吃一个报告。新脚本 `openlane_analyzer.py` 会自动遍历整个 run 目录，精准抓取 `openlane.log`、`warnings.log`、各个阶段的 `.rpt` 以及 `logs/**/*.log`。

2. **严重度分级（Severity Levels）**：
   将抓取到的问题划分为 `CRITICAL`（如 ERC 子电路缺失、Flow Fatal）、`ERROR`（如 LVS 短路）、`WARNING`（如 Slew/Fanout 违例）和 `INFO`。
   
3. **进阶防呆与成本控制（最核心）**：
   - **上下文去重**：自动将几十条 `fill/tap/decap` 的黑盒警告合并为一条摘要，防止 Token 爆炸。
   - **零浪费拦截**：在生成供 LLM 分析的 `ai_context.txt` 时，自动过滤掉一切 `INFO` 级别的已通过检查。大模型只处理真正的“疑难杂症”。

## 🔍 实战发现的真问题
运行该脚本后，成功在原本看似“完全通过”的 8ns PicoRV32 流程中，揪出了以下隐藏漏洞：
- **[CRITICAL] ERC 错误**：`could not find subcircuit: ...decap_12`（Decap 单元作为黑盒导出时，SPICE 模型缺失）。
- **[WARNING] Slew / Fanout 违例**：印证了之前对高扇出和物理走线的分析。
- **[WARNING] IR Drop 不可信**：因为未设置 `VSRC_LOC_FILES`。

## 💡 学习心得
真实的 EDA 工具输出犹如一座冰山，`metrics.csv` 里完美的 WNS 只是水面上的冰山一角，水面下的 `warnings.log` 和 `erc_screen.log` 才是决定芯片能不能用的关键。这次重构让我真正理解了**“签核（Signoff）”的严谨性**。



# OpenLane Run 分析报告（无token总结）
- run 目录：`/home/hty13/OpenLane/designs/picorv32/runs/openlane_test`
- 扫描文件：11 个

## 概览

| 严重度 | 数量 |
|---|---|
| 🔴 CRITICAL | 1 |
| 🟠 ERROR | 0 |
| 🟡 WARNING | 5 |
| 🔵 INFO | 10 |

## 关键指标

| 指标 | 值 |
|---|---|
| 流程完成 | True |
| WNS (ns) | 0.0 |
| TNS (ns) | 0.0 |
| DRC 标记数 | 0 |
| LVS 错误 | 0 |
| 天线违例条数 | 38 |
| 总功耗 (W) | 0.0634 |
| 时钟 skew (ns) | 0.33 |
| 未约束端点 | 58 |
| 未标注寄生 net | 286 |
| VPWR 压差 | 56.1 mV (3.12%) |
| VGND 压差 | 55.1 mV (3.06%) |

### config 关键参数

| 参数 | 值 |
|---|---|
| CLOCK_PERIOD | `8` |
| FP_CORE_UTIL | `45` |
| PL_TARGET_DENSITY | `0.55` |
| FP_PDN_VPITCH | `153.6` |
| FP_PDN_HPITCH | `153.18` |

## 问题清单（按严重度排序）

### 🔴 [CRITICAL] ERC — ERC 找不到子电路定义：sky130_ef_sc_hd__decap_12

- 位置：`logs/signoff/42-erc_screen.log:53`
- 详情：
```
Fatal error:could not find subcircuit: XFILLER_0_118_62(sky130_ef_sc_hd__decap_12) in picorv32
```
- 建议：SPICE/CDL 网表中缺少该单元的实现，常见于 filler/decap 被当作黑盒导出。影响：物理验证层面 LVS 仍可能通过，但电路级（后仿/CVC）网表不完整。修法：① 检查 PDK 的 SPICE 模型是否包含该单元；② 在导出 CDL 时排除 filler/decap 或加入其模型；③ 或把该单元加入 EXCLUDE_CELLS。

### 🟡 [WARNING] ANTENNA — 天线违例 38 条

- 位置：`41-antenna_violators.rpt`
- 详情：
```
Partial/Required:  6.54, Required:    400.0, Partial:  2616.41, Net: net130, Pin: output130/A, Layer: met3
Partial/Required:  2.82, Required:    400.0, Partial:  1127.61, Net: alu_out\[10\], Pin: _16603_/D, Layer: met2
Partial/Required:  1.96, Required:    400.0, Partial:   783.47, Net: net157, Pin: output157/A, Layer: met1
Partial/Required:  1.93, Required:    400.0, Partial:   773.83, Net: net109, Pin: _14596_/A1, Layer: met2
Partial/Required:  1.89, Required:    400.0, Partial:   754.98, Net: _04084_, Pin: _10584_/S, Layer: met3
Partial/Required:  1.82, Required:    400.0, Partial:   726.11, Net: _04014_, Pin: _10489_/B1, Layer: met3
Partial/Required:  1.78, Required:    400.0, Partial:   711.37, Net: net65, Pin: output65/A, Layer: met1
Partial/Required:  1.78, Required:    400.0, Partial:   711.11, Net: _04126_, Pin: _10070_/S0, Layer: met3
Partial/Required:  1.76, Required:    400.0, Partial:    702.6, Net: _02538_, Pin: _09299_/A1, Layer: met3
Partial/Required:  1.72, Required:    400.0, Partial:   688.03, Net: _07275_, Pin: _13868_/B2, Layer: met3
```
- 建议：开启 DIODE_INSERTION_STRATEGY 自动插二极管，或改层/断线后重连

### 🟡 [WARNING] IRDROP — config 未设置 VSRC_LOC_FILES

- 位置：`config.tcl`
- 建议：IR drop 报告会生成，但电源点位置取默认值，压降数值只能当参考；真实工程需给出电源 PAD 位置

### 🟡 [WARNING] LINT — Verilog linter 告警

- 位置：`openlane.log:7`
- 详情：
```
[WARNING]: 26 warnings found by linter
```
- 建议：查看 synthesis 日志中的 linter 输出，通常不改功能但影响可综合性

### 🟡 [WARNING] STA — 存在 max slew 违例（驱动能力不足）

- 位置：`openlane.log:70`
- 详情：
```
[WARNING]: There are max slew violations in the design at the typical corner. Please refer to 'designs/picorv32/runs/openlane_test/reports/signoff/31-rcx_sta.checks.rpt'.
```
- 建议：读 STA 日志里 report_object_max_slew 段，对高扇出/弱驱动单元换强驱动

### 🟡 [WARNING] STA — 存在 max fanout 违例（单节点负载过多）

- 位置：`openlane.log:71`
- 详情：
```
[WARNING]: There are max fanout violations in the design at the typical corner. Please refer to 'designs/picorv32/runs/openlane_test/reports/signoff/31-rcx_sta.checks.rpt'.
```
- 建议：读 STA 日志里 report_object_max_fanout 段，插 buffer 或调 set_max_fanout

### 🔵 [INFO] ANTENNA — config 未设置 DIODE_INSERTION_STRATEGY

- 位置：`config.tcl`
- 建议：若天线违例超标可显式开启二极管插入

### 🔵 [INFO] BLACKBOX — STA 中黑盒化的单元 4 种（均为 filler/tap/decap，属正常）

- 位置：``
- 详情：
```
sky130_ef_sc_hd__decap_12 ×1；sky130_fd_sc_hd__fill_1 ×1；sky130_fd_sc_hd__fill_2 ×1；sky130_fd_sc_hd__tapvpwrvgnd_1 ×1
```
- 建议：无需处理

### 🔵 [INFO] DRC — DRC 无违例

- 位置：`drc.rpt`

### 🔵 [INFO] FP — CLOCK_PERIOD = 8.0 ns，约束宽松，时序压力不足以暴露问题

- 位置：`config.tcl`
- 建议：想制造时序问题做实验，可逐档降低到 6 / 5 / 4 ns

### 🔵 [INFO] IRDROP — VGND 压差 55.1 mV = 3.06%（合格）

- 位置：`32-irdrop-VGND.rpt`

### 🔵 [INFO] IRDROP — VPWR 压差 56.1 mV = 3.12%（合格）

- 位置：`32-irdrop-VPWR.rpt`

### 🔵 [INFO] LVS — LVS 无错误

- 位置：`39-picorv32.lvs.rpt`

### 🔵 [INFO] STA — 未约束端点：58 个

- 位置：`31-rcx_sta.checks.rpt`
- 详情：
```
Startpoint: _16587_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: mem_la_addr[7] (output port clocked by clk)
Path Group: clk
Path Type: max
0.00    0.00   clock clk (rise edge)
0.00    0.00   clock source latency
0.48    0.36    0.36 ^ clk (in)
2    0.11                           clk (net)
0.48    0.00    0.36 ^ clkbuf_0_clk/A (sky130_fd_sc_hd__clkbuf_16)
0.20    0.37    0.73 ^ clkbuf_0_clk/X (sky130_fd_sc_hd__clkbuf_16)
```
- 建议：未约束的 IO 不会被检查，需补 set_input_delay / set_output_delay

### 🔵 [INFO] STA — 未标注寄生的 net：286 个

- 位置：`31-rcx_sta.checks.rpt`
- 详情：
```
Found 173 unannotated drivers.
irq[0]
irq[10]
irq[11]
irq[12]
irq[13]
irq[14]
irq[15]
irq[16]
irq[17]
```
- 建议：SPEF 未覆盖的 net 退化为理想线，时序偏乐观

### 🔵 [INFO] STA — WNS = 0.0 ns（无 setup 违例）

- 位置：`31-rcx_sta.summary.rpt`

# OpenLane分析（AItoken版）
## 1) 根因

- **tns=0 / wns=0 与 worst_slack_max=1.67 并存**：`wns`/`tns` 取自 `31-rcx_sta.checks.rpt` 的汇总行，而 `worst_slack_max` 是从 `31-rcx_sta.max.rpt` 逐条 path 抓的最小 slack。两者口径不同——checks.rpt 的 wns 是"最差 setup 违例"（无违例即 0），max.rpt 的 slack 是"最差路径余量"（正数）。**不是矛盾，是提取脚本把两个语义混在一起**，属报告解析问题，非设计问题。
- **met_paths 列表全部为正 slack 且单调递增**：这是 `max.rpt` 里按 slack 排序的 path 列表被整段抓取，`line` 是报告行号。列表本身无异常，只是"最差路径"被重复计入 checks.rpt 和 max.rpt 两个文件（line 70 出现两次）。
- **worst_slack_max=1.67 偏大**：说明约束（时钟周期）相对逻辑非常宽松，或大量路径是 reg→reg 短路径/IO 路径。真实根因通常是 **SDC 时钟周期设得过松** 或 **未约束的 IO 路径被默认约束兜底**，导致 slack 虚高，掩盖真实关键路径。

## 2) 真实设计缺陷判断

- **无 setup 违例（tns=wns=0）**：不是缺陷。
- **slack 普遍 >1.6ns**：**不是功能缺陷，但是约束缺陷**——时序余量过大意味着时钟约束未反映真实工作频率，签核无意义。
- **met_paths 重复/口径混乱**：**报告/脚本缺陷**，非 RTL/网表缺陷。
- 结论：**本次 run 无真实时序设计缺陷**；存在 1 个约束质量问题（时钟过松）+ 1 个报告解析问题。

## 3) 修复

**约束（config.tcl / SDC）**——收紧时钟到目标频率：
```tcl
# config.tcl
set ::env(CLOCK_PORT) "clk"
set ::env(CLOCK_PERIOD) 2.0   ;# 按真实目标频率设定，勿留过大余量
set ::env(IO_PCT) 0.2         ;# 明确 IO 延迟占比，避免默认兜底
```

**若需显式 SDC 约束 IO**（`BASE_SDC_FILE` 或 `EXTRA_LEFS` 同级 sdc）：
```tcl
create_clock -name clk -period 2.0 [get_ports clk]
set_input_delay  -clock clk [expr 0.2*2.0] [remove_from_collection [all_inputs] [get_ports clk]]
set_output_delay -clock clk [expr 0.2*2.0] [all_outputs]
set_clock_uncertainty 0.1 [get_clocks clk]
```

**报告解析修正**（提取脚本，非 OpenLane 参数）：`wns`/`tns` 只从 `checks.rpt` 汇总行取；`worst_slack` 从 `max.rpt` 取时按 path 去重（同一 startpoint/endpoint 只保留一次），并区分 `checks.rpt` 与 `max.rpt` 两个来源，避免 line 70 重复计入。

**验证**：收紧 `CLOCK_PERIOD` 后重跑，确认 `wns<0` 时能正确报违例，且 `worst_slack_max` 与 `wns` 语义一致。