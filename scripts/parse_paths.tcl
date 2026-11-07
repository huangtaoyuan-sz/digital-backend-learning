#!/usr/bin/env tclsh
# =============================================================================
# parse_paths.tcl — 批量提取每个 run 的“最差路径摘要”，不用再打开 5MB 的 max.rpt
#
# 把 signoff/31-rcx_sta.max.rpt 压成一行：
#   run | slack | startpoint | endpoint | 逻辑级数 | cell 延时 | net 延时
#
# 用法：
#   tclsh parse_paths.tcl $HOME/OpenLane/designs/picorv32/runs
#   tclsh parse_paths.tcl . --csv > paths.csv
#
# 注意：
#   - cell_stages / cell_delay 统计的是路径上所有带 (sky130_*) 的行，
#     会包含时钟树那几级（因为它们也标了 sky130），已在注释中说明
#   - 只读文件，不修改任何报告
# 依赖：仅 Tcl 标准库
# =============================================================================

package require Tcl 8.5

proc slurp {path} {
    if {![file exists $path]} { return "" }
    set fp [open $path r]
    fconfigure $fp -encoding utf-8
    set data [read $fp]
    close $fp
    return $data
}

proc dget {d key} {
    if {[dict exists $d $key]} { return [dict get $d $key] }
    return ""
}

# 从一份 max.rpt 里抽出关键信息
proc parse_path {file} {
    set text [slurp $file]
    set r [dict create]
    if {$text eq ""} { return $r }

    if {[regexp {Startpoint:\s+(\S+)} $text -> v]} { dict set r start $v }
    if {[regexp {Endpoint:\s+(\S+)}   $text -> v]} { dict set r end   $v }
    if {[regexp {Path Group:\s+(\S+)} $text -> v]} { dict set r group $v }
    if {[regexp {Path Type:\s+(\S+)}  $text -> v]} { dict set r type  $v }

    # slack：第一处 "<num>   slack (MET|VIOLATED)"
    if {[regexp {(-?[\d.]+)\s+slack \((MET|VIOLATED)\)} $text -> v status]} {
        dict set r slack $v
        dict set r status $status
    }

    # 逐行统计 cell 延时：
    #   行样例： 0.15    0.21    2.18 ^ _09244_/X (sky130_fd_sc_hd__buf_6)
    #   三个数依次是 slew、delay、time；只要第 3 个数字后面跟 ^/v 且带 (sky130…) 就是 cell 行
    set cell_delay 0.0
    set cell_n 0
    foreach line [split $text "\n"] {
        if {[string first "sky130" $line] < 0} { continue }
        if {[regexp {\s(\d+\.\d+)\s+(\d+\.\d+)\s+\d+\.\d+\s+[\^v]\s+\S+\s+\(sky130} $line -> slew delay]} {
            set cell_delay [expr {$cell_delay + $delay}]
            incr cell_n
        }
    }
    dict set r cell_delay [format %.2f $cell_delay]
    dict set r cell_stages $cell_n

    # 总 data arrival time；net 延时 = arrival - cell 延时
    if {[regexp {([\d.]+)\s+data arrival time} $text -> v]} {
        dict set r arrival $v
        dict set r net_delay [format %.2f [expr {$v - $cell_delay}]]
    }
    return $r
}

# ---------------------------------------------------------------- main
if {[llength $argv] < 1} {
    puts stderr "用法: tclsh parse_paths.tcl <runs_dir> \[--csv\]"
    exit 1
}

set root [lindex $argv 0]
set as_csv [expr {[lsearch -exact $argv "--csv"] >= 0}]

if {![file isdirectory $root]} {
    puts stderr "目录不存在: $root"
    exit 1
}

set runs {}
foreach d [glob -nocomplain -directory $root -types d *] {
    if {[file isdirectory [file join $d reports signoff]]} { lappend runs $d }
}
set runs [lsort $runs]

if {[llength $runs] == 0} {
    puts stderr "在 $root 下没找到含 reports/signoff 的 run"
    exit 1
}

if {$as_csv} {
    puts "run,slack,status,group,startpoint,endpoint,cell_stages,cell_delay_ns,net_delay_ns,arrival_ns"
}

foreach run $runs {
    set name [file tail $run]
    set f [file join $run reports signoff 31-rcx_sta.max.rpt]
    if {![file exists $f]} { continue }

    set p [parse_path $f]
    if {[dict size $p] == 0} { continue }

    if {$as_csv} {
        puts [join [list \
            $name \
            [dget $p slack] \
            [dget $p status] \
            [dget $p group] \
            [dget $p start] \
            [dget $p end] \
            [dget $p cell_stages] \
            [dget $p cell_delay] \
            [dget $p net_delay] \
            [dget $p arrival]] ,]
    } else {
        puts "===== $name ====="
        puts "  slack     : [dget $p slack] ns ([dget $p status])"
        puts "  startpoint: [dget $p start]"
        puts "  endpoint  : [dget $p end]"
        puts "  group/type: [dget $p group] / [dget $p type]"
        puts "  cell 段   : [dget $p cell_stages] 级，合计 [dget $p cell_delay] ns"
        puts "  net  段   : [dget $p net_delay] ns"
        puts "  arrival   : [dget $p arrival] ns"
        puts ""
    }
}
