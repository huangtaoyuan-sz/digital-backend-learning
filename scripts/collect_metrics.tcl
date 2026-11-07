#!/usr/bin/env tclsh
# =============================================================================
# collect_metrics.tcl — 把一个设计下所有 run 的关键指标汇总成一张 CSV
#
# 作用：替代“逐个 run 打开 summary.rpt / drc.rpt / lvs.rpt / metrics.csv 手工抄数”
#
# 用法（在 WSL 里，任意目录）：
#   tclsh collect_metrics.tcl ~/OpenLane/designs/picorv32/runs
#   tclsh collect_metrics.tcl ~/OpenLane/designs/picorv32/runs 'sweep_*'   # 只匹配名字
#   tclsh collect_metrics.tcl ~/OpenLane/designs/picorv32/runs > all.csv
#
# 依赖：只用 Tcl 标准库（Tcl 8.5+），不需要 tcllib，不需要 OpenLane 环境
# 提示：路径不要写 ~，用 $HOME 或绝对路径（Tcl 不自动展开 ~）
# =============================================================================

package require Tcl 8.5

# ---------------------------------------------------------------- 基础工具
proc slurp {path} {
    if {![file exists $path]} { return "" }
    set fp [open $path r]
    fconfigure $fp -encoding utf-8
    set data [read $fp]
    close $fp
    return $data
}

# 安全取 dict 值：键不存在就返回空串，避免整脚本因一个缺失字段而崩
proc dget {d key} {
    if {[dict exists $d $key]} { return [dict get $d $key] }
    return ""
}

# metrics.csv 里的 -1 是“没算”的哨兵值，转成空串
proc real_num {s} {
    if {![string is double -strict $s]} { return "" }
    if {$s == -1 || $s == -1.0} { return "" }
    return $s
}

proc to_double {s {default 0.0}} {
    if {[string is double -strict $s]} { return $s }
    return $default
}

# ---------------------------------------------------------------- 各报告解析
proc parse_summary {run} {
    set text [slurp [file join $run reports signoff 31-rcx_sta.summary.rpt]]
    set r [dict create]
    if {$text eq ""} { return $r }
    set section ""
    foreach line [split $text "\n"] {
        set line [string trim $line]
        if {[string match "report_*" $line]} { set section $line; continue }
        if {[regexp {^wns\s+(-?[\d.]+)} $line -> v]} { dict set r wns $v }
        if {[regexp {^tns\s+(-?[\d.]+)} $line -> v]} { dict set r tns $v }
        if {[regexp {^worst slack\s+(-?[\d.]+)} $line -> v]} {
            if {[string match *Setup* $section]} { dict set r setup_slack $v }
            if {[string match *Hold*  $section]} { dict set r hold_slack  $v }
        }
    }
    return $r
}

proc parse_metrics_csv {run} {
    set text [slurp [file join $run reports metrics.csv]]
    set r [dict create]
    if {$text eq ""} { return $r }
    set lines [split $text "\n"]
    set header [lindex $lines 0]
    set values [lindex $lines 1]
    if {$header eq "" || $values eq ""} { return $r }
    set names [split $header ,]
    set vals  [split $values ,]
    foreach n $names v $vals { dict set r $n $v }
    return $r
}

proc parse_drc {run} {
    set text [slurp [file join $run reports signoff drc.rpt]]
    if {[regexp {COUNT:\s*(\d+)} $text -> v]} { return $v }
    return ""
}

proc parse_lvs {run} {
    set dir [file join $run reports signoff]
    if {![file isdirectory $dir]} { return "" }
    foreach f [glob -nocomplain -directory $dir *lvs*.rpt] {
        set text [slurp $f]
        if {[regexp {Total errors\s*=\s*(\d+)} $text -> v]} { return $v }
        if {[string match "*no net, device, pin*" $text]} { return 0 }
    }
    return ""
}

proc count_antenna {run} {
    set text [slurp [file join $run reports signoff 41-antenna_violators.rpt]]
    if {$text eq ""} { return "" }
    set n 0
    foreach line [split $text "\n"] {
        if {[string first "Partial/Required" $line] >= 0} { incr n }
    }
    return $n
}

