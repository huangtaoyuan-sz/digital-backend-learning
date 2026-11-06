


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
openlane_analyzer.py  ——  OpenLane 综合日志/报告分析器（省 token 版）

用法:
    python3 openlane_analyzer.py <run_dir>                       # 纯本地规则，0 token
    python3 openlane_analyzer.py <run_dir> --ai                  # 只把 CRITICAL 发给 AI
    python3 openlane_analyzer.py <run_dir> --ai --ai-severity ERROR   # 放宽到 ERROR 级
    python3 openlane_analyzer.py <run_dir> --only-critical       # 只看关键问题
    python3 openlane_analyzer.py --self-test                     # 自测

run_dir 指 OpenLane 的 run 目录，例如:
    ~/OpenLane/designs/picorv32/runs/openlane_test
脚本会自动从该目录下读取:
    openlane.log, warnings.log, config.tcl,
    reports/signoff/31-rcx_sta.checks.rpt, 31-rcx_sta.summary.rpt,
    31-rcx_sta.power.rpt, 31-rcx_sta.skew.rpt,
    32-irdrop-VPWR.rpt, 32-irdrop-VGND.rpt,
    39-*.lvs.rpt, drc.rpt, 41-antenna_violators.rpt,
    logs/**/*.log  (用于抓 Fatal / Error / 黑盒)
最后在 run_dir 下写出:
    analysis/report.md          # 人读的 Markdown 报告
    analysis/issues.json        # 机器读的问题清单
    analysis/ai_context.txt     # 给 LLM 的精简上下文（默认只含 CRITICAL）
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# 1. 数据结构
# ---------------------------------------------------------------------------

# 严重度：数字越小越严重
SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}

SEVERITY_ICON = {
    "CRITICAL": "🔴",
    "ERROR": "🟠",
    "WARNING": "🟡",
    "INFO": "🔵",
}


@dataclass
class Issue:
    """一条被解析出来的问题。"""
    severity: str          # CRITICAL / ERROR / WARNING / INFO
    category: str          # 问题大类，例如 "ERC" / "STA" / "DRC"
    title: str             # 一句话描述
    detail: str = ""       # 细节（原始行、上下文）
    source: str = ""       # 来自哪个文件
    line: int = 0          # 行号（1-based，0 表示未知）
    hint: str = ""         # 建议的排查方向
    raw: str = ""          # 原始文本片段

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "source": self.source,
            "line": self.line,
            "hint": self.hint,
        }


@dataclass
class AnalysisResult:
    issues: list[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    files_seen: list[str] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def sorted_issues(self) -> list[Issue]:
        return sorted(
            self.issues,
            key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.category, i.source, i.line),
        )

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)


# ---------------------------------------------------------------------------
# 2. 通用工具
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> Path:
    """
    稳健地创建目录树（含父目录）。

    为什么不用 pathlib 的 parents=True：某些受限环境（如带 ACL 拦截的沙箱、
    挂载的 WSL 路径）下，Python 的递归 mkdir 会在中间层报 WinError 5 / 3。
    这里改为「从最上层存在的祖先开始，逐级 mkdir」，每级单独容错，
    任何一级已存在或失败都能继续。
    """
    path = path.resolve() if not path.is_absolute() else path
    chain: list[Path] = []
    cur = path
    while True:
        chain.append(cur)
        if cur.parent == cur or cur.exists():
            break
        cur = cur.parent
    for d in reversed(chain):
        try:
            if d.exists():
                continue
            d.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            print(f"  [warn] 无法创建目录 {d}: {exc}", file=sys.stderr)
    return path


def read_text(path: Path) -> Optional[str]:
    """安全读取文本；.gz 自动解压；不存在返回 None。"""
    if not path.exists():
        return None
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                return f.read()
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, EOFError) as exc:
        # 空文件或损坏的 gz 不该让整个分析崩掉
        print(f"  [warn] 读取失败 {path}: {exc}", file=sys.stderr)
        return None


def iter_lines(path: Path, limit: Optional[int] = None) -> Iterable[tuple[int, str]]:
    """逐行产出 (行号, 内容)，避免把几 GB 日志一次性读进内存。"""
    text = read_text(path)
    if text is None:
        return
    for idx, line in enumerate(text.splitlines(), start=1):
        yield idx, line
        if limit is not None and idx >= limit:
            break


def first_match(patterns: Iterable[str], line: str) -> Optional[re.Match]:
    for pat in patterns:
        m = re.search(pat, line)
        if m:
            return m
    return None


# ---------------------------------------------------------------------------
# 3. 各个解析器
# ---------------------------------------------------------------------------

