####################################################################
# my_constraints.sdc
#   手写 SDC，替换 OpenLane 默认的 scripts/base.sdc
#
# 设计 : picorv32 @ sky130_fd_sc_hd
# 时钟 : 8.000 ns (125 MHz)
# 用途 : BASE_SDC_FILE 指向本文件
#
# 与 OpenLane 默认版的差异
#   1) IO 延时按接口分组给值，而不是统一 CLOCK_PERIOD * IO_PCT (0.2)
#   2) 未使能的功能端口显式加 false_path
#   3) 不使用 remove_from_collection —— OpenSTA 未实现该命令
#      (报错样例: invalid command name "remove_from_collection")
#
# 端口清单来源: designs/picorv32/src/picorv32.v 的 module picorv32 端口列表
#   输入(9组): clk / resetn / mem_ready / mem_rdata[31:0] / pcpi_wr
#              / pcpi_rd[31:0] / pcpi_wait / pcpi_ready / irq[31:0]
#   输出(18组): trap / mem_valid / mem_instr / mem_addr[31:0]
#              / mem_wdata[31:0] / mem_wstrb[3:0]
#              / mem_la_read / mem_la_write / mem_la_addr[31:0]
#              / mem_la_wdata[31:0] / mem_la_wstrb[3:0]
#              / pcpi_valid / pcpi_insn[31:0] / pcpi_rs1[31:0]
#              / pcpi_rs2[31:0] / eoi[31:0] / trace_valid / trace_data[35:0]
####################################################################


## ================================================================
## 1. 时钟定义
## ================================================================
create_clock -name clk -period 8.000 [get_ports clk]

# 时钟不确定性：jitter + margin（沿用 OpenLane 默认 0.25 ns）
set_clock_uncertainty 0.250 [get_clocks clk]

# 时钟输入转换时间（端口 slew）
set_clock_transition 0.150 [get_clocks clk]


## ================================================================
## 2. 输入延时
##    假设：外部器件在时钟沿之后 N ns 才把数据送稳
##    注意：clk 端口不给 input_delay（它是时钟源）
## ================================================================

# 2.1 存储器接口：假设外部 SRAM 1.2 ns 后给数据
set_input_delay 1.200 -clock clk [get_ports {mem_rdata[*]}]
set_input_delay 1.200 -clock clk [get_ports {mem_ready}]

# 2.2 复位：picorv32 是【同步复位】(always @(posedge clk) if(!resetn))
#     所以 resetn 本质是"数据"，必须和其他输入一样给 input delay。
#
#     踩过的坑：曾写成 set_input_delay 0.000 [get_ports resetn]
#     -> 数据与时钟沿同时到达，hold 检查没有余量
#     -> 实测 hold 违例 -0.03 ns:
#          Startpoint: resetn (input port)
#          Endpoint:   _16951_ (flip-flop)
#          arrival 1.69 / required 1.73
#     若设计用的是【异步复位】，才应改为 set_false_path + recovery/removal 检查
set_input_delay 1.600 -clock clk [get_ports {resetn}]

# 2.3 中断：异步信号，真实设计需先两级同步再使用；
#     此处给保守值，时序意义有限（见第 5 节 false_path 讨论）
set_input_delay 1.600 -clock clk [get_ports {irq[*]}]

# 2.4 未使能功能（ENABLE_PCPI = 0）：占位值，随后 false_path 排除
set_input_delay 1.600 -clock clk [get_ports {pcpi_wr}]
set_input_delay 1.600 -clock clk [get_ports {pcpi_rd[*]}]
set_input_delay 1.600 -clock clk [get_ports {pcpi_wait}]
set_input_delay 1.600 -clock clk [get_ports {pcpi_ready}]


## ================================================================
## 3. 输出延时
##    假设：外部器件要求数据在时钟沿之后 N ns 内稳定
## ================================================================