proc parse_sta_log_counts {run} {
    # 关键：max slew/fanout 违例数只在 STA 日志里，reports/ 里没有
    set text [slurp [file join $run logs signoff 31-rcx_sta.log]]
    set r [dict create]
    if {$text eq ""} { return $r }
    if {[regexp {max slew violation count\s+(\d+)}   $text -> v]} { dict set r slew   $v }
    if {[regexp {max fanout violation count\s+(\d+)} $text -> v]} { dict set r fanout $v }
    if {[regexp {max cap violation count\s+(\d+)}    $text -> v]} { dict set r maxcap $v }
    return $r
}

proc parse_vpwr {run} {
    set text [slurp [file join $run reports signoff 32-irdrop-VPWR.rpt]]
    set r [dict create]
    if {$text eq ""} { return $r }
    set vals {}
    set first 1
    foreach line [split $text "\n"] {
        if {$first} { set first 0; continue }
        set idx [string last , $line]
        if {$idx < 0} { continue }
        set v [string trim [string range $line [expr {$idx + 1}] end]]
        if {[string is double -strict $v]} { lappend vals $v }
    }
    if {[llength $vals] == 0} { return $r }
    dict set r vpwr_min [::tcl::mathfunc::min {*}$vals]
    dict set r vpwr_max [::tcl::mathfunc::max {*}$vals]
    return $r
}

# ---------------------------------------------------------------- 主流程
if {[llength $argv] < 1} {
    puts stderr "用法: tclsh collect_metrics.tcl <runs_dir> \[pattern\]"
    puts stderr "例如: tclsh collect_metrics.tcl \$HOME/OpenLane/designs/picorv32/runs"
    exit 1
}

set root [lindex $argv 0]
set pattern [lindex $argv 1]
if {$pattern eq ""} { set pattern * }

if {![file isdirectory $root]} {
    puts stderr "目录不存在: $root"
    exit 1
}

set runs {}
foreach d [glob -nocomplain -directory $root -types d $pattern] {
    if {[file isdirectory [file join $d reports]]} { lappend runs $d }
}
set runs [lsort $runs]

if {[llength $runs] == 0} {
    puts stderr "在 $root 下没找到含 reports/ 的 run 目录"
    exit 1
}

set cols {
    run flow clock_ns wns tns setup_slack hold_slack
    drc lvs_err antenna_net slew_viol fanout_viol
    die_mm2 cells total_cells wire_um power_mw vpwr_min vpwr_drop_pct
}
puts [join $cols ,]

foreach run $runs {
    set name [file tail $run]
    set s [parse_summary $run]
    set m [parse_metrics_csv $run]
    set l [parse_sta_log_counts $run]
    set v [parse_vpwr $run]

    # 功耗：内部 + 开关 + 漏电（µW）→ mW
    set pi [to_double [dget $m power_typical_internal_uW]]
    set ps [to_double [dget $m power_typical_switching_uW]]
    set pl [to_double [dget $m power_typical_leakage_uW]]
    set power [format %.2f [expr {($pi + $ps + $pl) / 1000.0}]]

    set vmin ""
    set vpct ""
    if {[dict exists $v vpwr_min]} {
        set vmin [format %.5f [dict get $v vpwr_min]]
        set vpct [format %.2f [expr {(1.8 - [dict get $v vpwr_min]) / 1.8 * 100}]]
    }

    set row [list \
        $name \
        [dget $m flow_status] \
        [real_num [dget $m CLOCK_PERIOD]] \
        [dget $s wns] \
        [dget $s tns] \
        [dget $s setup_slack] \
        [dget $s hold_slack] \
        [parse_drc $run] \
        [parse_lvs $run] \
        [count_antenna $run] \
        [dget $l slew] \
        [dget $l fanout] \
        [real_num [dget $m "DIEAREA_mm^2"]] \
        [real_num [dget $m synth_cell_count]] \
        [real_num [dget $m TotalCells]] \
        [real_num [dget $m wire_length]] \
        $power \
        $vmin \
        $vpct]

    puts [join $row ,]
}
