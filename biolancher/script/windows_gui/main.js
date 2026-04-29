const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

let mainWindow;
let streamlitProcess;

const PORT = 8503;   // Fixed Streamlit port

// Check if port is in use
function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    
    server.once('error', (err) => {
      if (err.code === 'EADDRINUSE') resolve(true);
      else resolve(false);
    });
    
    server.once('listening', () => {
      server.close();
      resolve(false);
    });
    
    server.listen(port, '127.0.0.1');
  });
}

function findPython() {
  const possibilities = [
    path.join(process.resourcesPath, 'python', 'python.exe'),
    path.join(__dirname, 'python', 'python.exe'),
    path.join(process.resourcesPath, 'python', 'python'),
    path.join(__dirname, 'python', 'python')
  ];
  for (const p of possibilities) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error('Python not found');
}

// IPC handlers
ipcMain.handle('open-file-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'] });
  return result.canceled ? '' : result.filePaths[0];
});

ipcMain.handle('open-directory-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return result.canceled ? '' : result.filePaths[0];
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  let pythonPath;
  try {
    pythonPath = findPython();
  } catch (err) {
    dialog.showMessageBoxSync({ type: 'error', title: 'Error', message: 'Python not found!' });
    app.quit();
    return;
  }

  const appPyPath = app.isPackaged 
    ? path.join(process.resourcesPath, 'app.py') 
    : path.join(__dirname, 'app.py');

  // Start Streamlit
  streamlitProcess = spawn(pythonPath, [
    '-m', 'streamlit', 'run', appPyPath,
    '--server.port', PORT.toString(),
    '--server.address', '127.0.0.1',
    '--server.headless', 'true'
  ], { stdio: ['pipe', 'pipe', 'pipe'] });

  let serverReady = false;
  streamlitProcess.stdout.on('data', (data) => {
    const output = data.toString();
    console.log(output);
    if (!serverReady && output.includes('You can now view your Streamlit app in your browser.')) {
      serverReady = true;
      mainWindow.loadURL(`http://localhost:${PORT}`);
    }
  });

  streamlitProcess.stderr.on('data', (data) => console.error(data.toString()));

  mainWindow.on('closed', () => {
    mainWindow = null;
    if (streamlitProcess) streamlitProcess.kill();
  });
}

// App ready + port check
app.on('ready', async () => {
  const portOccupied = await isPortInUse(PORT);
  
  if (portOccupied) {
    dialog.showMessageBoxSync({
      type: 'warning',
      title: 'Port Occupied',
      message: `Port ${PORT} is already in use!\n\nClose the program using this port then restart the app.`,
      buttons: ['OK']
    });
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
  if (streamlitProcess) streamlitProcess.kill('SIGTERM');
});