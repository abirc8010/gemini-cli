import os
import json
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))

class InteractiveEvaluator:
    def __init__(self, tasks_dir=None, repos_dir=None):
        self.tasks_dir = tasks_dir or os.path.join(SCRIPT_DIR, "tasks")
        # Pointing directly to your Phase 1 downloaded repos
        self.repos_dir = "/media/abir/Abir/work/gemini/phase-1/data/repos"
        self.results = []
        self.cli_source_dir = REPO_ROOT 

    def load_task(self, task_id):
        task_path = os.path.join(self.tasks_dir, task_id)
        with open(os.path.join(task_path, "manifest.json"), "r") as f:
            manifest = json.load(f)
        with open(os.path.join(task_path, "problem.md"), "r") as f:
            problem = f.read()
        return manifest, problem

    def setup_environment(self, manifest):
        safe_repo_name = manifest["repo"].replace("/", "_")
        repo_path = os.path.abspath(os.path.join(self.repos_dir, safe_repo_name))
        host_home = os.path.expanduser("~")
        
        print(f"\n[*] Booting Sandbox for: {manifest['task_id']}")
        
        container_id = subprocess.check_output([
            "docker", "run", "-d", 
            "-u", "root",
            "-v", f"{repo_path}:/workspace/target", 
            "-v", f"{self.cli_source_dir}:/workspace/gemini-cli", 
            "-v", f"{host_home}/.gemini:/root/.gemini",
            "-w", "/workspace/target", 
            "gemini-eval-sandbox"
        ]).decode("utf-8").strip()

        # Rewind repo to broken state
        subprocess.run(["docker", "exec", container_id, "git", "reset", "--hard", manifest["base_commit"]], stdout=subprocess.DEVNULL)
        return container_id

    def execute_agent_interactive(self, container_id, problem_text):
        print("    [>] Booting CLI in Live-Streaming Mode...")
        start_time = time.time()
        
        instruction = f"Fix this issue directly in the files. Details: {problem_text[:500]} Then exit."
        cmd = ["docker", "exec", "-t", container_id, "node", "/workspace/gemini-cli/bundle/gemini.js", "-y", "-p", instruction]
        
        try:
            print("    [>] Agent is running. Live internal output:")
            print("    " + "┌" + "─"*60)
            
            # LIVE STREAMING PROTOCOL: Captures and prints CLI output line-by-line
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            
            full_logs = ""
            for line in process.stdout:
                print(f"    │ {line}", end="") 
                full_logs += line
                
            process.wait(timeout=1200) 
            print("    " + "└" + "─"*60)
            
            return {"time": time.time() - start_time, "timeout": False, "logs": full_logs}
            
        except subprocess.TimeoutExpired:
            print("    " + "└" + "─"*60)
            print("    [!] TIMEOUT THRESHOLD REACHED (20 mins). Killing process...")
            process.kill()
            subprocess.run(["docker", "exec", container_id, "pkill", "-f", "node"])
            return {"time": 1200, "timeout": True, "logs": full_logs}
        except Exception as e:
            print("    [!] CLI exited unexpectedly.")
            return {"time": time.time() - start_time, "timeout": False, "logs": str(e)}

    def analyze_failure(self, container_id, manifest, exec_result):
        if exec_result["timeout"]:
            return "FAIL_TIMEOUT", 0, 0

        logs = exec_result["logs"]
        
        # Telemetry Trajectory Tracking
        files_explored = len(set([line for line in logs.split('\n') if "Reading file" in line])) 
        
        diff_stat = subprocess.run(["docker", "exec", container_id, "git", "diff", "--name-only"], capture_output=True, text=True).stdout
        edited_files = [f for f in diff_stat.split('\n') if f]
        gold_files = manifest.get("impacted_files", [])
        
        correct_files_targeted = len(set(edited_files).intersection(set(gold_files)))

        if not edited_files:
            if files_explored < 2: 
                # If we hit a quota error, it will likely drop us here because it read 0 files.
                return "FAIL_CONTEXT_INSUFFICIENT", files_explored, 0
            return "FAIL_COMPLETE_HALLUCINATION", files_explored, 0

        if correct_files_targeted == 0:
            return "FAIL_WRONG_FILES_TARGETED", files_explored, len(edited_files)

        # Grading Protocol
        test_run = subprocess.run(["docker", "exec", container_id, "bash", "-c", manifest["test_cmd"]], capture_output=True, text=True)
        
        if test_run.returncode == 0:
            return "PASS_RESOLVED", files_explored, len(edited_files)
            
        test_out = test_run.stdout + test_run.stderr
        
        if "SyntaxError" in test_out or "ParseError" in test_out:
            return "FAIL_SYNTAX_CORRUPTION", files_explored, len(edited_files)
            
        if "Regression" in test_out or "unexpected failure" in test_out: 
            return "FAIL_TEST_REGRESSION", files_explored, len(edited_files)

        return "FAIL_SHALLOW_FIX", files_explored, len(edited_files)

    def run_all(self):
        print("=== Phase 2: Autonomous Evaluation Engine ===")
        # Grabbing the first 3 directories to verify
        task_ids = [d for d in os.listdir(self.tasks_dir) if os.path.isdir(os.path.join(self.tasks_dir, d))][:3]
        
        for task_id in task_ids:
            manifest, problem = self.load_task(task_id)
            container_id = self.setup_environment(manifest)
            
            try:
                exec_result = self.execute_agent_interactive(container_id, problem)
                status, explored, edited = self.analyze_failure(container_id, manifest, exec_result)
                
                print(f"    [!] Verdict: {status}")
                self.results.append({
                    "task_id": task_id,
                    "status": status,
                    "execution_time": round(exec_result["time"], 2),
                    "trajectory": {"files_explored": explored, "files_edited": edited}
                })
            finally:
                # Burns down the environment
                subprocess.run(["docker", "rm", "-f", container_id], stdout=subprocess.DEVNULL)

        results_file = os.path.join(SCRIPT_DIR, "results.json")
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=4)
        print(f"\n=== Engine Shutdown. Results saved to {results_file} ===")

if __name__ == "__main__":
    runner = InteractiveEvaluator()
    runner.run_all()