# 3.1 存储器主接口：假设要求 2.0 ns 内稳定（比默认 1.6 更严格）
set_output_delay 2.000 -clock clk [get_ports {mem_addr[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_wdata[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_wstrb[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_valid}]
set_output_delay 2.000 -clock clk [get_ports {mem_instr}]

# 3.2 Look-Ahead 接口（默认 base.sdc 用 all_outputs 覆盖到，
#     手写时容易漏，这里显式列出）
set_output_delay 2.000 -clock clk [get_ports {mem_la_addr[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_la_wdata[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_la_wstrb[*]}]
set_output_delay 2.000 -clock clk [get_ports {mem_la_read}]
set_output_delay 2.000 -clock clk [get_ports {mem_la_write}]

# 3.3 异常标志
set_output_delay 2.000 -clock clk [get_ports {trap}]

# 3.4 未使能功能：占位值
set_output_delay 1.600 -clock clk [get_ports {pcpi_valid}]
set_output_delay 1.600 -clock clk [get_ports {pcpi_insn[*]}]
set_output_delay 1.600 -clock clk [get_ports {pcpi_rs1[*]}]
set_output_delay 1.600 -clock clk [get_ports {pcpi_rs2[*]}]
set_output_delay 1.600 -clock clk [get_ports {eoi[*]}]
set_output_delay 1.600 -clock clk [get_ports {trace_valid}]
set_output_delay 1.600 -clock clk [get_ports {trace_data[*]}]


## ================================================================
## 4. 驱动能力与负载
##    ⚠️ 不要硬编码数值，一律复用 OpenLane 的环境变量。
##    反例（v1/v4 曾犯的错误）：
##      手写 set_load 0.005 pF，而 OpenLane 的 OUTPUT_CAP_LOAD = 33.442 fF
##      -> 应为 0.033442 pF，我写的值小了 6.7 倍
##      -> 输出驱动看到的总电容偏小 -> cell delay 偏小
##      -> data arrival time 由 4.38 ns 变成 3.62 ns（偏乐观 0.76 ns）
##      -> slack 由真实的 ~1.37 被误报为 2.13
##    同理 max_transition 也不能硬编码（OPENLANE 默认 0.75，我写成 1.5 松了一倍）
## ================================================================

# 4.1 输出负载：由 OUTPUT_CAP_LOAD (单位 fF) 换算成 pF
set cap_load [expr {$::env(OUTPUT_CAP_LOAD) / 1000.0}]
puts "\[INFO\] my_constraints: set_load = $cap_load pF on all outputs"
set_load $cap_load [all_outputs]

# 4.2 输入驱动：普通输入用 SYNTH_DRIVING_CELL；时钟优先用 SYNTH_CLK_DRIVING_CELL
set drv_cell $::env(SYNTH_DRIVING_CELL)
set drv_pin  $::env(SYNTH_DRIVING_CELL_PIN)
set clk_drv_cell $drv_cell
set clk_drv_pin  $drv_pin
if {[info exists ::env(SYNTH_CLK_DRIVING_CELL)] && $::env(SYNTH_CLK_DRIVING_CELL) ne ""} {
    set clk_drv_cell $::env(SYNTH_CLK_DRIVING_CELL)
    set clk_drv_pin  $::env(SYNTH_CLK_DRIVING_CELL_PIN)
}

set_driving_cell -lib_cell $drv_cell -pin $drv_pin \
    [get_ports {resetn mem_ready mem_rdata[*] pcpi_wr pcpi_rd[*] pcpi_wait pcpi_ready irq[*]}]
set_driving_cell -lib_cell $clk_drv_cell -pin $clk_drv_pin [get_ports {clk}]


## ================================================================
## 5. 时序例外（Time Exceptions）
## ================================================================

# 5.0 timing derate（工艺偏差余量）
#     OpenLane 默认 base.sdc 里有这一段，手写时最容易漏：
#       -late  1.05 : 慢路径再放大 5%（setup 检查用）
#       -early 0.95 : 快路径再缩小 5%（hold 检查用）
#     漏掉它会让 setup slack 偏乐观约 0.2 ns，hold slack 也偏离
if {![info exists ::env(SYNTH_TIMING_DERATE)]} {
    set ::env(SYNTH_TIMING_DERATE) 0.05
}
set_timing_derate -early [expr {1.0 - $::env(SYNTH_TIMING_DERATE)}]
set_timing_derate -late  [expr {1.0 + $::env(SYNTH_TIMING_DERATE)}]
puts "\[INFO\] my_constraints: timing derate = +/-[expr {$::env(SYNTH_TIMING_DERATE) * 100}] %"

# 5.1 false_path：未使能功能，综合后无真实路径
#     目的：清理报告噪音，表达"这些端口不参与本配置的时序"
set_false_path -from [get_ports {pcpi_wr}]
set_false_path -from [get_ports {pcpi_rd[*]}]
set_false_path -from [get_ports {pcpi_wait}]
set_false_path -from [get_ports {pcpi_ready}]

set_false_path -to [get_ports {pcpi_valid}]
set_false_path -to [get_ports {pcpi_insn[*]}]
set_false_path -to [get_ports {pcpi_rs1[*]}]
set_false_path -to [get_ports {pcpi_rs2[*]}]
set_false_path -to [get_ports {eoi[*]}]
set_false_path -to [get_ports {trace_valid}]
set_false_path -to [get_ports {trace_data[*]}]

# 5.2 multicycle：本设计【未启用】，原因如下（面试可讲）
#
#     若外部存储器是"2 拍返回"(mem_ready 第 2 拍才拉高)，则可以：
#         set_multicycle_path 2 -setup -from [get_ports {mem_rdata[*]}] -to [all_registers -data_pins]
#         set_multicycle_path 1 -hold  -from [get_ports {mem_rdata[*]}] -to [all_registers -data_pins]
#
#     但本项目的 testbench 里存储器是"零等待"(mem_ready = mem_valid)，
#     即功能上 1 拍就返回。此时若设 multicycle 2，就是"约束比实际宽松"，
#     属于"用约束骗过工具"，会掩盖真实违例。
#     因此这里只保留注释，不实际启用。


## ================================================================
## 6. 设计规则
##    同样复用 OpenLane 环境变量，避免手写的值与综合/布线阶段不一致
## ================================================================
set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
if {[info exists ::env(MAX_TRANSITION_CONSTRAINT)] && $::env(MAX_TRANSITION_CONSTRAINT) ne ""} {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}


## ================================================================
## 7. 自查提示（跑完后人工确认）
##    a) STA 日志里应出现 "Reading design constraints file at '...my_constraints.sdc'"
##    b) 若 SDC 有语法错，Step 2 会立刻报:
##         Error: my_constraints.sdc, <行号> <原因>
##    c) 看 required time 确认 output delay 生效:
##         grep "output external delay" 31-rcx_sta.max.rpt
##         应为 -2.00（baseline 是 -1.60）
##    d) 看 arrival time 确认没有"假乐观":
##         grep "data arrival time" 31-rcx_sta.max.rpt
##         应与 baseline 接近（约 4.3~4.4 ns）
##         若明显变小（如 3.6），说明有端口漏了 set_load / set_driving_cell
## ================================================================