def parse_openlane_log(run_dir: Path, res: AnalysisResult) -> None:
    """openlane.log / warnings.log：流程级日志。同样的告警会在两处重复，需要去重。"""
    seen_lines: set[str] = set()
    for name in ("openlane.log", "warnings.log"):
        path = run_dir / name
        text = read_text(path)
        if text is None:
            continue
        res.files_seen.append(str(path))
        for ln, line in iter_lines(path):
            s = line.strip()
            if not s:
                continue
            # 流程是否完成
            if "[SUCCESS]" in line or "Flow complete" in line:
                res.metrics["flow_complete"] = True
            if "VSRC_LOC_FILES is not defined" in line:
                # 该告警在校验 config 时已单独报出，这里只登记去重，避免重复
                seen_lines.add(s)
                continue
            # 明确的失败
            if first_match([r"\[ERROR\]", r"\[FATAL\]", r"Error:", r"Fatal error"], line):
                if s in seen_lines:
                    continue
                seen_lines.add(s)
                res.add(Issue("CRITICAL", "FLOW", "流程报错",
                              detail=s, source=name, line=ln,
                              hint="查看 logs/ 下对应阶段的子日志定位根因"))
            elif first_match([r"\[WARNING\]"], line):
                # 同样的告警在 openlane.log 与 warnings.log 各出现一次，按文本去重
                if s in seen_lines:
                    continue
                seen_lines.add(s)
                res.add(Issue("WARNING", "FLOW", "流程告警",
                              detail=s, source=name, line=ln))


def classify_warnings(res: AnalysisResult) -> None:
    """把 openlane.log 里泛化的 WARNING 重新归类，避免所有告警都长一样。"""
    for issue in res.issues:
        if issue.category != "FLOW" or issue.severity != "WARNING":
            continue
        d = issue.detail
        if "blackboxed during sta" in d:
            issue.category = "BLACKBOX"
            issue.title = "单元在 STA 中被黑盒化"
            issue.hint = "该单元没有时序模型；fill/decap/tap 正常，但若是 SRAM 或 macro 则会导致时序不完整"
        elif "max slew violations" in d:
            issue.category = "STA"
            issue.title = "存在 max slew 违例（驱动能力不足）"
            issue.hint = "读 STA 日志里 report_object_max_slew 段，对高扇出/弱驱动单元换强驱动"
        elif "max fanout violations" in d:
            issue.category = "STA"
            issue.title = "存在 max fanout 违例（单节点负载过多）"
            issue.hint = "读 STA 日志里 report_object_max_fanout 段，插 buffer 或调 set_max_fanout"
        elif "warnings found by linter" in d:
            issue.category = "LINT"
            issue.title = "Verilog linter 告警"
            issue.hint = "查看 synthesis 日志中的 linter 输出，通常不改功能但影响可综合性"
        elif "Power pins" in d or "power" in d.lower():
            issue.category = "POWER"
            issue.title = "电源相关告警"
        else:
            issue.category = "OTHER"
            issue.title = "未归类告警"
            issue.hint = "人工确认是否影响签核"


def parse_sub_logs(run_dir: Path, res: AnalysisResult) -> None:
    """
    遍历 logs/**/*.log，抓 Fatal error / Error。
    关键点：原脚本只看 .rpt，漏掉了 logs/signoff/42-erc_screen.log 里的
    "Fatal error: could not find subcircuit ..."。
    """
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return
    fatal_re = re.compile(r"Fatal error", re.IGNORECASE)
    error_re = re.compile(r"^\s*(?:ERROR|Error)\b|\*\* ERROR")
    subcircuit_re = re.compile(r"could not find subcircuit:\s*([\w]+)\(([\w\d_]+)\)")
    seen: set[tuple[str, str]] = set()

    for log in sorted(logs_dir.rglob("*.log")):
        try:
            rel = str(log.relative_to(run_dir))
        except ValueError:
            rel = str(log)
        for ln, line in iter_lines(log):
            s = line.strip()
            if not s:
                continue
            m = subcircuit_re.search(line)
            if m:
                key = ("SUB", m.group(2))
                if key in seen:
                    continue
                seen.add(key)
                res.add(Issue(
                    "CRITICAL", "ERC",
                    f"ERC 找不到子电路定义：{m.group(2)}",
                    detail=s, source=rel, line=ln,
                    hint=(
                        "SPICE/CDL 网表中缺少该单元的实现，常见于 filler/decap 被当作黑盒导出。"
                        "影响：物理验证层面 LVS 仍可能通过，但电路级（后仿/CVC）网表不完整。"
                        "修法：① 检查 PDK 的 SPICE 模型是否包含该单元；"
                        "② 在导出 CDL 时排除 filler/decap 或加入其模型；"
                        "③ 或把该单元加入 EXCLUDE_CELLS。"
                    ),
                ))
            # 子电路缺失往往同时以 Fatal 形式出现，两者是同一事件，不再重复记
            elif fatal_re.search(line):
                res.add(Issue("CRITICAL", "FLOW", "子日志出现 Fatal error",
                              detail=s, source=rel, line=ln,
                              hint=f"打开 {rel} 查看完整错误上下文"))
            elif error_re.search(line):
                res.add(Issue("ERROR", "FLOW", "子日志出现 Error",
                              detail=s, source=rel, line=ln))


