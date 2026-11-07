# 数字后端与 AI+EDA 自动化脚本 (Tcl & Python)

本目录包含我在跑通 PicoRV32 OpenLane 流程及探索 AI 赋能后端时，编写的自动化解析与诊断脚本。

## 1. qor_summary.tcl
- **功能**：读取 `metrics.csv`，快速打印 WNS、TNS、Setup/Hold 违例数。
- **用法**：`tclsh qor_summary.tcl`

## 2. parse_all_violations.tcl
- **功能**：解析 `31-rcx_sta.checks.rpt`，自动提取 Max Fanout / Slew / Cap 违例的具体引脚和数值。
- **用法**：`tclsh parse_all_violations.tcl`

# 3.🛠️ OpenLane 全栈日志自动体检与 AI 诊断工具 (openlane_analyzer.py)

本脚本是一个工业级的 OpenLane Run 目录综合体检工具。它能自动深度扫描整个运行目录（包含日志、STA报告、物理验证报告等），精准抓取从致命错误到物理违例的所有异常，并可一键呼叫大模型（LLM）进行根因分析与修复指导。

## 🌟 核心亮点 (Features)

*   **全栈深度扫描**：不仅看 `.rpt` 报告，还能深入 `logs/signoff/` 抓取隐藏的 `Fatal error` 和 `ERC`（如 Decap 子电路缺失）致命错误。
*   **严重度智能分级**：自动将问题划分为 `CRITICAL / ERROR / WARNING / INFO`。
*   **极致省 Token (防呆机制)**：
    *   **默认极简**：调用 AI 时，默认只发送最高危的 `CRITICAL` 级别（通常只有1-3条）。
    *   **文本截断**：每行详情截断至 200 字符，防止上下文炸裂。
    *   **自动去重**：忽略并合并几百条无用的 filler/decap 黑盒警告。
*   **零依赖本地跑**：不使用 AI 功能时，仅依赖 Python 3.8+ 标准库，不花一分钱即可完成本地体检。

## 🚀 快速使用 (Quick Start)

将脚本放入 WSL 的 `~/scripts/` 目录下，并确保有执行权限。

```bash
# 1. 纯本地体检（0 Token 成本，最快、最推荐）
# 生成 analysis/report.md 结构化报告
python3 ~/scripts/openlane_analyzer.py /path/to/your/run_dir

# 2. 极速判断这一版能不能过（只看致命错误）
python3 ~/scripts/openlane_analyzer.py /path/to/your/run_dir --only-critical

# 3. 呼叫 AI 医生（最省钱模式，仅发送 CRITICAL 级别）
export DEEPSEEK_API_KEY="sk-你的Key"
python3 ~/scripts/openlane_analyzer.py /path/to/your/run_dir --ai

# 4. 放宽限制，让 AI 分析 Error 甚至 Warning
python3 ~/scripts/openlane_analyzer.py /path/to/your/run_dir --ai --ai-severity ERROR

# 5. 脚本自测（验证正则解析器是否完好）
python3 ~/scripts/openlane_analyzer.py --self-test
```

# 4. 📊 `collect_metrics.tcl` (多 Run 数据一键汇总)

**工程痛点**：做参数扫描（如对比 8ns、6ns、5ns 的设计）时，需要手动打开几十个 `summary.rpt`、`metrics.csv` 抄写 WNS、面积、功耗等数据。
**功能**：一键遍历指定目录下的所有 run 文件夹，自动提取关键指标并生成一张干净的 CSV 表格。

### 🛠️ 使用方法

```bash
# 基础用法（Tcl 无法展开 ~，请用 $HOME 或绝对路径）
tclsh collect_metrics.tcl $HOME/OpenLane/designs/picorv32/runs

# 只匹配特定名字的 run（例如只抓 sweep 开头的实验）
tclsh collect_metrics.tcl $HOME/OpenLane/designs/picorv32/runs 'sweep_*'

# 将结果导出为 CSV 文件，方便用 Excel 画图分析
tclsh collect_metrics.tcl $HOME/OpenLane/designs/picorv32/runs > all_results.csv
```


## 5. 🔍 parse_paths.tcl (最差时序路径解剖刀)
工程痛点：31-rcx_sta.max.rpt 报告动辄几万行，用 cat 或 less 查找最差路径的 Startpoint 和 Endpoint 极耗时间。
功能：批量读取每个 run 的时序报告，将最差路径的信息压缩成一行，直观展示 Cell 延时与 Net 延时的占比。

🛠️ 使用方法
bash
# 在终端打印人可读的摘要
tclsh parse_paths.tcl $HOME/OpenLane/designs/picorv32/runs

# 生成 CSV 格式，方便后续处理
tclsh parse_paths.tcl $HOME/OpenLane/designs/picorv32/runs --csv > paths.csv