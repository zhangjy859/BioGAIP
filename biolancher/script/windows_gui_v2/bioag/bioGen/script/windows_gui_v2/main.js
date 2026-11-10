const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

let mainWindow;
let streamlitProcess;

const PORT = 8503;
const SHOW_MODE_SELECTION = true;

app.commandLine.appendSwitch('log-level', '3');
app.commandLine.appendSwitch('no-proxy-server');
app.commandLine.appendSwitch('ignore-certificate-errors');
app.commandLine.appendSwitch('allow-insecure-localhost');
app.commandLine.appendSwitch('disable-http2');

const LOADING_HTML = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body {
      background-color: #f2f3f5; display: flex; justify-content: center;
      align-items: center; height: 100vh; margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      user-select: none; -webkit-font-smoothing: antialiased;
    }
    .card {
      background: #ffffff; padding: 40px 48px; border-radius: 12px;
      box-shadow: 0 4px 10px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.02);
      text-align: center; width: 520px; animation: fadeIn 0.4s ease-out;
      display: flex; flex-direction: column; transition: all 0.3s;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .spinner {
      width: 36px; height: 36px; border: 3px solid #f3f4f6; border-top: 3px solid #1677ff;
      border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px auto;
    }
    @keyframes spin { 100% { transform: rotate(360deg); } }
    .title { font-size: 18px; font-weight: 600; color: #1d2129; margin: 0 0 8px 0; }
    .status { font-size: 14px; color: #4e5969; margin: 0 0 12px 0; }
    .info { font-size: 13px; color: #86909c; margin: 0; text-align: center; line-height: 1.5; }
    
    .console-container {
      margin-top: 24px; border-radius: 8px; background: #1e1e1e;
      box-shadow: inset 0 2px 4px rgba(0,0,0,0.1); display: none;
      text-align: left; overflow: hidden; animation: fadeIn 0.3s ease-out;
    }
    .console-header {
      background: #2d2d2d; padding: 8px 12px; font-size: 12px; color: #858585;
      display: flex; align-items: center; border-bottom: 1px solid #111;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
    .dot-red { background: #ff5f56; } .dot-yellow { background: #ffbd2e; } .dot-green { background: #27c93f; }
    .console {
      color: #d4d4d4; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px; padding: 12px; height: 150px; overflow-y: auto; line-height: 1.5;
      white-space: pre-wrap; word-break: break-all; scroll-behavior: smooth;
    }
    .console::-webkit-scrollbar { width: 6px; }
    .console::-webkit-scrollbar-thumb { background: #4a4a4a; border-radius: 3px; }

    .action-area { margin-top: 24px; display: none; }
    .btn {
      background-color: #f2f3f5; color: #4e5969; border: none; padding: 6px 16px;
      border-radius: 6px; font-size: 13px; cursor: pointer; transition: all 0.2s;
    }
    .btn:hover:not(:disabled) { background-color: #e5e6eb; color: #1d2129; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    
    .warning {
      background: #fff7e8; color: #ff7d00; padding: 10px 16px; border-radius: 8px;
      font-size: 13px; display: none; text-align: center; margin-top: 16px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <div class="title" id="title">Starting Workspace</div>
    <div class="status" id="status">Initializing system services...</div>
    <div class="info" id="info"></div>
    
    <div class="console-container" id="console-container">
      <div class="console-header">
        \\<div class="dot dot-red"></div><div class="dot dot-yellow"></div><div class="dot dot-green"></div>
        <span style="margin-left: 8px;">Installation Logs</span>
      </div>
      <div class="console" id="console"></div>
    </div>

    <div class="action-area" id="action-area">
      <button class="btn" id="cancel-btn">Cancel Installation</button>
    </div>
    <div class="warning" id="warning"></div>
  </div>
  <script>
    const { ipcRenderer } = require('electron');
    
    document.getElementById('cancel-btn').addEventListener('click', () => {
      const btn = document.getElementById('cancel-btn');
      btn.innerText = 'Cancelling...'; btn.disabled = true;
      ipcRenderer.send('cancel-biogaip-install');
    });

    window.updateUI = (title, status, info, showCancel) => {
      if (title) document.getElementById('title').innerText = title;
      if (status) document.getElementById('status').innerText = status;
      if (info !== undefined) document.getElementById('info').innerText = info;
      
      const actionArea = document.getElementById('action-area');
      if (showCancel) {
        actionArea.style.display = 'block';
        const btn = document.getElementById('cancel-btn');
        btn.innerText = 'Cancel Installation'; btn.disabled = false;
      } else {
        actionArea.style.display = 'none';
      }
    };

    window.appendLog = (msg) => {
      const container = document.getElementById('console-container');
      const el = document.getElementById('console');
      if (container.style.display !== 'block') container.style.display = 'block';
      el.appendChild(document.createTextNode(msg));
      el.scrollTop = el.scrollHeight;
    };

    window.showWarning = (msg) => {
      const el = document.getElementById('warning');
      el.innerText = msg; el.style.display = 'block';
    };
  </script>
</body>
</html>
`;

function getSelectionHTML(easyModeAvailable) {
  return `
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <style>
      body {
        background-color: #f2f3f5; display: flex; justify-content: center; align-items: center;
        height: 100vh; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        user-select: none; -webkit-font-smoothing: antialiased;
      }
      .container { text-align: center; }
      .title { font-size: 26px; font-weight: 600; color: #1d2129; margin-bottom: 40px; }
      .cards { display: flex; gap: 24px; justify-content: center; }
      .card {
        background: #ffffff; width: 240px; padding: 40px 24px; border-radius: 16px; cursor: pointer;
        box-shadow: 0 4px 10px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.02);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); border: 2px solid transparent;
        display: flex; flex-direction: column; align-items: center;
      }
      .card:hover:not(.disabled) {
        transform: translateY(-4px); box-shadow: 0 12px 24px rgba(0,0,0,0.08); border-color: #1677ff;
      }
      .card.disabled {
        background: #f7f8fa; cursor: not-allowed; opacity: 0.7; box-shadow: none; border-color: transparent;
      }
      .icon { font-size: 42px; margin-bottom: 20px; }
      .card-title { font-size: 18px; font-weight: 600; color: #1d2129; margin-bottom: 8px; }
      .card.disabled .card-title, .card.disabled .card-desc { color: #86909c; }
      .card-desc { font-size: 13px; color: #86909c; line-height: 1.6; }
      .badge {
        margin-top: 16px; padding: 6px 10px; background: #fff7e8; color: #ff7d00;
        border-radius: 6px; font-size: 12px; font-weight: 500; border: 1px solid #ffe4ba;
      }
      .spinner {
        width: 24px; height: 24px; border: 3px solid #e5e6eb; border-top: 3px solid #1677ff;
        border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 12px auto; display: none;
      }
      @keyframes spin { 100% { transform: rotate(360deg); } }
      .loading-text { font-size: 14px; color: #4e5969; display: none; margin-top: 16px; }
      .loading-container { margin-top: 40px; height: 60px; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="title">Select Workspace Mode</div>
      <div class="cards" id="cards">
        <div class="card ${easyModeAvailable ? '' : 'disabled'}" onclick="${easyModeAvailable ? "selectMode('easy')" : ""}">
          <div class="icon">🚀</div>
          <div class="card-title">Easy Mode</div>
          <div class="card-desc">Streamlined interface for quick and automated workflows.</div>
          ${!easyModeAvailable ? '<div class="badge">Unavailable: Dependency Missing</div>' : ''}
        </div>
        <div class="card" onclick="selectMode('advanced')">
          <div class="icon">🎛️</div>
          <div class="card-title">Advanced Mode</div>
          <div class="card-desc">Full access to all configurable features and parameters.</div>
        </div>
      </div>
      <div class="loading-container">
        <div class="spinner" id="spinner"></div>
        <div class="loading-text" id="loading">Starting selected workspace...</div>
      </div>
    </div>
    <script>
      const { ipcRenderer } = require('electron');
      function selectMode(mode) {
        document.getElementById('cards').style.pointerEvents = 'none';
        document.getElementById('cards').style.opacity = '0.5';
        document.getElementById('spinner').style.display = 'block';
        document.getElementById('loading').style.display = 'block';
        ipcRenderer.send('mode-selected', mode);
      }
    </script>
  </body>
  </html>
  `;
}

function logDebug(message) {
  if (process.stdout.isTTY || process.env.NODE_ENV !== 'production') {
    const timestamp = new Date().toISOString().substring(11, 23);
    console.log(`[UI-DEBUG ${timestamp}] ${message}`);
  }
}

function updateUI(title, status, info = '', showCancel = false) {
  logDebug(`State Transition -> [${title}] | ${status}`);
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.executeJavaScript(`if(window.updateUI) window.updateUI(${JSON.stringify(title)}, ${JSON.stringify(status)}, ${JSON.stringify(info)}, ${showCancel})`).catch(() => {});
}

function sendToUILog(msg) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.executeJavaScript(`if(window.appendLog) window.appendLog(${JSON.stringify(msg)})`).catch(() => {});
}

function showUIWarning(message) {
  logDebug(`UI Warning -> ${message}`);
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.executeJavaScript(`if(window.showWarning) window.showWarning(${JSON.stringify(message)})`).catch(() => {});
}

function runCommand(cmd, args, opts = {}, onLog = null) {
  logDebug(`Executing: ${cmd} ${args.join(' ')}`);
  return new Promise((resolve) => {
    const proc = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'pipe'], ...opts });
    let stdout = '';
    let stderr = '';
    
    proc.stdout.on('data', d => {
      const str = d.toString();
      stdout += str;
      if (onLog) onLog(str);
    });
    
    proc.stderr.on('data', d => {
      const str = d.toString();
      stderr += str;
      if (onLog) onLog(str);
    });
    
    proc.on('close', code => {
      logDebug(`Command exited with code: ${code}`);
      resolve({ code, stdout, stderr });
    });
    
    proc.on('error', err => {
      logDebug(`Command execution error: ${err.message}`);
      resolve({ code: -1, stdout: '', stderr: err.message });
    });
  });
}

async function checkPackageInstalled(pythonPath, packageName) {
  const res = await runCommand(pythonPath, ['-c', `import ${packageName}`]);
  return res.code === 0;
}

async function checkBiogaipInstalled(pythonPath) {
  const pythonDir = path.dirname(pythonPath);
  let searchPaths = process.platform === 'win32' 
    ? [path.join(pythonDir, 'Scripts', 'biogaip.exe'), path.join(pythonDir, 'Scripts', 'biogaip.cmd'), path.join(pythonDir, 'Scripts', 'biogaip')]
    : [path.join(pythonDir, 'biogaip')];

  let biogaipPath = null;
  for (const p of searchPaths) {
    if (fs.existsSync(p)) {
      biogaipPath = p;
      break;
    }
  }

  if (!biogaipPath) return false;

  const isCmd = process.platform === 'win32' && biogaipPath.endsWith('.cmd');
  const res = await runCommand(biogaipPath, ['-h'], { shell: isCmd });
  return res.code === 0;
}

function checkPortReady(port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(400);
    socket.on('connect', () => { socket.destroy(); resolve(true); });
    socket.on('error', () => { socket.destroy(); resolve(false); });
    socket.on('timeout', () => { socket.destroy(); resolve(false); });
    socket.connect(port, '127.0.0.1');
  });
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', (err) => resolve(err.code === 'EADDRINUSE'));
    server.once('listening', () => { server.close(); resolve(false); });
    server.listen(port, '127.0.0.1');
  });
}

function findPython() {
  const possibilities = [
    path.join(process.resourcesPath, 'python', 'python.exe'),
    path.join(__dirname, 'python', 'python.exe'),
    path.join(process.resourcesPath, 'python', 'python'),
    path.join(__dirname, 'python', 'python'),
    path.join(process.resourcesPath, 'python', 'bin', 'python'),
    path.join(__dirname, 'python', 'bin', 'python')
  ];
  for (const p of possibilities) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error('Python environment not found');
}

ipcMain.handle('open-file-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'] });
  return result.canceled ? '' : result.filePaths[0];
});

ipcMain.handle('open-directory-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return result.canceled ? '' : result.filePaths[0];
});

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    show: true,
    backgroundColor: '#f2f3f5',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false,
      allowRunningInsecureContent: true
    }
  });

  await mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(LOADING_HTML)}`);

  app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
    event.preventDefault();
    callback(true);
  });

  let pythonPath;
  try {
    pythonPath = findPython();
  } catch (err) {
    dialog.showMessageBoxSync({ type: 'error', title: 'Environment Error', message: 'Python environment not found.' });
    app.quit();
    return;
  }

  updateUI('Checking Environment', 'Verifying required dependencies...', 'Scanning local Python environment.');

  const hasStreamlit = await checkPackageInstalled(pythonPath, 'streamlit');
  if (!hasStreamlit) {
    updateUI('Initial Setup', 'Installing core dependencies...', 'This process only runs during the first launch.\nPlease be patient as it may take a few minutes.');
    const reqPath = app.isPackaged ? path.join(process.resourcesPath, 'requirements.txt') : path.join(__dirname, 'requirements.txt');
    if (fs.existsSync(reqPath)) {
      await runCommand(pythonPath, ['-m', 'pip', 'install', '-r', reqPath], {}, sendToUILog);
    }
  }

  let easyModeAvailable = false;
  const hasBiogaip = await checkBiogaipInstalled(pythonPath);
  
  if (!hasBiogaip) {
    let userCancelled = false;
    const cancelHandler = () => { userCancelled = true; };
    ipcMain.once('cancel-biogaip-install', cancelHandler);

    for (let i = 3; i > 0; i--) {
      if (userCancelled) break;
      updateUI('Environment Setup', 'Preparing to install dependencies...', `Installation will start automatically in ${i} seconds.`, true);
      await new Promise(r => setTimeout(r, 1000));
    }

    ipcMain.removeListener('cancel-biogaip-install', cancelHandler);

    if (!userCancelled) {
      updateUI('Configuring Modules', 'Installing workflow dependencies...', 'This is a one-time setup. Please wait while packages are configured.', false);
      const pkgPath = app.isPackaged ? path.join(process.resourcesPath, 'src', 'pip_package') : path.join(__dirname, 'src', 'pip_package');
      if (fs.existsSync(pkgPath)) {
        const installRes = await runCommand(pythonPath, ['-m', 'pip', 'install', pkgPath], {}, sendToUILog);
        if (installRes.code !== 0) {
          showUIWarning('Installation failed. App will launch, but Easy Mode will be unavailable.');
          await new Promise(r => setTimeout(r, 3500));
        } else {
          easyModeAvailable = true;
        }
      }
    } else {
      updateUI('Installation Skipped', 'Dependency setup cancelled by user.', '', false);
      showUIWarning('Note: Easy Mode will remain unavailable.');
      await new Promise(r => setTimeout(r, 2500));
    }
  } else {
    easyModeAvailable = true;
  }

  const startStreamlit = (mode) => {
    // for easymode use app_easymode.py, for advanced use app.py
    const appEasyModePath = app.isPackaged ? path.join(process.resourcesPath, 'app_easymode.py') : path.join(__dirname, 'app_easymode.py');
    const appPyPath = app.isPackaged ? path.join(process.resourcesPath, 'app.py') : path.join(__dirname, 'app.py');
    const targetScript = mode === 'easy' ? appEasyModePath : appPyPath; 
    
    streamlitProcess = spawn(pythonPath, [
      '-m', 'streamlit', 'run', targetScript,
      '--server.port', PORT.toString(),
      '--server.address', '127.0.0.1',
      '--server.headless', 'true',
      '--browser.gatherUsageStats', 'false',
      '--server.enableCORS', 'false',
      '--server.enableXsrfProtection', 'false'
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });

    let loaded = false;
    const tryLoad = () => {
      if (loaded || !mainWindow) return;
      loaded = true;
      if (checkInterval) clearInterval(checkInterval);
      mainWindow.loadURL(`http://127.0.0.1:${PORT}`).catch(() => {});
    };

    const checkInterval = setInterval(async () => {
      if (await checkPortReady(PORT)) tryLoad();
    }, 500);

    streamlitProcess.stdout.on('data', (data) => {
      const output = data.toString();
      if (output.includes('You can now view your Streamlit app') || output.includes('Local URL')) tryLoad();
    });

    streamlitProcess.on('error', (err) => {
      if (checkInterval) clearInterval(checkInterval);
      dialog.showErrorBox('Startup Failed', err.message);
    });
  };

  if (SHOW_MODE_SELECTION) {
    await mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(getSelectionHTML(easyModeAvailable))}`);
    ipcMain.once('mode-selected', (event, mode) => {
      startStreamlit(mode);
    });
  } else {
    updateUI('Starting Service', 'Launching application server...', 'Almost there...', false);
    startStreamlit('advanced');
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
    if (streamlitProcess) {
      streamlitProcess.kill();
      streamlitProcess = null;
    }
  });
}

app.on('ready', async () => {
  if (await isPortInUse(PORT)) {
    dialog.showMessageBoxSync({ type: 'warning', title: 'Port Occupied', message: `Port ${PORT} is already in use.`, buttons: ['OK'] });
    app.quit();
    return;
  }
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (mainWindow === null) createWindow();
});

app.on('before-quit', () => {
  if (streamlitProcess) {
    streamlitProcess.kill('SIGTERM');
    streamlitProcess = null;
  }
});