def parse_log_errors(run_dir: Path, res: AnalysisResult) -> None:
    """
    在 run 根目录的 .log 文件里也抓 Fatal。
    parse_sub_logs 只看 logs/ 子目录，而 openlane.log / warnings.log 在根目录。
    """
    fatal_re = re.compile(r"Fatal error")
    for path in sorted(run_dir.glob("*.log")):
        for ln, line in iter_lines(path):
            if fatal_re.search(line):
                res.add(Issue("CRITICAL", "FLOW", "日志出现 Fatal error",
                              detail=line.strip(), source=path.name, line=ln))


def parse_sta_summary(run_dir: Path, res: AnalysisResult) -> None:
    """31-rcx_sta.summary.rpt：WNS / TNS / 最差 slack。"""
    path = run_dir / "reports" / "signoff" / "31-rcx_sta.summary.rpt"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    pats = {
        "tns": r"^tns\s+(-?[\d.]+)",
        "wns": r"^wns\s+(-?[\d.]+)",
        "worst_slack_max": r"worst slack\s+(-?[\d.]+)",
    }
    for key, pat in pats.items():
        m = re.search(pat, text, re.MULTILINE)
        if m:
            res.metrics[key] = float(m.group(1))

    wns = res.metrics.get("wns")
    if wns is not None and wns < 0:
        res.add(Issue("ERROR", "STA", f"WNS = {wns} ns（存在 setup 违例）",
                      source="31-rcx_sta.summary.rpt",
                      hint="打开 31-rcx_sta.max.rpt 找最差路径，按 cell delay / net delay 拆解"))
    elif wns is not None:
        res.add(Issue("INFO", "STA", f"WNS = {wns} ns（无 setup 违例）",
                      source="31-rcx_sta.summary.rpt"))
    hold = re.search(r"report_worst_slack -min \(Hold\)\s+worst slack\s+(-?[\d.]+)", text)
    if hold:
        res.metrics["worst_hold_slack"] = float(hold.group(1))
        if float(hold.group(1)) < 0:
            res.add(Issue("ERROR", "STA", f"Hold 违例: {hold.group(1)} ns",
                          source="31-rcx_sta.summary.rpt",
                          hint="检查 CTS 后的 hold fix 或插延迟单元"))


def _parse_checks_sub(report: Path, res: AnalysisResult) -> tuple[bool, bool, bool]:
    """解析 checks.rpt，返回 (有VIOLATED, 有max slew, 有max fanout)。"""
    text = read_text(report)
    if text is None:
        return (False, False, False)
    res.files_seen.append(str(report))
    lines = text.splitlines()

    sections: list[tuple[str, int, int]] = []
    current_title = None
    current_start = 1
    for idx, line in enumerate(lines, start=1):
        if line.startswith("report_"):
            if current_title is not None:
                sections.append((current_title, current_start, idx - 1))
            current_title = line.strip()
            current_start = idx
    if current_title is not None:
        sections.append((current_title, current_start, len(lines)))

    def object_entries(segment: list[str]) -> list[str]:
        out = []
        for ln in segment:
            s = ln.strip()
            if not s or set(s) <= {"="}:
                continue
            if s.startswith("report_") or "Corner" in s:
                continue
            if s.startswith(("Fanout", "Cap", "Slew", "Delay", "Time", "Description")):
                continue
            if "--" in s and len(set(s)) <= 2:
                continue
            if s.rstrip(".").lstrip("-+").replace(".", "").isdigit():
                continue
            out.append(s)
        return out

    has_violated = has_slew = has_fanout = False
    reported_violations: set[tuple[str, str, str]] = set()
    # 同一违例可能被 report_checks 和 --slack_max 各输出一遍，用签名去重
    for title, start, end in sections:
        body = lines[start - 1: end]
        head = title.lower()
        for i, line in enumerate(body):
            m = re.search(r"(-?\d+(?:\.\d+)?)\s+slack \((VIOLATED|MET)\)", line)
            if not m:
                continue
            if m.group(2) == "VIOLATED":
                sig = (report.name, m.group(1), line.strip())
                if sig in reported_violations:
                    continue
                reported_violations.add(sig)
                has_violated = True
                res.add(Issue("ERROR", "STA",
                              f"路径 VIOLATED：slack = {m.group(1)} ns",
                              detail=line.strip(), source=report.name, line=start + i,
                              hint="看同段内的 Startpoint/Endpoint，拆 cell delay 与 net delay"))
            else:
                res.metrics.setdefault("met_paths", []).append(
                    {"slack": float(m.group(1)), "file": report.name, "line": start + i})

        if "max_slew" in head or "max slew" in head or "max_fanout" in head or "max fanout" in head:
            # report_checks -max_slew_violations 会把 slew 和 fanout 输出在同一段
            entries = object_entries(body[1:])
            if entries:
                has_slew = True
                has_fanout = True
                res.add(Issue("WARNING", "STA",
                              f"max slew / max fanout 违例：{len(entries)} 条",
                              detail="\n".join(entries[:20]), source=report.name,
                              line=start,
                              hint="检查每条的 Fanout 与 Slew：驱动不足则 upsizing，扇出过多则插 buffer"))
        elif "unconstrained" in head:
            unconstrained = object_entries(body[1:])
            if unconstrained:
                res.metrics["unconstrained_count"] = len(unconstrained)
                res.add(Issue("INFO", "STA",
                              f"未约束端点：{len(unconstrained)} 个",
                              detail="\n".join(unconstrained[:10]), source=report.name,
                              hint="未约束的 IO 不会被检查，需补 set_input_delay / set_output_delay"))
        elif "parasitic_annotation" in head:
            unannotated = object_entries(body[1:])
            if unannotated:
                res.metrics["unannotated_nets"] = len(unannotated)
                res.add(Issue("INFO", "STA",
                              f"未标注寄生的 net：{len(unannotated)} 个",
                              detail="\n".join(unannotated[:10]), source=report.name,
                              hint="SPEF 未覆盖的 net 退化为理想线，时序偏乐观"))
    return (has_violated, has_slew, has_fanout)


