# 文件名：parse_all_violations.tcl
# 功能：解析 31-rcx_sta.checks.rpt，打印所有违例

set filename "reports/signoff/31-rcx_sta.checks.rpt"
if {![file exists $filename]} {
    puts "错误：找不到 $filename，请确保在 openlane_test 目录下运行。"
    exit 1
}

set fp [open $filename r]
set count 0
set current_section ""

while {[gets $fp line] >= 0} {
    set line [string trim $line]
    
    # 识别当前处于哪个违例区域
    if {[string match "*max fanout*" $line]} { set current_section "MAX FANOUT"; puts "\n--- $current_section 违例 ---" }
    if {[string match "*max slew*" $line]}   { set current_section "MAX SLEW";   puts "\n--- $current_section 违例 ---" }
    if {[string match "*max cap*" $line]}    { set current_section "MAX CAP";    puts "\n--- $current_section 违例 ---" }

    # 匹配带有 VIOLATED 的行
    if {[string match "*VIOLATED*" $line]} {
        puts "  $line"
        incr count
    }
}
close $fp
puts "\n========================================"
puts "总违例数量：$count"
puts "========================================"
