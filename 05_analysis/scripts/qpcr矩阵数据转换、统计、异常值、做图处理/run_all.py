import subprocess

def run(script):
    print(f"➡️ Running {script}...")
    result = subprocess.run(["python", script], check=True)
    print("✅ Done.\n")

scripts = [
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/05_analysis/scripts/qpcr矩阵数据转换、统计、异常值、做图处理/plate_convert_long_format.py",
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/05_analysis/scripts/qpcr矩阵数据转换、统计、异常值、做图处理/ddcp_analysis.py",
    "/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EphB1/05_analysis/scripts/qpcr矩阵数据转换、统计、异常值、做图处理/graphing.py"
]

for s in scripts:
    run(s)

print("🎉 All scripts completed.")