def parse_checks_report(run_dir: Path, res: AnalysisResult) -> None:
    """31-rcx_sta.checks.rpt：必须按 report_ 标题切段，才能抓到没有 VIOLATED 字样的 slew/fanout。"""
    path = run_dir / "reports" / "signoff" / "31-rcx_sta.checks.rpt"
    _parse_checks_sub(path, res)
    # 同一份内容常被复制到 max.rpt，也扫一遍（去重已在函数内做）
    _parse_checks_sub(run_dir / "reports" / "signoff" / "31-rcx_sta.max.rpt", res)


def parse_drc(run_dir: Path, res: AnalysisResult) -> None:
    path = run_dir / "reports" / "signoff" / "drc.rpt"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    m = re.search(r"COUNT:\s*(\d+)", text)
    if m:
        count = int(m.group(1))
        res.metrics["drc_count"] = count
        if count > 0:
            res.add(Issue("ERROR", "DRC", f"DRC 标记数 {count}",
                          source="drc.rpt",
                          hint="drc.rpt 的 COUNT 是标记数，需除以 3 或 4 得到违例数"))
        else:
            res.add(Issue("INFO", "DRC", "DRC 无违例", source="drc.rpt"))


def parse_lvs(run_dir: Path, res: AnalysisResult) -> None:
    for path in sorted((run_dir / "reports" / "signoff").glob("*lvs*.rpt")):
        text = read_text(path)
        if text is None:
            continue
        res.files_seen.append(str(path))
        m = re.search(r"Total errors\s*=\s*(\d+)", text)
        if m:
            n = int(m.group(1))
            res.metrics["lvs_errors"] = n
            if n > 0:
                res.add(Issue("ERROR", "LVS", f"LVS 错误 {n} 个",
                              detail=text[:400], source=path.name,
                              hint="常见原因：power pin 悬空、LEF/GDS pin 名不一致、macro 未正确集成"))
            else:
                res.add(Issue("INFO", "LVS", "LVS 无错误", source=path.name))
        elif "no net, device, pin, or property mismatches" in text:
            res.metrics["lvs_errors"] = 0
            res.add(Issue("INFO", "LVS", "LVS 无错误", source=path.name))


