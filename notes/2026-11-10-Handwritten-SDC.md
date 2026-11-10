# 手写 SDC 实战：五个坑，五次"时序说谎"

> 日期：2026-11-10
> 设计：PicoRV32 @ sky130_fd_sc_hd，8 ns
> 目标：不用 OpenLane 自动生成的 `base.sdc`，自己写一份约束并挂进流程

---

## 🔥 为什么手写

OpenLane 默认的 `scripts/base.sdc` 是这样的：

```tcl
create_clock [get_ports clk] -name clk -period $CLOCK_PERIOD
set input_delay_value  [expr $CLOCK_PERIOD * $IO_PCT]
set output_delay_value [expr $CLOCK_PERIOD * $IO_PCT]
set_input_delay  $input_delay_value  -clock clk [all_inputs 去掉 clk]
set_output_delay $output_delay_value -clock clk [all_outputs]
...
```

**`IO_PCT` 默认 0.2** → 所有 IO 端口统一给 `8 × 0.2 = 1.6 ns`。

这是个**通用假设**，不是从接口协议推出来的。手写的价值在于：

1. 按接口分组给不同的延时（存储器 / 复位 / 中断 / 未使能功能）
2. 显式加时序例外（`false_path`）
3. **理解每条约束背后的物理含义**

---

## 📐 手写 SDC 的结构

```tcl
## 1. 时钟
create_clock -name clk -period 8.000 [get_ports clk]
set_clock_uncertainty 0.250 [get_clocks clk]
set_clock_transition  0.150 [get_clocks clk]

## 2. 输入延时（按接口分组）
set_input_delay 1.200 -clock clk [get_ports {mem_rdata[*]}]   ;# 同步 SRAM
set_input_delay 1.200 -clock clk [get_ports {mem_ready}]
set_input_delay 1.600 -clock clk [get_ports {irq[*]}]          ;# 异步中断
set_input_delay 1.600 -clock clk [get_ports {resetn}]          ;# 同步复位
set_input_delay 1.600 -clock clk [get_ports {pcpi_*}]          ;# 未使能

## 3. 输出延时
set_output_delay 2.000 -clock clk [get_ports {mem_addr[*] ...}]  ;# 比默认严 0.4 ns
set_output_delay 2.000 -clock clk [get_ports {mem_la_* ...}]     ;# LA 接口
set_output_delay 1.600 -clock clk [get_ports {eoi[*] trace_* ...}]

## 4. 驱动 / 负载（复用环境变量，不硬编码）
set cap_load [expr {$::env(OUTPUT_CAP_LOAD) / 1000.0}]
set_load $cap_load [all_outputs]
set_driving_cell -lib_cell $::env(SYNTH_DRIVING_CELL) -pin Y [...]

## 5. 时序例外
set_false_path -from [get_ports {pcpi_rd[*] pcpi_wr pcpi_wait pcpi_ready}]
set_false_path -to   [get_ports {pcpi_valid pcpi_insn[*] ... trace_* eoi[*]}]

## 6. 工艺余量（最容易漏）
set_timing_derate -early [expr {1.0 - $::env(SYNTH_TIMING_DERATE)}]   ;# 0.95
set_timing_derate -late  [expr {1.0 + $::env(SYNTH_TIMING_DERATE)}]   ;# 1.05

## 7. 设计规则
set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
```

---

## 🕳️ 六个版本，五个坑

| 版本 | 关键改动 | arrival | required | setup | hold | 结果 |
|---|---|---|---|---|---|---|
| **antB**（默认 SDC） | 基准 | 4.38 | 6.15 | 1.77 | 0.28 | ✅ |
| v1 | `remove_from_collection` | — | — | — | — | ❌ 报错 |
| v3 | `set_load` 只覆盖部分端口 | **3.63** | 5.75 | 2.13 | — | ⚠️ 假乐观 0.75 ns |
| v4 | `set_load` 写成 0.005 pF | 3.62 | 5.75 | 2.13 | — | ⚠️ 假乐观 0.76 ns |
| v5 | 补 `set_load`，漏 `derate` | 3.95 | 5.75 | 1.80 | 0.12 | ⚠️ 仍偏乐观 0.43 ns |
| v6 | 补 `derate`，`resetn` 给 0 | 3.96 | 5.75 | 1.79 | **-0.03** | ❌ hold 违例 |
| **v7** | `resetn` 改 1.6 | **4.02** | 5.75 | **1.73** | **0.18** | ✅ **通过** |

