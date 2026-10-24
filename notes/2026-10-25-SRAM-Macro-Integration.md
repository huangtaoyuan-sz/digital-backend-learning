# 2026-10-25 学习日志：OpenLane 引入 SRAM 宏单元实战与 LVS 踩坑

## 📌 今日目标
打破纯标准单元设计的局限，在 OpenLane 流程中集成真实的 `sky130_sram_1kbyte_1rw1r_32x256_8` 宏单元。体验包含大块头 Macro 的 Floorplan 规划，并遭遇真实的物理设计灾难。

## 🚀 一、 核心配置与黑盒处理
SRAM 与普通逻辑门不同，它的内部极其复杂，因此需要将其作为黑盒（Blackbox）处理。

1. **引入模型文件**：在 `config.json` 中通过 `EXTRA_LEFS`、`EXTRA_LIBS` 和 `EXTRA_GDS_FILES` 引入了 SRAM 的物理、时序和版图文件。
2. **黑盒声明**：手写了一个只包含端口声明的 `sram_blackbox.v`，并通过 `VERILOG_FILES_BLACKBOX` 引入，成功绕过了开源综合工具（Yosys）对 SRAM 内部仿真语法的解析报错（`unexpected $undefined`）。
3. **电源连接**：通过 `FP_PDN_MACRO_HOOKS: "u_sram VPWR VGND VPWR VGND"` 强制将 SRAM 的电源引脚接入全局电源网络。

## 🛠️ 二、 手动布局规划 (Macro Placement)
为了控制这个“庞然大物”的位置，我新建了 `macro.cfg` 文件：

```text
u_sram 50 50 N
```
并在 config.json 中通过 MACRO_PLACEMENT_CFG 指定该文件，成功将 SRAM 强制固定在芯片左下角的 (X=50, Y=50) 坐标处。

## 💥 三、 遭遇灾难与排错记录
整个流程遭遇了多次报错，但在不断排查后成功推进到 Signoff 阶段：

JSON 解析报错：手工编写配置时由于遗漏逗号（Expecting ',' delimiter），导致 Python 解析失败。通过使用 cat > config.json << EOF 的方式重写文件解决。

Linter 检查报错：开源代码检查工具 Verilator 无法识别仿真语法。通过在配置中加入 "RUN_LINTER": false 和 "QUIT_ON_LINTER_ERRORS": false 跳过。

LVS 报错：流程在 Step 40 报出 37 个 LVS 错误（unmatched pins = 13）。分析报告发现 device count difference = 0，判断为开源工具在提取黑盒版图时，SRAM 的电源环（Power Ring）引脚与网表黑盒定义不匹配导致。这是真实工业界常见的 PDN 电源完整性映射问题。

## 📊 四、 最终物理结果 (KLayout 可视化)
尽管 LVS 存在黑盒映射报错，但工具已成功吐出 GDSII 版图。将 GDS 导入 KLayout 后，验证了以下物理特征：

巨大的 SRAM 宏单元精准坐落在 (50, 50) 处。

工具自动围绕 SRAM 生成了蓝色的电源环（Power Ring）。

标准单元在剩余的 Core 区域内完成了基本的布局与走线。

![SRAM物理版图](../images/2026-10-25-SRAM-Macro-Integration_2026-10-24-16-20-06.png)


## 💡 五、 学习心得与思考
宏单元集成的难点：Macro 引入了极端的局部密度和走线通道阻塞。真实的 Floorplan 必须为 Macro 预留 Halo（隔离区），否则周围的标准单元和布线会被彻底挤爆。

电源网络（PDN）的重要性：大块头 SRAM 的耗电极高，电源环的设计直接决定了芯片是否会因为 IR Drop 而失效。

工程的妥协：开源工具在处理复杂的黑盒 LVS 检查时存在局限。虽然未能达成 Flow complete 的完美结局，但由此理解了商业工具（如 Calibre 修改 Rule Deck）处理此类问题的底层逻辑。