# 数字后端自动化脚本（Tcl）

本目录包含我在跑通 PicoRV32 OpenLane 流程时，编写的自动化解析脚本。

## 1. qor_summary.tcl
- 功能：读取 `metrics.csv`，快速打印 WNS、TNS、Setup/Hold 违例数。
- 用法：`tclsh qor_summary.tcl`

## 2. parse_all_violations.tcl
- 功能：解析 `31-rcx_sta.checks.rpt`，自动提取 Max Fanout / Slew / Cap 违例的具体引脚和数值。
- 用法：`tclsh parse_all_violations.tcl`