**注意：五个坑里，四个表现为"时序看起来更好"，只有两个是真报错。**

---

## 🧱 坑 1：OpenSTA 不支持 `remove_from_collection`

```tcl
set in_used [remove_from_collection [all_inputs] $clk_port]   # 我用这个"排除"时钟
```

```
Error: my_constraints.sdc, 12 invalid command name "remove_from_collection"
```

**`remove_from_collection` 是 PrimeTime 的标准命令，OpenSTA 没实现。**

**教训**：SDC 号称标准，各家实现是子集。写约束要考虑可移植性（同一份 SDC 可能要在 PrimeTime / Tempus / OpenSTA 上跑）。

**解决**：改成"逐组显式列端口"，虽然啰嗦但 100% 可移植。

---

## 🧱 坑 2：`set_load` 只覆盖部分端口 → arrival 凭空快 0.75 ns

```tcl
# ❌ 只给了 6 组
set_load 0.005 [get_ports {trap mem_valid mem_instr mem_addr[*] mem_wdata[*] mem_wstrb[*]}]
# mem_la_* / eoi / trace_* / pcpi_* 都没有负载
```

**为什么影响这么大**：输出端口的负载电容是"驱动它的单元"所看到的总电容的一部分。

```
驱动单元延时 = f(输入 slew, 输出总电容)
输出总电容   = 片内连线(SPEF) + 端口外部电容(set_load)
```

**没有 `set_load` → 外部电容 = 0 → 驱动看到的总负载偏小 → cell delay 偏小 → arrival 提前。**

而 baseline 的最差路径终点恰好是 **`mem_la_addr[7]`** —— **正好是我漏掉的那组**。

| 项 | 有 set_load | 漏了 |
|---|---|---|
| arrival | 4.38 | **3.63** |
| slack | 1.77（真） | **2.13（假）** |

**教训：约束不全 = 时序乐观，而且工具不会报错。**

---

## 🧱 坑 3：数值硬编码，差 6.7 倍

我以为 5 fF 是"典型负载"，改成 `all_outputs` 后 arrival 只从 3.63 恢复到 3.62 —— 几乎没变。

**于是去查 PDK 配置**：

```tcl
# ~/.ciel/sky130A/libs.tech/openlane/sky130_fd_sc_hd/config.tcl
set ::env(OUTPUT_CAP_LOAD) "33.442"   ;# femtofarad __inv_16 pin A cap
set ::env(MAX_TRANSITION_CONSTRAINT) 0.75
```

**真实值是 33.442 fF = 0.033442 pF，我写的 0.005 pF 小了 6.7 倍。**

而 `base.sdc` 是这么做的：

```tcl
set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]    # fF -> pF
set_load $cap_load [all_outputs]
```

**教训**：不要硬编码，一律复用环境变量。手写的值必须和综合/布线阶段用的是同一套。

> 33.442 fF ≈ `inv_16` 的输入电容 ≈ 16 个最小反相器输入的负载，大致对应 fanout-of-16。

---

## 🧱 坑 4：漏了 `set_timing_derate`（5% 工艺余量）

`base.sdc` 里有一段我完全没注意到：

```tcl
set_timing_derate -early [expr {1-$::env(SYNTH_TIMING_DERATE)}]   # 0.95
set_timing_derate -late  [expr {1+$::env(SYNTH_TIMING_DERATE)}]   # 1.05
```

`SYNTH_TIMING_DERATE = 0.05`：

| 检查 | 作用 |
|---|---|
| `-late 1.05` | 所有慢路径 ×1.05 → setup 更严 |
| `-early 0.95` | 所有快路径 ×0.95 → hold 更严 |

**漏掉 = 少了 5% 的工艺偏差余量**：

```
arrival 3.95（无 derate）→ 补上后应约 4.15
hold   0.12（无 derate）→ 补上后应回升
```

**教训**：SDC 不只是"延时和时钟"，还有**余量类约束**（derate / uncertainty / OCV）。这类约束最容易被"顺手忽略"，因为它们看起来"不影响功能"。

