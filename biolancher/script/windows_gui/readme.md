### how to bulid
1. Download a Windows standalone Python build from https://github.com/indygreg/python-build-standalone/releases. 

    We use cpython-3.12.11+20250828-x86_64-pc-windows-msvc-install_only.tar.gz (https://github.com/astral-sh/python-build-standalone/releases/download/20250828/cpython-3.12.11+20250828-aarch64-pc-windows-msvc-install_only.tar.gz) here

    if you use linux, try: https://github.com/astral-sh/python-build-standalone/releases/download/20250828/cpython-3.11.13+20250828-s390x-unknown-linux-gnu-install_only.tar.gz

    if you use mac os, try: https://github.com/astral-sh/python-build-standalone/releases/download/20250828/cpython-3.11.13+20250828-x86_64-apple-darwin-install_only.tar.gz

2. Extract it to a folder named python in your project directory.

3. Open your terminal （powershell/shell), Install Streamlit into the bundled Python: python\python.exe -m pip install streamlit pyyaml psutil. 

    For Linux or mac, use python\python -m pip install streamlit pyyaml psutil

4. Install Node.js and npm if not already installed.  https://nodejs.org/zh-cn/download/ and https://github.com/coreybutler/nvm-windows/releases

5. In the project directory (with package.json, main.js, and app.py), run npm install.

6. To test: npm start.

7. To build the installer exe: npm run make. This will create a setup.exe in the out/make folder using Electron Forge with Squirrel maker, which produces a single exe installer for Windows.