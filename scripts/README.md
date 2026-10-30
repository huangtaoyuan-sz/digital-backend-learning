# 数字后端与 AI+EDA 自动化脚本 (Tcl & Python)

本目录包含我在跑通 PicoRV32 OpenLane 流程及探索 AI 赋能后端时，编写的自动化解析与诊断脚本。

## 1. qor_summary.tcl
- **功能**：读取 `metrics.csv`，快速打印 WNS、TNS、Setup/Hold 违例数。
- **用法**：`tclsh qor_summary.tcl`

## 2. parse_all_violations.tcl
- **功能**：解析 `31-rcx_sta.checks.rpt`，自动提取 Max Fanout / Slew / Cap 违例的具体引脚和数值。
- **用法**：`tclsh parse_all_violations.tcl`

## 3. ai_sta_analyzer.py (✨ AI 赋能)
- **功能**：基于 LLM API 构建的智能时序报告分析工具。
- **核心特性**：
  - **智能搜索**：不传参数时，自动扫描当前目录下的 `.rpt` 文件。
  - **防呆拦截**：内置正则会先检查报告。若无 `VIOLATED` 违例则直接退出，节省 API 成本；有违例才呼叫大模型进行延迟拆解并生成 `size_cell` 修复脚本。
  - **结果落盘**：自动生成 `ai_analysis_result.md` 报告。
- **用法**：
  `# 方式一：自动搜索当前目录报告
  `python3 ai_sta_analyzer.py`
  `# 方式二：指定报告路径
  `python3 ai_sta_analyzer.py ./31-rcx_sta.max.rpt`