def parse_irdrop(run_dir: Path, res: AnalysisResult, nominal: float = 1.8) -> None:
    sig = run_dir / "reports" / "signoff"

    def collect(fn: str) -> list[float]:
        p = sig / fn
        vals: list[float] = []
        if not p.exists():
            return vals
        first = True
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if first:
                    first = False
                    continue
                parts = line.rsplit(",", 1)
                if len(parts) != 2:
                    continue
                try:
                    vals.append(float(parts[1]))
                except ValueError:
                    pass
        return vals

    vpwr = collect("32-irdrop-VPWR.rpt")
    vgnd = collect("32-irdrop-VGND.rpt")
    if not vpwr and not vgnd:
        return

    def summarize(name: str, vals: list[float], ground: bool) -> None:
        if not vals:
            return
        lo, hi = min(vals), max(vals)
        drop = hi if ground else (nominal - lo)
        pct = drop / nominal * 100
        res.metrics[name] = {
            "instances": len(vals), "min": lo, "max": hi,
            "avg": sum(vals) / len(vals), "worst_drop_mv": drop * 1000,
            "worst_drop_pct": pct,
        }
        if pct >= 5.0:
            res.add(Issue("ERROR", "IRDROP",
                          f"{name} 压降 {drop*1000:.1f} mV = {pct:.2f}%（超过 5%）",
                          source=f"32-irdrop-{name}.rpt",
                          hint="加密 PDN 网格（减小 VPITCH/HPITCH）、加宽电源线，或分散高电流单元"))
        else:
            res.add(Issue("INFO", "IRDROP",
                          f"{name} 压差 {drop*1000:.1f} mV = {pct:.2f}%（合格）",
                          source=f"32-irdrop-{name}.rpt"))

    summarize("VPWR", vpwr, ground=False)
    summarize("VGND", vgnd, ground=True)


def parse_power(run_dir: Path, res: AnalysisResult) -> None:
    path = run_dir / "reports" / "signoff" / "31-rcx_sta.power.rpt"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    m = re.search(r"^Total\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)",
                  text, re.MULTILINE)
    if m:
        res.metrics["power_total_w"] = float(m.group(4))
        res.metrics["power_internal_w"] = float(m.group(1))
        res.metrics["power_switching_w"] = float(m.group(2))
        res.metrics["power_leakage_w"] = float(m.group(3))


def parse_antenna(run_dir: Path, res: AnalysisResult) -> None:
    path = run_dir / "reports" / "signoff" / "41-antenna_violators.rpt"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    entries = [ln.strip() for ln in text.splitlines() if "Partial/Required" in ln]
    if entries:
        res.metrics["antenna_violators"] = len(entries)
        res.add(Issue("WARNING", "ANTENNA", f"天线违例 {len(entries)} 条",
                      detail="\n".join(entries[:10]), source="41-antenna_violators.rpt",
                      hint="开启 DIODE_INSERTION_STRATEGY 自动插二极管，或改层/断线后重连"))
    else:
        res.add(Issue("INFO", "ANTENNA", "无天线违例", source="41-antenna_violators.rpt"))


def parse_skew(run_dir: Path, res: AnalysisResult) -> None:
    path = run_dir / "reports" / "signoff" / "31-rcx_sta.skew.rpt"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    m = re.search(r"^\s*([\d.]+)\s+(-?[\d.]+)\s+([\d.]+)\s*$", text, re.MULTILINE)
    if m:
        res.metrics["clock_skew_ns"] = float(m.group(3))


def parse_config(run_dir: Path, res: AnalysisResult) -> None:
    """config.tcl：检查几个关键参数，从配置层面暴露根因。"""
    path = run_dir / "config.tcl"
    text = read_text(path)
    if text is None:
        return
    res.files_seen.append(str(path))
    keys = ["CLOCK_PERIOD", "FP_CORE_UTIL", "PL_TARGET_DENSITY", "DIODE_INSERTION_STRATEGY",
            "VSRC_LOC_FILES", "FP_PDN_VPITCH", "FP_PDN_HPITCH"]
    found: dict[str, str] = {}
    # OpenLane 的 config.tcl 是 `set ::env(KEY) "VALUE"`，也兼容 `set KEY VALUE`
    for k in keys:
        m = re.search(rf"^\s*set\s+(?:::env\()?{k}\)?\s+(\S.*)$", text, re.MULTILINE)
        if m:
            found[k] = m.group(1).strip().strip('"')
    res.metrics["config"] = found

    if "VSRC_LOC_FILES" not in found:
        res.add(Issue("WARNING", "IRDROP", "config 未设置 VSRC_LOC_FILES",
                      source="config.tcl",
                      hint="IR drop 报告会生成，但电源点位置取默认值，压降数值只能当参考；"
                           "真实工程需给出电源 PAD 位置"))
    if "DIODE_INSERTION_STRATEGY" not in found:
        res.add(Issue("INFO", "ANTENNA", "config 未设置 DIODE_INSERTION_STRATEGY",
                      source="config.tcl", hint="若天线违例超标可显式开启二极管插入"))

    if "FP_CORE_UTIL" in found:
        try:
            util = float(found["FP_CORE_UTIL"])
            if util > 55:
                res.add(Issue("WARNING", "FP", f"FP_CORE_UTIL = {util} 偏高",
                              source="config.tcl",
                              hint="利用率过高会引发全局布局拥塞（GPL-0302），常见做法是 40–50"))
        except ValueError:
            pass

    if "CLOCK_PERIOD" in found:
        try:
            period = float(found["CLOCK_PERIOD"])
            res.metrics["clock_period_ns"] = period
            if period >= 8:
                res.add(Issue("INFO", "FP",
                              f"CLOCK_PERIOD = {period} ns，约束宽松，时序压力不足以暴露问题",
                              source="config.tcl",
                              hint="想制造时序问题做实验，可逐档降低到 6 / 5 / 4 ns"))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 4. 汇总与输出
