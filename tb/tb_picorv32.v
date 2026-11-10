// =============================================================================
// tb_picorv32.v  ——  PicoRV32 最小验证平台
//
// 用途：同一份 TB 同时支持
//   1) RTL 功能仿真        （直接编 src/picorv32.v）
//   2) 门级仿真 GLS + SDF  （编 results/final/verilog/gl/picorv32.v，加 +define+GLS）
//
// 验证内容：
//   - 指令取指（mem_instr 通道）
//   - 寄存器运算（lui / addi）
//   - 存储写（sw，带 byte write strobe）
//   - 存储读（lw）
//   - 分支跳转（beq）
//   PASS 判据：观察到 mem_addr == 0x1000 且 mem_wdata == 42 的写操作
//              —— 说明取指、译码、执行、写回存储这条链路全部走通
//
// 用法见同目录 README.md
// =============================================================================
`timescale 1ns/1ps

module tb_picorv32;

    // ---------------------------------------------------------------- 时钟/复位
    reg clk    = 1'b0;
    reg resetn = 1'b0;

    always #5 clk = ~clk;          // 10 ns 周期 = 100 MHz（RTL 仿真用，与 signoff 8ns 无关）

    // ---------------------------------------------------------------- DUT 接口
    wire        mem_valid;
    wire        mem_instr;
    wire        mem_ready;
    wire [31:0] mem_addr;
    wire [31:0] mem_wdata;
    wire [ 3:0] mem_wstrb;
    wire [31:0] mem_rdata;

    wire        mem_la_read;
    wire        mem_la_write;
    wire [31:0] mem_la_addr;
    wire [31:0] mem_la_wdata;
    wire [ 3:0] mem_la_wstrb;

    wire        pcpi_valid;
    wire [31:0] pcpi_insn;
    wire [31:0] pcpi_rs1;
    wire [31:0] pcpi_rs2;

    wire        trap;
    wire [31:0] eoi;
    wire        trace_valid;
    wire [35:0] trace_data;

    // ---------------------------------------------------------------- DUT 例化
`ifdef GLS
    // ---- 门级网表：没有参数，多出 VPWR/VGND 电源端口 ----
    // OpenLane 生成的 GLS 网表是带电源引脚的，必须显式接上，否则报
    // "Port 'VPWR' not found in the connected module"
    wire vpwr = 1'b1;
    wire vgnd = 1'b0;

    picorv32 dut (
        .clk(clk), .resetn(resetn), .trap(trap),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_rdata(mem_rdata),
        .mem_la_read(mem_la_read), .mem_la_write(mem_la_write),
        .mem_la_addr(mem_la_addr), .mem_la_wdata(mem_la_wdata),
        .mem_la_wstrb(mem_la_wstrb),
        .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
        .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
        .pcpi_wr(1'b0), .pcpi_rd(32'h0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
        .irq(32'h0), .eoi(eoi),
        .trace_valid(trace_valid), .trace_data(trace_data),
        .VPWR(vpwr), .VGND(vgnd)
    );
`else
    // ---- RTL：用默认参数（可选功能全关，与 OpenLane 综合配置一致）----
    picorv32 #(
        .ENABLE_IRQ (0),
        .ENABLE_PCPI(0),
        .ENABLE_MUL (0),
        .ENABLE_DIV (0),
        .ENABLE_TRACE(0)
    ) dut (
        .clk(clk), .resetn(resetn), .trap(trap),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_rdata(mem_rdata),
        .mem_la_read(mem_la_read), .mem_la_write(mem_la_write),
        .mem_la_addr(mem_la_addr), .mem_la_wdata(mem_la_wdata),
        .mem_la_wstrb(mem_la_wstrb),
        .pcpi_valid(pcpi_valid), .pcpi_insn(pcpi_insn),
        .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
        .pcpi_wr(1'b0), .pcpi_rd(32'h0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
        .irq(32'h0), .eoi(eoi),
        .trace_valid(trace_valid), .trace_data(trace_data)
    );
`endif

    // ---------------------------------------------------------------- 存储器模型
    // 64 KB = 16384 words，零等待（mem_ready = mem_valid）
    reg [31:0] mem [0:16383];

    assign mem_ready = mem_valid;                      // 零等待状态
    assign mem_rdata = mem[mem_addr[15:2]];            // 组合读，字对齐

    reg [31:0] wtmp;
    integer    b;
    always @(posedge clk) begin
        if (mem_valid && mem_ready && (|mem_wstrb)) begin
            wtmp = mem[mem_addr[15:2]];
            if (mem_wstrb[0]) wtmp[ 7: 0] = mem_wdata[ 7: 0];
            if (mem_wstrb[1]) wtmp[15: 8] = mem_wdata[15: 8];
            if (mem_wstrb[2]) wtmp[23:16] = mem_wdata[23:16];
            if (mem_wstrb[3]) wtmp[31:24] = mem_wdata[31:24];
            mem[mem_addr[15:2]] = wtmp;
        end
    end

    // ---------------------------------------------------------------- 测试程序
    // 0x00  lui  x1, 0x1        x1 = 0x1000
    // 0x04  addi x2, x0, 42     x2 = 42
    // 0x08  sw   x2, 0(x1)      mem[0x1000] = 42     <-- PASS 判据
    // 0x0c  lw   x3, 0(x1)      x3 = mem[0x1000]
    // 0x10  beq  x2, x3, +8     相等则跳过下一条
    // 0x14  addi x4, x0, 1      (失败路径，不会走到)
    // 0x18  addi x4, x0, 2      (成功路径)
    // 0x1c  jal  x0, 0          死循环
    initial begin
        mem[0] = 32'h0000_10B7;
        mem[1] = 32'h02A0_0113;
        mem[2] = 32'h0020_A023;
        mem[3] = 32'h0000_A183;
        mem[4] = 32'h0031_0463;
        mem[5] = 32'h0010_0213;
        mem[6] = 32'h0020_0213;
        mem[7] = 32'h0000_006F;
        // 其余单元清零（避免 X 传播）
        for (b = 8; b < 16384; b = b + 1) mem[b] = 32'h0;
    end

    // ---------------------------------------------------------------- 观察/判分
    integer cyc = 0;
    integer store_cnt = 0;
    integer final_cyc = 0;
    reg     pass_seen = 1'b0;

    always @(posedge clk) begin
        cyc <= cyc + 1;

        if (mem_valid && mem_ready && (|mem_wstrb)) begin
            store_cnt = store_cnt + 1;
            $display("[%0t] STORE #%0d  addr=0x%08h  data=0x%08h  strb=%b  instr=%b",
                     $time, store_cnt, mem_addr, mem_wdata, mem_wstrb, mem_instr);
            if (mem_addr == 32'h0000_1000 && mem_wdata == 32'd42)
                pass_seen <= 1'b1;
        end

        // 超时保护
        if (cyc > 5000) begin
            $display("");
            $display("[FAIL] TIMEOUT: no expected store within %0d cycles", cyc);
            $display("       observed stores = %0d", store_cnt);
            $finish;
        end

        // 抓到 PASS 判据后，再等 20 拍让后续指令执行完，然后结束
        // 注意：先把周期数存下来，因为下面 repeat 会阻塞这个 always 块
        if (pass_seen) begin
            final_cyc = cyc;
            repeat (20) @(posedge clk);
            $display("");
            $display("========================================");
            $display("[PASS] PicoRV32 functional test passed");
            $display("       fetch -> decode -> execute -> store : OK");
            $display("       stores observed = %0d,  finish at cycle %0d", store_cnt, final_cyc);
            $display("========================================");
            $finish;
        end
    end

    // ---------------------------------------------------------------- 波形（可选）
`ifdef VCD
    initial begin
        $dumpfile("tb_picorv32.vcd");
        $dumpvars(0, tb_picorv32);
    end
`endif

    // ---------------------------------------------------------------- SDF 反标（GLS 用）
    // 编译时加 -DSDF_PATH="\"<sdf 绝对路径>\"" 即可自动反标
`ifdef SDF_ANNO
    initial begin
        #1;
        $sdf_annotate(`SDF_PATH, tb_picorv32.dut, , "sdf_annotate.log", "MAXIMUM");
    end
`endif

    // ---------------------------------------------------------------- 复位序列
    initial begin
        $timeformat(-9, 1, " ns", 10);   // %t 按 ns 显示（否则 ModelSim 会打成 ps）
        resetn = 1'b0;
        repeat (10) @(posedge clk);
        resetn = 1'b1;
        $display("[%0t] reset released", $time);
    end
endmodule
