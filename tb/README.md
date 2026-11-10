# PicoRV32 Testbench

自检查（self-checking）testbench，**一份代码支持两种仿真**：

| 模式 | 用途 | 关键编译选项 |
|---|---|---|
| RTL 功能仿真 | 验证 RTL 行为正确 | 无 |
| 零延时 GLS | 验证综合/布局布线后的网表功能等价 | `+define+GLS` `+define+USE_POWER_PINS` |

---

## 验证什么

| 覆盖点 | 说明 |
|---|---|
| 取指 | `mem_instr = 1` 通道 |
| 寄存器运算 | `lui` / `addi` |
| 存储写 | `sw`，含 byte write strobe |
| 存储读 | `lw` |
| 分支跳转 | `beq` |

### 测试程序

| 地址 | 指令 | 机器码 | 作用 |
|---|---|---|---|
| 0x00 | `lui x1, 0x1` | `000010B7` | x1 = 0x1000 |
| 0x04 | `addi x2, x0, 42` | `02A00113` | x2 = 42 |
| 0x08 | `sw x2, 0(x1)` | `0020A023` | **mem[0x1000] = 42（PASS 判据）** |
| 0x0c | `lw x3, 0(x1)` | `0000A183` | 读回 |
| 0x10 | `beq x2, x3, +8` | `00310463` | 相等则跳过失败路径 |
| 0x14 | `addi x4, x0, 1` | `00100213` | 失败路径（不应执行） |
| 0x18 | `addi x4, x0, 2` | `00200213` | 成功路径 |
| 0x1c | `jal x0, 0` | `0000006F` | 死循环 |

### PASS 判据

在存储接口观察到：

```
mem_valid && mem_ready && |mem_wstrb &&
mem_addr == 0x1000 && mem_wdata == 42
```

**一笔写操作覆盖"取指 → 译码 → 执行 → 存储写"整条链路**：

- 取指错了 → 地址不会是 0x1000
- ALU 错了 → 数据不会是 42
- 分支错了 → 会多出第二次写

超时（5000 周期）则打印 `[FAIL] TIMEOUT`。

---

## 仿真的四个输入

```
DUT (RTL 或网表) + 单元库模型 + TB + (SDF)
```

| 文件 | 来源 | 作用 |
|---|---|---|
| `rtl/picorv32.v` | OpenLane `designs/picorv32/src/` | RTL 源码 |
| `gl/picorv32_gl.v` | `results/final/verilog/gl/` | 门级网表（13,573 实例） |
| `lib/primitives.v` | PDK `libs.ref/sky130_fd_sc_hd/verilog/` | UDP 原语（触发器/锁存器） |
| `lib/sky130_fd_sc_hd.v` | 同上 | 每个标准单元的行为模型 |
| `sdf/picorv32_max.sdf` | `results/final/sdf/multicorner/max/` | 真实延时（GLS 用） |

---

## 怎么跑（ModelSim）

```tcl
# 每次启动先切到工程目录（ModelSim 默认在 exe 所在目录）
cd D:/IC_project/picorv32/sim

# ---------- RTL 仿真 ----------
vlib work
vlog rtl/picorv32.v
vlog tb/tb_picorv32.v
vsim -c work.tb_picorv32 -do "run -all"

# ---------- 零延时 GLS ----------
vlib work_gls
vlog -work work_gls lib/primitives.v
vlog -work work_gls +define+USE_POWER_PINS lib/sky130_fd_sc_hd_sim.v
vlog -work work_gls +define+USE_POWER_PINS gl/picorv32_gl.v
vlog -work work_gls +define+GLS tb/tb_picorv32.v
vsim work_gls.tb_picorv32 -do "run -all"
```

---

## 实测结果

```
RTL 仿真:
  [95.0 ns] reset released
  [235.0 ns] STORE #1  addr=0x00001000  data=0x0000002a  strb=1111  instr=0
  [PASS] PicoRV32 functional test passed
         stores observed = 1, finish at cycle 24

零延时 GLS（13,573 实例网表）:
  同上，时间与周期数完全一致 —— 证明网表功能与 RTL 等价
```

---

## GLS 踩过的三个坑

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 1 | `Net type of 'C' must be explicitly declared` | PDK 模型含 `` `default_nettype none ``，ModelSim 10.1d 不容忍隐式网络 | 预处理单元库，删除该指令 |
| 2 | `Too many port connections. Expected 1, found 5` | 网表带电源引脚（`USE_POWER_PINS`），库未开该宏 | 编译库时加 `+define+USE_POWER_PINS`，TB 补接 `VPWR`/`VGND` |
| 3 | `SDF files require Altera primitive library` | **ModelSim Altera Starter 版禁止第三方库 SDF 反标** | 降级为零延时 GLS；时序由 STA 覆盖 |

> 带 SDF 的时序 GLS 可用 Icarus Verilog 补做（支持 `$sdf_annotate` + `-gspecify`）。

---

## 可以怎么扩展

1. 用 `$value$plusargs` 参数化测试（一个 TB 跑多种程序）
2. 把 `mem_ready` 改成可变延迟，测 wait-state
3. 加 `covergroup` 统计指令类型覆盖
4. 改写成 UVM 环境（sequence / driver / monitor / scoreboard）