# ---------------------------------------------------------------------------

def analyze(run_dir: Path) -> AnalysisResult:
    res = AnalysisResult()
    if not run_dir.exists():
        raise SystemExit(f"目录不存在: {run_dir}")
    print(f"分析 run 目录: {run_dir}")

    steps = [
        ("openlane/warnings log", lambda: parse_openlane_log(run_dir, res)),
        ("sub logs (Fatal/Error/ERC)", lambda: parse_sub_logs(run_dir, res)),
        ("root logs (Fatal)", lambda: parse_log_errors(run_dir, res)),
        ("STA summary", lambda: parse_sta_summary(run_dir, res)),
        ("checks report", lambda: parse_checks_report(run_dir, res)),
        ("DRC", lambda: parse_drc(run_dir, res)),
        ("LVS", lambda: parse_lvs(run_dir, res)),
        ("IR drop", lambda: parse_irdrop(run_dir, res)),
        ("power", lambda: parse_power(run_dir, res)),
        ("antenna", lambda: parse_antenna(run_dir, res)),
        ("skew", lambda: parse_skew(run_dir, res)),
        ("config", lambda: parse_config(run_dir, res)),
    ]
    for label, fn in steps:
        try:
            fn()
            print(f"  ✓ {label}")
        except Exception:  # 单步失败不影响整体
            print(f"  ✗ {label} 失败:", file=sys.stderr)
            traceback.print_exc(limit=2)

    classify_warnings(res)
    summarize_blackbox(res)
    return res


def summarize_blackbox(res: AnalysisResult) -> None:
    """
    把逐条 blackbox 告警合并成一条摘要。
    fill / tap / decap 被黑盒是正常现象（它们没有时序），逐条列只会淹没真问题。
    """
    groups: dict[str, list[Issue]] = {}
    for issue in res.issues:
        if issue.category == "BLACKBOX":
            m = re.search(r"Module\s+(\S+)\s+blackboxed", issue.detail)
            key = m.group(1) if m else "unknown"
            groups.setdefault(key, []).append(issue)
    if not groups:
        return
    res.issues = [i for i in res.issues if i.category != "BLACKBOX"]
    benign = [c for c in groups if re.search(r"(fill|tap|decap)", c)]
    serious = [c for c in groups if c not in benign]
    detail = "；".join(f"{c} ×{len(g)}" for c, g in sorted(groups.items()))
    if serious:
        res.add(Issue("WARNING", "BLACKBOX",
                      f"STA 中黑盒化的单元：{len(groups)} 种（含非 filler 单元）",
                      detail=detail,
                      hint="fill/tap/decap 无时序模型属正常；若含 SRAM/macro/IO，则相关路径时序不完整，需补 lib"))
    else:
        res.add(Issue("INFO", "BLACKBOX",
                      f"STA 中黑盒化的单元 {len(groups)} 种（均为 filler/tap/decap，属正常）",
                      detail=detail,
                      hint="无需处理"))


def render_markdown(run_dir: Path, res: AnalysisResult, only: str = "ALL") -> str:
    """only: ALL / CRITICAL / ERROR 及以上"""
    threshold = {"ALL": 3, "WARNING": 2, "ERROR": 1, "CRITICAL": 0}.get(only, 3)
    out: list[str] = []
    out.append(f"# OpenLane Run 分析报告\n")
    out.append(f"- run 目录：`{run_dir}`")
    out.append(f"- 扫描文件：{len(res.files_seen)} 个")
    out.append("")
    out.append("## 概览\n")
    out.append("| 严重度 | 数量 |")
    out.append("|---|---|")
    for sev in ("CRITICAL", "ERROR", "WARNING", "INFO"):
        out.append(f"| {SEVERITY_ICON[sev]} {sev} | {res.count(sev)} |")
    out.append("")
    out.append("## 关键指标\n")
    out.append("| 指标 | 值 |")
    out.append("|---|---|")
    m = res.metrics
    for key, label in [
        ("flow_complete", "流程完成"),
        ("wns", "WNS (ns)"), ("tns", "TNS (ns)"), ("worst_hold_slack", "最差 hold slack (ns)"),
        ("drc_count", "DRC 标记数"), ("lvs_errors", "LVS 错误"),
        ("antenna_violators", "天线违例条数"),
        ("power_total_w", "总功耗 (W)"), ("clock_skew_ns", "时钟 skew (ns)"),
        ("unconstrained_count", "未约束端点"), ("unannotated_nets", "未标注寄生 net"),
    ]:
        if key in m:
            out.append(f"| {label} | {m[key]} |")
    for k in ("VPWR", "VGND"):
        if k in m:
            d = m[k]
            out.append(f"| {k} 压差 | {d['worst_drop_mv']:.1f} mV ({d['worst_drop_pct']:.2f}%) |")
    if "config" in m and m["config"]:
        out.append("")
        out.append("### config 关键参数\n")
        out.append("| 参数 | 值 |")
        out.append("|---|---|")
        for k, v in m["config"].items():
            out.append(f"| {k} | `{v}` |")
    out.append("")
    out.append("## 问题清单（按严重度排序）\n")
    shown = 0
    for issue in res.sorted_issues():
        if SEVERITY_ORDER.get(issue.severity, 9) > threshold:
            continue
        shown += 1
        icon = SEVERITY_ICON.get(issue.severity, "•")
        loc = issue.source + (f":{issue.line}" if issue.line else "")
        out.append(f"### {icon} [{issue.severity}] {issue.category} — {issue.title}\n")
        out.append(f"- 位置：`{loc}`")
        if issue.detail:
            detail = "\n".join(issue.detail.splitlines()[:10])
            out.append(f"- 详情：\n```\n{detail}\n```")
        if issue.hint:
            out.append(f"- 建议：{issue.hint}")
        out.append("")
    if shown == 0:
        out.append("（当前过滤级别下没有问题）\n")
    return "\n".join(out)


