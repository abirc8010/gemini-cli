import json
from collections import Counter

def generate_report():
    try:
        with open("evals/long-context-benchmark/results.json", "r") as f:
            results = json.load(f)
    except FileNotFoundError:
        print("[!] No results.json found. Run runner.py first.")
        return

    total = len(results)
    statuses = Counter([r["status"] for r in results])
    
    print("\n# 📊 Gemini CLI - Long-Context Baseline Report")
    print(f"**Total Tasks Evaluated:** {total}\n")
    
    print("### Failure Mode Diagnostics")
    print("| Category | Count | Percentage |")
    print("| :--- | :--- | :--- |")
    
    for status, count in sorted(statuses.items()):
        icon = "✅" if "PASS" in status else "❌"
        if "TIMEOUT" in status: icon = "⏳"
        
        pct = round((count / total) * 100, 1)
        clean_name = status.replace("FAIL_", "").replace("_", " ").title()
        print(f"| {icon} {clean_name} | {count} | {pct}% |")

    avg_explored = sum(r["trajectory"]["files_explored"] for r in results) / total if total > 0 else 0
    print(f"\n**Innovation Metric (Trajectory):** Agent explored an average of **{round(avg_explored, 1)}** context files per task before acting.")

if __name__ == "__main__":
    generate_report()