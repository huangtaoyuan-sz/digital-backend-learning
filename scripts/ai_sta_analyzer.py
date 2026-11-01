import os
import argparse
import glob
from openai import OpenAI

# 从系统环境变量中读取 API Key
api_key = os.getenv("DEEPSEEK_API_KEY")

if not api_key:
    print("❌ 错误：请先在终端运行 export DEEPSEEK_API_KEY='你的真实Key'")
    exit(1)

client = OpenAI(
    api_key=api_key, 
    base_url="https://api.deepseek.com" 
)

def analyze_report(file_path):
    if not os.path.exists(file_path):
        print(f"❌ 找不到文件: {file_path}")
        return

    # 1. 读取全部内容
    with open(file_path, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    # 2. 智能搜索：找到包含 VIOLATED 的行号
    violation_indices = [i for i, line in enumerate(all_lines) if "VIOLATED" in line.upper()]

    if not violation_indices:
        print("🎉 报告中没有发现 VIOLATED 违例，无需 AI 深度分析，节省 Token！")
        return
    else:
        print(f"⚠️ 检测到违例，正在提取前 5 条违例的上下文...")
        
        # 3. 提取违例的上下文（每个违例前后各 30 行）
        extracted_text = ""
        for idx in violation_indices[:5]: 
            start = max(0, idx - 30)
            end = min(len(all_lines), idx + 5)
            extracted_text += "".join(all_lines[start:end])
            extracted_text += "\n" + "="*60 + "\n"

        report_content = extracted_text

    prompt = f"""
    你现在是一个资深数字IC后端工程师。请阅读以下 STA 报告（OpenROAD生成）。
    你需要完成以下三个任务：
    1. 寻找是否有 Slack 为负数（VIOLATED）的路径。如果有，指出是哪条路径；如果没有，请直接说明“未发现违例”。
    2. 如果发现违例，请分析它是逻辑级数太深、驱动太弱、还是时钟插入延迟造成的？
    3. 针对这条违例，给我写出对应的 Tcl ECO 修复指令（比如 size_cell）。
    
    报告内容如下：
    {report_content}
    """
 
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个精通STA时序分析的专家，回答必须严谨。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        result = response.choices[0].message.content
        print("================ AI 分析结果 ================\n")
        print(result)
        
        # 保存结果到当前目录
        with open("ai_analysis_result.md", "w", encoding="utf-8") as f:
            f.write(result)
        print("\n📁 结果已自动保存到 ai_analysis_result.md")
        
    except Exception as e:
        print(f"❌ API 调用失败，请检查网络或 API Key: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 赋能数字后端：STA 报告智能分析工具")
    parser.add_argument("path", nargs="?", help="指定要分析的 STA 报告路径（可选）")
    args = parser.parse_args()

    report_path = args.path

    if not report_path:
        print("💡 未指定报告路径，正在当前目录下智能搜索 .rpt 报告...")
        rpt_files = glob.glob("./*max*.rpt") + glob.glob("./*.rpt")
        
        if rpt_files:
            report_path = rpt_files[0]
            print(f"🎯 自动锁定目标文件: {report_path}")
        else:
            print("❌ 错误：当前目录下没有找到任何 .rpt 报告文件，请通过参数指定路径。")
            exit(1)
    
    analyze_report(report_path)