# ---- 省 token 的关键函数 ----
SEVERITY_RANK = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}


def build_ai_context(res: AnalysisResult, min_severity: str = "CRITICAL",
                     max_chars: int = 6000, max_detail_lines: int = 1) -> str:
    """
    给 LLM 的精简上下文。

    省 token 策略：
      1. 默认只发 CRITICAL（1–3 条），不发 INFO/WARNING
      2. detail 只保留前 max_detail_lines 行，每行截断到 200 字符
      3. 不重复 hint（模型自己会推，只在需要时给）
      4. 总长度硬上限 max_chars
    """
    limit = SEVERITY_RANK.get(min_severity, 0)
    parts = ["## 关键指标"]
    for k, v in res.metrics.items():
        if k == "config":
            continue
        if isinstance(v, dict):
            continue
        parts.append(f"- {k}: {v}")
    parts.append("")
    parts.append("## 问题")
    n = 0
    for issue in res.sorted_issues():
        if SEVERITY_RANK.get(issue.severity, 9) > limit:
            continue
        n += 1
        parts.append(f"- [{issue.severity}] {issue.category}: {issue.title}")
        if issue.detail:
            det = issue.detail.splitlines()
            for line in det[:max_detail_lines]:
                parts.append("  " + line[:200])
        if issue.hint:
            parts.append(f"  方向: {issue.hint[:160]}")
    if n == 0:
        parts.append("（无达到该严重度的问题）")
    text = "\n".join(parts)
    return text[:max_chars]


