import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import platform
import psutil
import shutil
import os
import subprocess
import socket
import webbrowser

SUGGESTIONS = {
    "OS": "https://www.microsoft.com/en-us/windows/get-windows-11",
    "RAM": "https://www.kingston.com.cn/en/blog/gaming/how-upgrade-ram-in-pc",
    "System Disk Free": "https://support.microsoft.com/en-us/windows/free-up-drive-space-in-windows-85529ccb-c365-490d-b548-831022bc9b32",
    "WSL2": "https://learn.microsoft.com/en-us/windows/wsl/install",
    "Virtualization": "https://support.microsoft.com/en-us/windows/enable-virtualization-on-windows-c5578302-6e43-4b4b-a449-8ced115f58e1",
    "Docker": "https://docs.docker.com/desktop/setup/install/windows-install/"
}

def check_internet():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        pass
    return False

def check_command(cmd):
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=4)
        return True
    except Exception:
        return False

def get_system_info():
    sys_os = platform.system() + " " + platform.release()
    ram_gb = round(psutil.virtual_memory().total / (1024**3))
    sys_drive = os.getenv('SystemDrive', 'C:') + '\\'
    disk_gb = round(shutil.disk_usage(sys_drive).free / (1024**3))
    arch = platform.machine()
    internet = check_internet()
    
    wsl = check_command(["wsl", "--status"])
    docker_win = check_command(["docker", "--version"])
    docker_wsl = check_command(["wsl", "docker", "--version"]) if wsl else False
    
    docker_bool = docker_win or docker_wsl
    if docker_win and docker_wsl: docker_str = "Installed (Win & WSL)"
    elif docker_win: docker_str = "Installed (Win)"
    elif docker_wsl: docker_str = "Installed (WSL)"
    else: docker_str = "Not Installed"
    
    virt = False
    try:
        res = subprocess.run(["powershell", "(Get-WmiObject -Namespace root\\cimv2 -Class Win32_ComputerSystem).HypervisorPresent"], 
                             capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        virt = "True" in res.stdout
    except Exception:
        pass

    return {
        "OS": (sys_os, sys_os.startswith("Windows 10") or sys_os.startswith("Windows 11")),
        "RAM": (f"{ram_gb} GB", ram_gb),
        "System Disk Free": (f"{disk_gb} GB", disk_gb),
        "Architecture": (arch, "64" in arch or "86" in arch),
        "Internet": ("Connected" if internet else "Disconnected", internet),
        "WSL2": ("Installed" if wsl else "Not Installed", wsl),
        "Virtualization": ("Enabled" if virt else "Disabled", virt),
        "Docker": (docker_str, docker_bool)
    }

def evaluate(val, min_val, rec_val, is_bool=False):
    if is_bool:
        if val == rec_val: return "✔️ Optimal", "pass"
        if val == min_val: return "⚠️ Minimum", "warn"
        return "❌ Fail", "fail"
    else:
        if val >= rec_val: return "✔️ Optimal", "pass"
        if val >= min_val: return "⚠️ Minimum", "warn"
        return "❌ Fail", "fail"

def execute_checks(tree, btn, root, summary_label):
    for item in tree.get_children():
        tree.delete(item)
        
    info = get_system_info()
    
    # Custom rule for Docker + WSL2
    docker_installed = info["Docker"][1]
    wsl_installed = info["WSL2"][1]
    untested_docker = False
    
    if docker_installed:
        if not wsl_installed:
            docker_status = ("✔️ Optimal (Untested)", "pass")
            untested_docker = True
        else:
            docker_status = ("✔️ Optimal", "pass")
    else:
        docker_status = ("❌ Fail", "fail")
    
    checks = [
        ("OS", "Win 10/Mac/Linux", "Windows 10/11", info["OS"][0], 
         ("✔️ Optimal", "pass") if info["OS"][1] else ("❌ Fail", "fail")),
        ("RAM", "16 GB", "32 GB", info["RAM"][0], evaluate(info["RAM"][1], 16, 32)),
        ("System Disk Free", "20 GB", "50 GB", info["System Disk Free"][0], evaluate(info["System Disk Free"][1], 20, 50)),
        ("Architecture", "X86/64", "X86/64", info["Architecture"][0], 
         ("✔️ Optimal", "pass") if info["Architecture"][1] else ("❌ Fail", "fail")),
        ("Internet", "Required", "Required", info["Internet"][0], evaluate(info["Internet"][1], True, True, True)),
        ("WSL2", "Optional", "Required", info["WSL2"][0], evaluate(info["WSL2"][1], False, True, True)),
        ("Virtualization", "Optional", "Required", info["Virtualization"][0], evaluate(info["Virtualization"][1], False, True, True)),
        ("Docker", "Optional", "Required", info["Docker"][0], docker_status)
    ]
    
    fails, warns = 0, 0
    
    for row in checks:
        comp, _, _, _, (status_txt, tag) = row
        if tag == "fail": fails += 1
        if tag == "warn": warns += 1
        
        suggestion = "Guide 🔗" if tag != "pass" and comp in SUGGESTIONS else ""
        tree.insert("", "end", values=(row[0], row[1], row[2], row[3], status_txt, suggestion), tags=(tag,))
        
    if fails > 0:
        msg = f"❌ System check failed. {fails} component(s) do not meet minimum requirements."
        color = "#d32f2f"
    elif warns > 0:
        msg = f"⚠️ System meets minimum requirements, but {warns} component(s) could be optimized."
        color = "#f57c00"
    else:
        msg = "✅ Excellent! Your system meets all recommended configurations."
        color = "#388e3c"
        
    # Extra warning logic for the untested Docker mode
    if untested_docker:
        msg += "\n⚠️ Warning: Docker is installed without WSL2. This mode is not strictly tested."
        if color == "#388e3c": color = "#f57c00" # Shift color to warning if it was fully green
        
    summary_label.config(text=msg, fg=color)
    btn.config(text="Run Check", state=tk.NORMAL)
    root.config(cursor="")

def on_run_click(tree, btn, root, summary_label):
    btn.config(text="Checking... Please Wait", state=tk.DISABLED)
    root.config(cursor="watch")
    summary_label.config(text="Evaluating system configuration...", fg="#1976d2")
    root.update() 
    root.after(100, lambda: execute_checks(tree, btn, root, summary_label))

def on_tree_click(event, tree):
    region = tree.identify("region", event.x, event.y)
    if region == "cell":
        col = tree.identify_column(event.x)
        if col == "#6":
            item = tree.identify_row(event.y)
            if item:
                vals = tree.item(item, "values")
                if vals[5] != "":
                    comp = vals[0]
                    if comp in SUGGESTIONS:
                        disclaimer_title = "Important Disclaimer"
                        disclaimer_msg = (
                            "You are about to visit a third-party website.\n\n"
                            "Please note that we have no affiliation with this website, "
                            "and the provided link is for reference purposes only.\n\n"
                            "We are not responsible for the authenticity, accuracy, "
                            "or any other issues regarding the third-party website's content.\n\n"
                            "Do you wish to proceed?"
                        )
                        if messagebox.askyesno(disclaimer_title, disclaimer_msg):
                            webbrowser.open(SUGGESTIONS[comp])

def main():
    root = tk.Tk()
    # 先隐藏主窗口，以免在显示免责声明时背景有一个空白窗口
    root.withdraw()
    
    # 新增：软件启动时的全局免责声明
    startup_title = "Software Disclaimer & Terms of Use"
    startup_msg = (
        "This software is provided 'as-is', without warranty of any kind, express or implied. "
        "It is provided completely free of charge.\n\n"
        "In no event shall the authors, developers, or copyright holders be liable for any claim, "
        "damages, data loss, or other liability, whether in an action of contract, tort or otherwise, "
        "arising from, out of, or in connection with the software or the use or other dealings in the software.\n\n"
        "By clicking 'Yes', you acknowledge that you have read and agree to these terms. "
        "Do you wish to proceed?"
    )
    
    # 如果用户点击了“No”，则销毁程序并退出
    if not messagebox.askyesno(startup_title, startup_msg):
        root.destroy()
        return
        
    # 用户同意后，显示主窗口并继续原有流程
    root.deiconify()
    
    root.title("BioAG System Configuration Checker")
    root.geometry("1000x400") # Slightly wider/taller to accommodate the extra warning text and column widths
    
    columns = ("Component", "Minimum", "Recommended", "Current", "Status", "Suggestion")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    widths = [150, 120, 120, 200, 150, 100]
    for col, w in zip(columns, widths):
        tree.heading(col, text=col)
        tree.column(col, anchor="center", width=w)
        
    tree.tag_configure('pass', background='#e6f4ea')
    tree.tag_configure('warn', background='#fff3cd')
    tree.tag_configure('fail', background='#fce8e6')
    
    tree.bind("<ButtonRelease-1>", lambda e: on_tree_click(e, tree))
    tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    summary_label = tk.Label(root, text="Ready to check system configuration.", font=("Arial", 11, "bold"))
    summary_label.pack(pady=5)
    
    btn = ttk.Button(root, text="Run Check")
    btn.config(command=lambda: on_run_click(tree, btn, root, summary_label))
    btn.pack(pady=10)
    
    on_run_click(tree, btn, root, summary_label)
    root.mainloop()

if __name__ == "__main__":
    main()