# OpenLane 扇出违例分析与 Tcl 脚本解析

## 背景
在 OpenLane 跑完 RTL-to-GDSII 流程后，报告提示存在最大扇出（Max Fanout）违例。为了精确统计违例数量并提取具体引脚信息，编写 Tcl 脚本进行自动化解析。

## 运行环境
- OpenLane / OpenROAD 流程
- SkyWater 130nm 工艺库
- 脚本语言：Tcl 8.6

## 违例数据源
文件路径：`reports/signoff/31-rcx_sta.checks.rpt`

## 解析脚本 (parse_fanout.tcl)
```tcl
set filename "reports/signoff/31-rcx_sta.checks.rpt"
set fp [open $filename r]
set in_fanout 0
set count 0

while {[gets $fp line] >= 0} {
    if {[string match "*max fanout*" $line]} {
        set in_fanout 1
        continue
    }
    if {$in_fanout && [string match "*clkbuf*" $line]} {
        puts "发现违例：$line"
        incr count
    }
}
close $fp
puts "----------------------"
puts "总扇出违例数：$count"
运行结果
text
发现违例：clkbuf_3_2__f_clk/X         10      11      (VIOLATED)
----------------------
总扇出违例数：1
分析结论
违例发生在时钟树缓冲器 (clkbuf) 上。

限值 (Limit) 为 10，实际扇出 (Fanout) 为 11，超标 1 个，属于轻微违例。

根本原因可能是 Floorplan 阶段核心利用率偏高，导致时钟树负载过大。

下一步计划
尝试调整 designs/spm/config.tcl 中的 FP_CORE_UTIL 参数，扩大芯片面积，重新跑流程，观察该违例是否消除。

## 修复验证（成功）
将 `config.json` 中的 `FP_CORE_UTIL` 从 45 调整为 60，扩大核心面积，重新跑 `make test`。
日志显示：`There are no max slew, max fanout or max capacitance violations`。
重新运行解析脚本，总扇出违例数为 0，成功修复 CTS 阶段扇出违例。