def run_ai(ctx: str) -> Optional[str]:
    try:
        from openai import OpenAI
    except ImportError:
        print("未安装 openai 包，跳过 AI 分析（pip install openai）", file=sys.stderr)
        return None
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("未设置 DEEPSEEK_API_KEY，跳过 AI 分析", file=sys.stderr)
        return None
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt = (
        "你是资深数字IC后端工程师。下面是一次 OpenLane(sky130) run 的自动提取问题。"
        "请：1) 逐条给出真实根因；2) 判断哪些是真实设计缺陷；"
        "3) 给出可执行的修复参数或 Tcl。回答简洁，不要复述输入。\n\n" + ctx
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是精通 OpenLane 与 sky130 的后端专家，回答严谨、不臆造。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# 5. 自测
# ---------------------------------------------------------------------------

SELF_TEST_LOG = """\
[INFO]: Running LVS (log: designs/x/runs/t/logs/signoff/39-lvs.lef.log)...
[WARNING]: VSRC_LOC_FILES is not defined. The IR drop analysis will run, but the values may be inaccurate.
Fatal error:could not find subcircuit: XFILLER_0_118_62(sky130_ef_sc_hd__decap_12) in picorv32
[WARNING]: There are max slew violations in the design at the typical corner.
[SUCCESS]: Flow complete.
"""

SELF_TEST_CHECKS = """\
===========================================================================
report_checks --slack_max -0.01
===========================================================================
                   -0.35   slack (VIOLATED)
===========================================================================
report_object_max_slew
===========================================================================
_00012_/X (0.42)
===========================================================================
report_object_max_fanout
===========================================================================
_00033_/Y (12)
"""


def self_test() -> int:
    """
    用内置模板验证解析器是否仍能抓到关键问题。
    自测目录默认 ./_selftest（需先存在），可用 OL_SELFTEST_DIR 覆盖。
    """
    tmp = Path(os.environ.get("OL_SELFTEST_DIR", str(Path(__file__).parent / "_selftest")))
    for sub in (tmp / "logs" / "signoff", tmp / "reports" / "signoff"):
        ensure_dir(sub)
    if not tmp.exists():
        print(f"❌ 自测目录不可用: {tmp}（请先创建，或设置 OL_SELFTEST_DIR）", file=sys.stderr)
        return 1
    (tmp / "openlane.log").write_text(SELF_TEST_LOG, encoding="utf-8")
    (tmp / "warnings.log").write_text(SELF_TEST_LOG, encoding="utf-8")
    (tmp / "logs" / "signoff" / "42-erc_screen.log").write_text(SELF_TEST_LOG, encoding="utf-8")
    (tmp / "reports" / "signoff" / "31-rcx_sta.checks.rpt").write_text(SELF_TEST_CHECKS, encoding="utf-8")
    (tmp / "reports" / "signoff" / "31-rcx_sta.max.rpt").write_text(SELF_TEST_CHECKS, encoding="utf-8")
    (tmp / "reports" / "signoff" / "31-rcx_sta.summary.rpt").write_text(
        "wns -0.35\ntns -1.20\nreport_worst_slack -min (Hold)\n   worst slack 0.12\n", encoding="utf-8")

    res = analyze(tmp)
    titles = [i.title for i in res.issues]
    checks = {
        "抓到 ERC 子电路缺失": any(i.category == "ERC" and "找不到子电路" in i.title for i in res.issues),
        "抓到 Fatal error": any(i.category == "FLOW" and "Fatal" in i.title for i in res.issues),
        "抓到 max slew / fanout": any("max slew" in t and "max fanout" in t for t in titles),
        "抓到 VIOLATED 路径": any("VIOLATED" in i.title for i in res.issues),
        "读到 WNS=-0.35": res.metrics.get("wns") == -0.35,
        "读到 hold slack": res.metrics.get("worst_hold_slack") == 0.12,
        "识别未定义 VSRC_LOC_FILES": any("VSRC_LOC_FILES" in i.title for i in res.issues),
    }
    print("\n逐项断言:")
    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    all_ok = all(checks.values())
    print("自测:", "通过 ✅" if all_ok else "失败 ❌")
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# 6. main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="OpenLane run 日志/报告综合分析器（省 token 版）")
    ap.add_argument("run_dir", nargs="?", help="OpenLane run 目录")
    ap.add_argument("--ai", action="store_true", help="调用 DeepSeek 做深度分析（默认只发 CRITICAL）")
    ap.add_argument("--ai-severity", default="CRITICAL",
                    choices=["CRITICAL", "ERROR", "WARNING", "INFO"],
                    help="发送给 AI 的最低严重度（默认 CRITICAL，最省 token）")
    ap.add_argument("--only-critical", action="store_true", help="report.md 只写 CRITICAL")
    ap.add_argument("--only", default="ALL", choices=["ALL", "WARNING", "ERROR", "CRITICAL"],
                    help="report.md 的过滤级别（默认 ALL）")
    ap.add_argument("--self-test", action="store_true", help="用内置模板自测")
    ap.add_argument("--out", default="analysis", help="输出子目录名（相对 run_dir）")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.run_dir:
        ap.print_help()
        return 2

    run_dir = Path(args.run_dir).expanduser().resolve()
    res = analyze(run_dir)

    out_dir = run_dir / args.out
    ensure_dir(out_dir)

    only = "CRITICAL" if args.only_critical else args.only
    md = render_markdown(run_dir, res, only=only)
    (out_dir / "report.md").write_text(md, encoding="utf-8")

    issues = [i.to_dict() for i in res.sorted_issues()]
    (out_dir / "issues.json").write_text(
        json.dumps({"run_dir": str(run_dir), "metrics": res.metrics, "issues": issues},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    ctx = build_ai_context(res, min_severity=args.ai_severity)
    (out_dir / "ai_context.txt").write_text(ctx, encoding="utf-8")

    print(f"\n输出:")
    print(f"  {out_dir / 'report.md'}")
    print(f"  {out_dir / 'issues.json'}")
    print(f"  {out_dir / 'ai_context.txt'}  ({len(ctx)} 字符)")
    print(f"\n统计: CRITICAL={res.count('CRITICAL')} ERROR={res.count('ERROR')} "
          f"WARNING={res.count('WARNING')} INFO={res.count('INFO')}")

    if args.ai:
        print(f"\n调用 DeepSeek（发送 {args.ai_severity} 及以上）...")
        answer = run_ai(ctx)
        if answer:
            (out_dir / "ai_analysis.md").write_text(answer, encoding="utf-8")
            print(f"已写入 {out_dir / 'ai_analysis.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))