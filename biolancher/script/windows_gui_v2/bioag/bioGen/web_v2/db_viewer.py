import logging
import sqlite3
import json
import argparse
import sys
import os
import threading
import time
import itertools
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
import subprocess
import tempfile
import concurrent.futures
import re

def load_db(path):
    if not os.path.exists(path): raise FileNotFoundError(f"File '{path}' not found.")
    if path.lower().endswith('.json'):
        with open(path, 'r', encoding='utf-8') as f:
            return {'type': 'json', 'data': json.load(f), 'name': os.path.splitext(os.path.basename(path))[0]}
    return {'type': 'sqlite', 'conn': sqlite3.connect(path)}

def list_users(db):
    if db['type'] == 'json': return [db['name']]
    try:
        cursor = db['conn'].cursor()
        cursor.execute("SELECT session_key FROM kv_sessions")
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError: return []

def get_user_history(db, username):
    if db['type'] == 'json': return db['data'].get('messages', [])
    cursor = db['conn'].cursor()
    cursor.execute("SELECT data_json FROM kv_sessions WHERE session_key = ?", (username,))
    row = cursor.fetchone()
    return json.loads(row[0]).get('messages', []) if row else []

class WebServerManager:
    def __init__(self):
        self.server = self.thread = self.port = None

    def start(self, html_content, start_port=8080):
        self.stop()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
        
        self.port = start_port
        while self.port < 65535:
            try:
                self.server = HTTPServer(('', self.port), Handler)
                break
            except OSError: self.port += 1
                
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.port

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = self.port = None

server_mgr = WebServerManager()

def parse_markdown(text):
    try:
        import markdown
        return markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])
    except ImportError: return f"<pre style='white-space: pre-wrap;'>{text}</pre>"

def format_markdown(messages, username):
    md = f"# Session History: {username}\n\n"
    for msg in messages:
        role, source = str(msg.get('role') or 'Unknown').capitalize(), str(msg.get('source') or '')
        src_tag = f" ({source})" if source and source.lower() != role.lower() else ""
        md += f"### {role}{src_tag}\n\n{str(msg.get('content') or '').strip()}\n\n---\n\n"
    return md

def generate_basic_html(md_text):
    css = "body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; line-height: 1.6; color: #24292e; } pre { background-color: #f6f8fa; padding: 16px; border-radius: 6px; overflow: auto; } code { font-family: monospace; background-color: rgba(27,31,35,0.05); padding: 0.2em; border-radius: 3px; }"
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{parse_markdown(md_text)}</body></html>"