---

## 🧱 坑 5：同步复位给 `input_delay = 0` → 直接造出 hold 违例

```tcl
# ❌ 我的写法：把复位当"特殊信号"，给 0
set_input_delay 0.000 -clock clk [get_ports {resetn}]
```

结果：

```
[ERROR]: There are hold violations in the design at the typical corner.

Startpoint: resetn (input port clocked by clk)
Endpoint:   _16951_ (flip-flop)
data arrival time  : 1.69 ns
data required time : 1.73 ns
slack              : -0.03 ns
```

**原因**：picorv32 用的是**同步复位**：

```verilog
always @(posedge clk) begin
    if (!resetn) ...
```

**`resetn` 在时钟沿被采样，本质是"数据"，不是"异步控制"。**

`input_delay = 0` 意味着数据与时钟沿同时到达 → hold 检查没有任何余量。

**修正**：给它和其他输入一样的 1.6 ns。

```tcl
set_input_delay 1.600 -clock clk [get_ports {resetn}]
```

> 如果设计用的是**异步复位**，才应该：`set_false_path -from resetn` + 检查 recovery/removal。

**教训**：先分清"同步复位"和"异步复位"，它们的约束方式完全相反。搞错的代价是 hold 违例。

---

## 📊 最终结果（v7 vs baseline）

| 指标 | antB（默认 SDC） | v7（手写 SDC） |
|---|---|---|
| `output external delay` | 1.60 | **2.00**（更严） |
| `data required time` | 6.15 | **5.75** |
| `data arrival time` | 4.38 | **4.02** |
| setup slack | 1.77 | **1.73** ✅ |
| hold slack | 0.28 | **0.18** ✅ |
| DRC / LVS | 0 / 0 | **0 / 0** ✅ |
| 标准单元 | 9,626 | 9,626 |
| 总实例 | 29,280 | 29,312 |
| 布线长度 | 650,133 µm | 655,822 µm |

### 为什么 slack 是 1.73 而不是"预期的 1.37"

因为**约束改变会同时改变两件事**：

```
required 下降 0.40 ns    ← 公式决定（8 - 0.25 - 2.0）
arrival  下降 0.36 ns    ← 优化结果决定（输入约束变紧 → resizer 优化更强）
净变化   slack 1.77 → 1.73（−0.04）
```

**所以"改约束"不能只算一边——约束变了，网表也会变，必须重跑全流程。**

---

## 💡 学到了什么

1. **约束错误几乎都表现为"时序变好"**，而不是报错。工具不会告诉你"你漏了约束"。
2. **验证约束正确性的方法**：交叉检查 `arrival / required / slack` 三者是否自洽，而不是只看 slack。
3. **手写的每个数值都必须有出处**：PDK 配置 / 接口协议 / 明确标注的假设。硬编码 = 定时炸弹。
4. **余量类约束（derate / uncertainty）最容易被忽略**，因为它们"看起来不影响功能"。
5. **同步复位 vs 异步复位**决定了复位该怎么约束，搞反直接违例。

---

## 🧰 命令备忘

```bash
# 1. 跑（注意 -config_file 的路径相对当前目录，不是设计目录！）
cd ~/OpenLane && make mount
# 容器内
cd /openlane
./flow.tcl -design picorv32 \
           -config_file designs/picorv32/config_my_sdc.json \
           -tag run_1110_sdc_v7
exit

# 2. 验证 SDC 是否生效
cd ~/OpenLane/designs/picorv32/runs/run_1110_sdc_v7
grep "my_constraints" logs/synthesis/2-sta.log
#   [INFO] my_constraints: set_load = 0.033442 pF on all outputs
#   [INFO] my_constraints: timing derate = +/-5.0 %

# 3. 验证时序自洽
grep -E "output external delay|data arrival time|data required time|slack \(" \
     reports/signoff/31-rcx_sta.max.rpt | head -6
```

---

## 🔜 待办

- [ ] 5 ns 下的违例定位与 ECO 修复
- [ ] `set_multicycle_path`：需要先把 TB 改成"2 拍返回"，让约束和功能一致（否则是"约束骗过工具"）
- [ ] SRAM 集成的 DRC/LVS（老师点名的缺口）
