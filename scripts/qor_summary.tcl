set filename "reports/metrics.csv"
if {![file exists $filename]} {
    puts "错误：找不到 $filename"
    exit 1
}

set fp [open $filename r]
# 读取第一行：表头（Key）
set header_line [gets $fp]
set headers [split $header_line ","]

# 读取第二行：数据（Value）
set data_line [gets $fp]
set values [split $data_line ","]
close $fp

puts "========================================"
puts "         PicoRV32 QoR 报告             "
puts "========================================"

foreach key {"wns" "tns" "setup_violations" "hold_violations" "max_fanout_violations" "max_slew_violations"} {
    set index [lsearch $headers $key]
    if {$index != -1} {
        set val [lindex $values $index]
        puts [format "%-25s : %s" $key $val]
    }
}
puts "========================================"
puts "========================================"
puts "          物理与功耗指标                "
puts "========================================"
foreach key {"DIEAREA_mm^2" "TotalCells" "wire_length" "vias" "power_typical_internal_uW" "power_typical_switching_uW"} {
    set index [lsearch $headers $key]
    if {$index != -1} {
        set val [lindex $values $index]
        puts [format "%-30s : %s" $key $val]
    }
}