def generate_enrich_html(messages, username, default_url='', default_key='', default_model=''):
    msg_json = json.dumps(messages).replace("</script>", "<\\/script>")
    
    html_msgs = ""
    for idx, msg in enumerate(messages):
        role = str(msg.get('role') or 'Unknown')
        is_user = role.lower() == 'user'
        align_class = 'user' if is_user else 'agent'
        sender = "You" if is_user else str(msg.get('source') or role).capitalize()
        content = parse_markdown(str(msg.get('content') or '').strip())
        avatar = "👤" if is_user else "🤖"
        
        btn_html = f'<div class="action-bar"><button class="btn-explain" onclick="explainStep({idx})" id="btn-explain-{idx}">✨ Explain</button></div>' if not is_user else ''
        
        html_msgs += f'''
        <div class="msg {align_class}" id="msg-{idx}">
            <div class="sender"><span>{avatar}</span>{sender}</div>
            <div class="msg-bubble">{content}{btn_html}</div>
            <div class="explanation-box" id="explanation-{idx}" style="display:none;"></div>
        </div>'''

    template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>{username} Session</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        :root {{ --bg: #f8fafc; --border: #e2e8f0; --text: #0f172a; --gray: #64748b; --user-bg: #f1f5f9; --agent-bg: #ffffff; --primary: #4f46e5; }}
        body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }}
        .nav {{ position: sticky; top: 0; background: rgba(255,255,255,0.85); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); padding: 16px 24px; font-weight: 600; font-size: 16px; z-index: 100; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }}
        .nav-btn {{ background: transparent; border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.2s; font-family: inherit; font-weight: 500; color: var(--gray); }}
        .nav-btn:hover {{ border-color: var(--primary); color: var(--primary); }}
        .chat-container {{ max-width: 800px; margin: 40px auto; display: flex; flex-direction: column; gap: 32px; padding: 0 20px; }}
        .msg {{ display: flex; flex-direction: column; max-width: 88%; line-height: 1.6; position: relative; }}
        .msg.user {{ align-self: flex-end; }}
        .msg.agent {{ align-self: flex-start; }}
        .msg-bubble {{ padding: 18px 22px; border-radius: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); font-size: 15px; position: relative; transition: all 0.2s ease; overflow-wrap: break-word; }}
        .msg.user .msg-bubble {{ background: var(--user-bg); border: 1px solid transparent; border-bottom-right-radius: 4px; }}
        .msg.agent .msg-bubble {{ background: var(--agent-bg); border: 1px solid var(--border); border-bottom-left-radius: 4px; }}
        .sender {{ font-size: 13px; font-weight: 500; color: var(--gray); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
        .msg.user .sender {{ justify-content: flex-end; }}
        pre {{ background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; margin: 12px 0; }}
        code {{ font-family: monospace; font-size: 0.9em; }}
        p {{ margin: 0 0 12px 0; }} p:last-child {{ margin: 0; }}
        
        .action-bar {{ position: absolute; top: -14px; right: 12px; opacity: 0; transition: opacity 0.2s, transform 0.2s; transform: translateY(4px); }}
        .msg.agent:hover .action-bar {{ opacity: 1; transform: translateY(0); }}
        .btn-explain {{ background: #ffffff; border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px; font-size: 12px; font-family: 'Inter'; cursor: pointer; color: var(--primary); font-weight: 500; box-shadow: 0 2px 6px rgba(0,0,0,0.05); transition: all 0.2s; }}
        .btn-explain:hover {{ transform: scale(1.05); border-color: var(--primary); }}
        .btn-explain:disabled {{ opacity: 0.7; cursor: not-allowed; transform: none; }}
        .explanation-box {{ margin-top: 12px; background: #eef2ff; border: 1px solid #c7d2fe; border-left: 4px solid var(--primary); border-radius: 8px; padding: 16px 20px; font-size: 14px; color: #312e81; animation: fadeIn 0.3s ease; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(-4px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        
        .modal-backdrop {{ position: fixed; inset: 0; background: rgba(15,23,42,0.4); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 1000; opacity: 0; pointer-events: none; transition: 0.2s; }}
        .modal-backdrop.show {{ opacity: 1; pointer-events: auto; }}
        .modal {{ background: #ffffff; border-radius: 16px; padding: 32px; width: 400px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1); transform: scale(0.95); transition: 0.2s; }}
        .modal-backdrop.show .modal {{ transform: scale(1); }}
        .modal h3 {{ margin: 0 0 24px 0; font-size: 18px; }}
        .form-group {{ margin-bottom: 16px; }}
        .form-group label {{ display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; color: #475569; }}
        .form-group input {{ width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none; transition: 0.2s; }}
        .form-group input:focus {{ border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }}
        .modal-actions {{ display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }}
        .btn {{ padding: 8px 16px; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; border: none; font-family: inherit; transition: 0.2s; }}
        .btn-cancel {{ background: #f1f5f9; color: #475569; }} .btn-cancel:hover {{ background: #e2e8f0; }}
        .btn-save {{ background: var(--primary); color: white; }} .btn-save:hover {{ background: #4338ca; }}
    </style>
</head>
<body>
    <div class="nav">
        <div>Session Explorer: {username}</div>
        <button class="nav-btn" onclick="openSettings()">⚙️ Settings</button>
    </div>
    <div class="chat-container">{html_msgs}</div>

    <div class="modal-backdrop" id="settings-modal">
        <div class="modal">
            <h3>LLM Configuration</h3>
            <div class="form-group"><label>API Base URL</label><input type="text" id="inp-url" placeholder="https://api.openai.com/v1/chat/completions"></div>
            <div class="form-group"><label>API Key</label><input type="password" id="inp-key" placeholder="sk-..."></div>
            <div class="form-group"><label>Model Name</label><input type="text" id="inp-model" placeholder="gpt-4o"></div>
            <div class="modal-actions">
                <button class="btn btn-cancel" onclick="closeSettings()">Cancel</button>
                <button class="btn btn-save" onclick="saveSettings()">Save & Close</button>
            </div>
        </div>
    </div>

    <script>
        const msgsData = {msg_json};
        const defUrl = "{default_url}";
        const defKey = "{default_key}";
        const defMod = "{default_model}";

        function getConf() {{
            return {{
                url: localStorage.getItem('biogen_api_url') || defUrl || 'https://api.openai.com/v1/chat/completions',
                key: localStorage.getItem('biogen_api_key') || defKey || '',
                model: localStorage.getItem('biogen_model') || defMod || 'gpt-4o'
            }};
        }}

        function openSettings() {{
            const c = getConf();
            document.getElementById('inp-url').value = c.url;
            document.getElementById('inp-key').value = c.key;
            document.getElementById('inp-model').value = c.model;
            document.getElementById('settings-modal').classList.add('show');
        }}

        function closeSettings() {{ document.getElementById('settings-modal').classList.remove('show'); }}
        function saveSettings() {{
            localStorage.setItem('biogen_api_url', document.getElementById('inp-url').value);
            localStorage.setItem('biogen_api_key', document.getElementById('inp-key').value);
            localStorage.setItem('biogen_model', document.getElementById('inp-model').value);
            closeSettings();
        }}

        async function explainStep(idx) {{
            const conf = getConf();
            if(!conf.key) {{ openSettings(); return; }}

            const btn = document.getElementById('btn-explain-' + idx);
            const box = document.getElementById('explanation-' + idx);
            btn.innerText = '⏳ Thinking...'; btn.disabled = true;

            const initPrompt = msgsData.find(m => (m.role||'').toLowerCase() === 'user')?.content || "No initial prompt";
            const contextSlice = msgsData.slice(Math.max(0, idx - 5), idx);
            const targetStep = msgsData[idx];

            let ctxText = `[INITIAL OBJECTIVE]\\n${{initPrompt}}\\n\\n`;
            if (contextSlice.length > 0) {{
                ctxText += `[PRIOR CONTEXT]\\n`;
                contextSlice.forEach(m => ctxText += `${{m.role}}: ${{m.content}}\\n\\n`);
            }}
            ctxText += `[TARGET STEP TO EXPLAIN]\\nRole: ${{targetStep.role}}\\nContent: ${{targetStep.content}}`;

            try {{
                const res = await fetch(conf.url, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': `Bearer ${{conf.key}}` }},
                    body: JSON.stringify({{
                        model: conf.model,
                        temperature: 0.2,
                        messages: [
                            {{ role: 'system', content: 'You are an expert technical product manager. Explain ONLY the [TARGET STEP TO EXPLAIN]. Use the prior context for background, but DO NOT explain the entire workflow. Be concise, insightful, and format output exactly in Markdown.' }},
                            {{ role: 'user', content: ctxText }}
                        ]
                    }})
                }});
                const data = await res.json();
                if(data.error) throw new Error(data.error.message);
                
                box.innerHTML = marked.parse(`**💡 Explanation:**\\n${{data.choices[0].message.content}}`);
                box.style.display = 'block';
            }} catch (e) {{
                alert('Generation Error: ' + e.message);
            }} finally {{
                btn.innerText = '✨ Explain'; btn.disabled = false;
            }}
        }}
    </script>
</body>
</html>"""
    return template

def render_terminal(md_text):
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        Console().print(Markdown(md_text))
    except ImportError: print(md_text)

def export_pdf(html_content, out_path):
    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(out_path)
    except ImportError: raise RuntimeError("weasyprint required. Install via: pip install weasyprint")

def call_llm_api(api_url, api_key, model, system_prompt, user_content, temperature=0.1):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}], "temperature": temperature}
    req = urllib.request.Request(api_url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())['choices'][0]['message']['content'].strip()
    except urllib.error.HTTPError as e: raise RuntimeError(f"HTTP {e.code} {e.reason} - {e.read().decode('utf-8')}")

def clean_code_block(text):
    lines = text.strip().split('\n')
    if lines and lines[0].startswith('```'): lines = lines[1:]
    if lines and lines[-1].startswith('```'): lines = lines[:-1]
    return '\n'.join(lines).strip()

def validate_snakemake(code):
    try: subprocess.run(["snakemake", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except Exception: return True, ""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.smk', delete=False) as f:
        f.write(code)
        tmp = f.name
        
    try:
        res = subprocess.run(["snakemake", "-s", tmp, "--list-rules"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.remove(tmp)
        if res.returncode != 0: return False, res.stderr or res.stdout
        return True, ""
    except Exception as e:
        if os.path.exists(tmp): os.remove(tmp)
        return False, str(e)

def llm_action(action_type, messages, api_url, api_key, model):
    history = "\n\n".join([f"{msg.get('role', 'Unknown')}: {msg.get('content', '')}" for msg in messages])
    
    sys_prompts = {
        'snakemake': (
            "You are an expert bioinformatics workflow engineer. Create a production-ready, highly robust Snakemake workflow matching the chat history execution steps. "
            "CRITICAL REQUIREMENTS:\n"
            "1. You MUST make all input and output paths configurable via a `config` dictionary at the top of the file. Provide default values that exactly match the paths used in the chat history, but leave clear comments instructing the user to override them if needed.\n"
            "2. You MUST include environment building steps for reproducibility. Use Snakemake's `conda:` directive with inline YAML definitions (or clearly specify dependencies) for the rules.\n"
            "3. Follow nf-core level best practices for design and robustness.\n"
            "Output ONLY valid Python/Snakemake code, without markdown wrappers like ```."
        ),
        'skill': (
            "You are a senior AI prompt engineer. Extract the methodology from the chat history and create an 'Agent Skill' SOP to instruct another AI agent to reproduce the steps in production. "
            "CRITICAL REQUIREMENTS:\n"
            "1. DO NOT assume or hardcode any fixed file paths (e.g., /home/user/data.txt).\n"
            "2. Use abstract placeholders (e.g., <input_file>, <reference_genome>) and explicitly instruct the agent to ask the user to provide the actual paths before executing any step.\n"
            "Adhere to best practices for prompt engineering. Output ONLY valid Markdown, no markdown wrappers like ```."
        ),
        'flowchart': (
            "Analyze chat history and extract key workflow steps. "
            "Output ONLY a valid JSON object without markdown wrappers: {\"steps\": [{\"id\": \"step1\", \"label\": \"Name\", \"command\": \"cmd or N/A\", \"deps\": []}]}. IDs must be alphanumeric."
        )
    }
    
    if action_type in ['snakemake', 'skill']:
        candidates = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(call_llm_api, api_url, api_key, model, sys_prompts[action_type], history, 0.7) for _ in range(3)]
            for f in concurrent.futures.as_completed(futures):
                try: candidates.append(f.result())
                except Exception: pass
                
        if not candidates: raise RuntimeError("Failed to generate any candidates. Please check your API/Rate limits.")
        
        if len(candidates) == 1:
            res = candidates[0]
        else:
            eval_sys = "You are a strict, expert technical reviewer evaluating AI-generated workflows/SOPs."
            eval_usr = f"RULES:\n{sys_prompts[action_type]}\n\n"
            for i, c in enumerate(candidates): eval_usr += f"--- CANDIDATE {i+1} ---\n{c}\n\n"
            eval_usr += f'Analyze the {len(candidates)} candidates against the RULES. Which is the most robust and strictly follows the instructions? Return ONLY a JSON object: {{"best_candidate_index": 1}} (or up to {len(candidates)}). No markdown, no extra text.'
            
            try:
                eval_res = call_llm_api(api_url, api_key, model, eval_sys, eval_usr, 0.1)
                m = re.search(r'"best_candidate_index"\s*:\s*(\d+)', eval_res)
                best_idx = int(m.group(1)) - 1 if m else 0
                best_idx = max(0, min(best_idx, len(candidates) - 1))
                res = candidates[best_idx]
            except Exception: res = candidates[0]
    else:
        res = call_llm_api(api_url, api_key, model, sys_prompts[action_type], history, 0.1)
        
    logging.info(f"LLM Action '{action_type}' completed. Output length: {len(res)} characters.")

    return clean_code_block(res) if action_type in ['snakemake', 'flowchart'] else res

def generate_flowchart_html(json_payload):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Workflow Architecture</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: false, theme: 'base', securityLevel: 'loose', themeVariables: {{ primaryColor: '#ffffff', primaryBorderColor: '#cbd5e1', primaryTextColor: '#1e293b', lineType: 'basis', fontFamily: 'Inter' }} }});
        
        const data = {json_payload};
        let showAll = false;

        window.renderGraph = async function() {{
            let mk = "graph TD\\n";
            data.steps.forEach(step => {{
                let lbl = step.label;
                if (showAll && step.command && step.command !== "N/A") {{
                    let cmd = step.command.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    lbl = `<b>${{step.label}}</b><br/><div style='background:#f1f5f9; color:#334155; padding:8px; border-radius:6px; font-family:monospace; font-size:12px; margin-top:8px; text-align:left; max-width:320px; white-space:pre-wrap; word-break:break-word; border:1px solid #e2e8f0;'>${{cmd}}</div>`;
                }} else {{
                    lbl = `<div style='padding:4px 8px;'><b>${{step.label}}</b></div>`;
                }}
                mk += `${{step.id}}["${{lbl}}"]:::${{step.id}}\\n`;
                (step.deps || []).forEach(dep => mk += `${{dep}} --> ${{step.id}}\\n`);
            }});
            mk += "classDef default fill:#ffffff,stroke:#94a3b8,stroke-width:2px,color:#0f172a,rx:10px,ry:10px;\\n";
            const {{ svg }} = await mermaid.render('mermaid-svg', mk);
            document.getElementById('graph-container').innerHTML = svg;
            attachListeners();
        }};

        function attachListeners() {{
            const tooltip = document.getElementById('tooltip');
            data.steps.forEach(step => {{
                document.querySelectorAll(`.${{step.id}}`).forEach(node => {{
                    node.addEventListener('mouseenter', (e) => {{
                        if (showAll || !step.command || step.command === "N/A") return;
                        tooltip.innerHTML = `<div><strong style="color:#94a3b8;font-size:10px;text-transform:uppercase;">Executed Command</strong><br/>` + step.command.replace(/</g, '&lt;').replace(/>/g, '&gt;') + `</div>`;
                        tooltip.classList.add('visible');
                        const rect = node.getBoundingClientRect();
                        tooltip.style.left = (rect.left + window.scrollX + rect.width/2) + 'px';
                        tooltip.style.top = (rect.bottom + window.scrollY + 12) + 'px';
                    }});
                    node.addEventListener('mouseleave', () => tooltip.classList.remove('visible'));
                }});
            }});
        }}

        document.getElementById('toggleSwitch').addEventListener('change', (e) => {{ showAll = e.target.checked; document.getElementById('tooltip').classList.remove('visible'); renderGraph(); }});
        renderGraph();
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        body {{ font-family: 'Inter', sans-serif; background: #f8fafc; margin: 0; padding: 0; color: #0f172a; }}
        header {{ background: #ffffff; padding: 20px 40px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }}
        .title h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
        .title p {{ margin: 4px 0 0 0; color: #64748b; font-size: 13px; }}
        .toggle-wrapper {{ display: flex; align-items: center; gap: 12px; }}
        .toggle-label {{ font-size: 14px; font-weight: 500; }}
        .switch {{ position: relative; display: inline-block; width: 44px; height: 24px; }}
        .switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5e1; transition: .3s; border-radius: 24px; }}
        .slider:before {{ position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .3s; border-radius: 50%; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        input:checked + .slider {{ background-color: #0f172a; }}
        input:checked + .slider:before {{ transform: translateX(20px); }}
        #graph-container {{ display: flex; justify-content: center; padding: 48px; min-height: 80vh; }}
        .tooltip {{ position: absolute; background: rgba(15, 23, 42, 0.95); color: #f8fafc; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 13px; pointer-events: none; opacity: 0; transition: opacity 0.2s; max-width: 450px; white-space: pre-wrap; transform: translateX(-50%); z-index: 1000; line-height: 1.5; }}
        .tooltip.visible {{ opacity: 1; }}
    </style>
</head>
<body>
    <header>
        <div class="title"><h1>Workflow Architecture</h1><p>AI-generated execution graph</p></div>
        <div class="toggle-wrapper"><span class="toggle-label">Show Commands</span><label class="switch"><input type="checkbox" id="toggleSwitch"><span class="slider"></span></label></div>
    </header>
    <div id="graph-container"></div>
    <div id="tooltip" class="tooltip"></div>
</body>
</html>"""

def run_gui(initial_db=None, initial_port=8080):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("bioGen Enhanced Viewer")
    root.geometry("680x680")
    style = ttk.Style()
    style.theme_use('clam')
    db_ref = {"db": None}
    
    def update_server_status():
        if server_mgr.server:
            status_var.set(f"Web Server Running on port {server_mgr.port}")
            btn_stop_srv.config(state=tk.NORMAL)
        else:
            status_var.set("Ready")
            btn_stop_srv.config(state=tk.DISABLED)

    def stop_server_ui():
        server_mgr.stop()
        update_server_status()

    def process_file_load(path):
        if path:
            file_var.set(path)
            try:
                db_ref["db"] = load_db(path)
                users = list_users(db_ref["db"])
                user_cb['values'] = users
                if users: user_cb.current(0)
            except Exception as e: messagebox.showerror("Error", str(e))

    def get_msgs():
        if not db_ref["db"] or not user_var.get():
            messagebox.showwarning("Warning", "Select a database and user.")
            return None
        return get_user_history(db_ref["db"], user_var.get())

    def execute_viewer():
        msgs = get_msgs()
        if not msgs: return
        fmt, user = format_var.get(), user_var.get()
        if fmt in ['web', 'enrich_web']:
            if fmt == 'enrich_web':
                html = generate_enrich_html(msgs, user, api_url_var.get(), api_key_var.get(), model_var.get())
            else: html = generate_basic_html(format_markdown(msgs, user))
            p = server_mgr.start(html, port_var.get())
            update_server_status()
            webbrowser.open(f"http://localhost:{p}")
        elif fmt == 'term': threading.Thread(target=render_terminal, args=(format_markdown(msgs, user),), daemon=True).start()
        else:
            out = filedialog.asksaveasfilename(defaultextension=f".{fmt}")
            if out:
                if fmt == 'md':
                    with open(out, 'w', encoding='utf-8') as f: f.write(format_markdown(msgs, user))
                elif fmt == 'pdf': export_pdf(generate_basic_html(format_markdown(msgs, user)), out)
                messagebox.showinfo("Success", f"Saved to {out}")

    def execute_llm(action):
        msgs = get_msgs()
        if not msgs: return
        url, key, mod = api_url_var.get(), api_key_var.get(), model_var.get()
        if not key: return messagebox.showwarning("Warning", "API Key is required.")
        
        def run():
            progress.start(10)
            eval_txt = " (Evaluating 3 candidates)" if action in ['snakemake', 'skill'] else ""
            status_var.set(f"Generating {action}{eval_txt} via LLM...")
            try:
                res = llm_action(action, msgs, url, key, mod)
                root.after(0, lambda: handle_llm_result(action, res))
            except Exception as e: 
                logging.error(f"LLM generation error: {e}")
                root.after(0, lambda: messagebox.showerror("Generation Error", str(e)))
            finally:
                root.after(0, progress.stop)
                root.after(0, update_server_status)
                
        threading.Thread(target=run, daemon=True).start()

    def handle_llm_result(action, result):
        if action == 'snakemake':
            is_valid, err = validate_snakemake(result)
            if not is_valid:
                if not messagebox.askyesno("Validation Failed", f"Snakemake validation failed:\n{err[:400]}...\n\nSave anyway? (Click No to discard)"): return

        if action == 'flowchart':
            p = server_mgr.start(generate_flowchart_html(result), port_var.get())
            update_server_status()
            webbrowser.open(f"http://localhost:{p}")
        else:
            ext = ".smk" if action == "snakemake" else ".md"
            filepath = filedialog.asksaveasfilename(defaultextension=ext, title=f"Save {action}")
            if filepath:
                with open(filepath, 'w', encoding='utf-8') as f: f.write(result)
                messagebox.showinfo("Success", f"Saved to {filepath}")

    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill=tk.X, side=tk.TOP, before=notebook)
    
    file_var, user_var = tk.StringVar(), tk.StringVar()
    ttk.Label(top_frame, text="Database File (*.db or *.json):", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=tk.W, pady=2)
    ttk.Entry(top_frame, textvariable=file_var, state='readonly').grid(row=1, column=0, sticky=tk.EW, padx=(0,10))
    ttk.Button(top_frame, text="Browse", command=lambda: process_file_load(filedialog.askopenfilename(filetypes=[("DB & JSON", "*.db *.json"), ("All Files", "*.*")]))).grid(row=1, column=1)
    ttk.Label(top_frame, text="Select User Session:", font=("Arial", 9, "bold")).grid(row=2, column=0, sticky=tk.W, pady=(10,2))
    user_cb = ttk.Combobox(top_frame, textvariable=user_var, state="readonly")
    user_cb.grid(row=3, column=0, columnspan=2, sticky=tk.EW)
    top_frame.columnconfigure(0, weight=1)

    tab_viewer = ttk.Frame(notebook, padding=20)
    notebook.add(tab_viewer, text="Viewer Options")
    
    format_var = tk.StringVar(value='enrich_web')
    ttk.Label(tab_viewer, text="Output Format:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0,5))
    for text, val in [('Enriched Web (Modern UI)', 'enrich_web'), ('Standard Web', 'web'), ('Terminal Console', 'term'), ('Export Markdown', 'md'), ('Export PDF', 'pdf')]: 
        ttk.Radiobutton(tab_viewer, text=text, variable=format_var, value=val).pack(anchor=tk.W)

    port_frame = ttk.Frame(tab_viewer)
    port_frame.pack(anchor=tk.W, pady=(15, 5))
    ttk.Label(port_frame, text="Web UI Port:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
    port_var = tk.IntVar(value=initial_port)
    ttk.Entry(port_frame, textvariable=port_var, width=10).pack(side=tk.LEFT, padx=5)

    ttk.Button(tab_viewer, text="Generate / View", command=execute_viewer).pack(fill=tk.X, pady=20)

    tab_llm = ttk.Frame(notebook, padding=20)
    notebook.add(tab_llm, text="LLM Toolset")
    api_url_var = tk.StringVar(value=os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1/chat/completions'))
    api_key_var = tk.StringVar(value=os.environ.get('OPENAI_API_KEY', ''))
    model_var = tk.StringVar(value=os.environ.get('OPENAI_MODEL', 'gpt-4o'))

    for label, var, show in [("API URL:", api_url_var, ""), ("API Key:", api_key_var, "*"), ("Model:", model_var, "")]:
        ttk.Label(tab_llm, text=label, font=("Arial", 9)).pack(anchor=tk.W)
        ttk.Entry(tab_llm, textvariable=var, show=show).pack(fill=tk.X, pady=(0, 10))

    ttk.Label(tab_llm, text="⚠️ Note: LLM-generated content may be inaccurate. Please verify before use.", foreground="red", font=("Arial", 8)).pack(anchor=tk.W, pady=5)
    
    btn_frame = ttk.Frame(tab_llm)
    btn_frame.pack(fill=tk.X, pady=(5, 0))
    ttk.Button(btn_frame, text="Generate Snakemake", command=lambda: execute_llm('snakemake')).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
    ttk.Button(btn_frame, text="Generate Flowchart", command=lambda: execute_llm('flowchart')).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
    ttk.Button(btn_frame, text="Generate Skill SOP", command=lambda: execute_llm('skill')).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

    status_frame = ttk.Frame(root)
    status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=5)
    status_var = tk.StringVar(value="Ready")
    ttk.Label(status_frame, textvariable=status_var, font=("Arial", 8, "italic")).pack(side=tk.LEFT)
    btn_stop_srv = ttk.Button(status_frame, text="Stop Server", state=tk.DISABLED, command=stop_server_ui)
    btn_stop_srv.pack(side=tk.RIGHT, padx=(10, 0))
    progress = ttk.Progressbar(status_frame, mode='indeterminate', length=100)
    progress.pack(side=tk.RIGHT)

    if initial_db: process_file_load(initial_db)
    root.mainloop()

class CLISpinner:
    def __init__(self, msg="Processing"):
        self.spinner, self.stop_evt, self.msg, self.thread = itertools.cycle(['-', '\\', '|', '/']), False, msg, None
    def _spin(self):
        while not self.stop_evt:
            sys.stdout.write(f'\r[INFO] {self.msg} {next(self.spinner)}')
            sys.stdout.flush()
            time.sleep(0.1)
        sys.stdout.write(f'\r[INFO] {self.msg} Done!   \n')
    def start(self):
        self.stop_evt = False
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_evt = True
        if self.thread: self.thread.join()

def cli_main(args):
    db = load_db(args.db)
    if args.list:
        print("\n".join(f" - {u}" for u in list_users(db)))
        sys.exit(0)
    if not args.user: sys.exit("[ERROR] Specify --user")
    
    msgs = get_user_history(db, args.user)
    if not msgs: sys.exit("[INFO] No history found.")

    if args.llm_action:
        if not args.api_key: sys.exit("[ERROR] --api-key required.")
        print("\n[WARNING] LLM-generated content may be inaccurate. Please review carefully.\n")
        eval_txt = " (3 Candidates + LLM Evaluation)" if args.llm_action in ['snakemake', 'skill'] else ""
        spin = CLISpinner(f"Generating via LLM{eval_txt}")
        spin.start()
        res = llm_action(args.llm_action, msgs, args.api_url, args.api_key, args.model)
        spin.stop()
        
        if args.llm_action == 'snakemake':
            is_valid, err = validate_snakemake(res)
            if not is_valid:
                print(f"\n[ERROR] Snakemake format invalid:\n{err[:500]}...")
                if input("Save anyway? [y/N]: ").lower() != 'y': sys.exit("[INFO] Discarded. Try generating again.")

        if args.llm_action == 'flowchart':
            p = server_mgr.start(generate_flowchart_html(res), args.port)
            print(f"[INFO] Server at http://localhost:{p}. Ctrl+C to stop.")
            try: time.sleep(99999)
            except KeyboardInterrupt: pass
        else:
            out = args.out or f"output.{'smk' if args.llm_action=='snakemake' else 'md'}"
            with open(out, 'w', encoding='utf-8') as f: f.write(res)
            print(f"[INFO] Saved to {out}")
    else:
        if args.format in ['web', 'enrich_web']:
            html = generate_enrich_html(msgs, args.user, args.api_url, args.api_key, args.model) if args.format == 'enrich_web' else generate_basic_html(format_markdown(msgs, args.user))
            p = server_mgr.start(html, args.port)
            print(f"[INFO] Server at http://localhost:{p}. Ctrl+C to stop.")
            try: time.sleep(99999)
            except KeyboardInterrupt: pass
        elif args.format == 'term': render_terminal(format_markdown(msgs, args.user))
        else:
            out = args.out or f"{args.user}_out.{args.format}"
            if args.format == 'md':
                with open(out, 'w', encoding='utf-8') as f: f.write(format_markdown(msgs, args.user))
            elif args.format == 'pdf': export_pdf(generate_basic_html(format_markdown(msgs, args.user)), out)
            print(f"[INFO] Saved to {out}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="bioGen Enhanced Session Viewer")
    parser.add_argument('db', nargs='?', help="Path to DB/JSON (optional if launching GUI)")
    parser.add_argument('--gui', action='store_true', help="Force launch the graphical interface")
    parser.add_argument('--list', action='store_true', help="List all users in the database")
    parser.add_argument('--user', help="Specify user session to process")
    parser.add_argument('--format', choices=['term', 'md', 'pdf', 'web', 'enrich_web'], default='term', help="Output rendering format")
    parser.add_argument('--out', help="Output file path destination")
    parser.add_argument('--port', type=int, default=8080, help="Specify the port for Web UI server (default: 8080)")
    parser.add_argument('--llm-action', choices=['snakemake', 'flowchart', 'skill'], help="LLM post-processing action")
    parser.add_argument('--api-url', default=os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1/chat/completions'), help="LLM API Base URL")
    parser.add_argument('--api-key', default=os.environ.get('OPENAI_API_KEY', ''), help="LLM API Key")
    parser.add_argument('--model', default=os.environ.get('OPENAI_MODEL', 'gpt-4o'), help="LLM Model Name")
    args = parser.parse_args()

    # Route automatically to GUI if --gui is provided, OR if no critical CLI actions are provided
    if args.gui or (not args.db and not args.list and not args.user and not args.llm_action):
        run_gui(initial_db=args.db, initial_port=args.port)
    else:
        cli_main(args)