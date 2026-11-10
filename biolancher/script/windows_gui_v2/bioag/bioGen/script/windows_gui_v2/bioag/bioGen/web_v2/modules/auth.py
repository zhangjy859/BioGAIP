import os
import random
import hashlib
import datetime
import streamlit as st
from datetime import timedelta
from streamlit_cookies_manager import EncryptedCookieManager

def handle_authentication(storage):
    cookiers_password = os.environ.get("COOKIE_PASSWORD", None)
    if not cookiers_password and not st.session_state.get('cookier_password', None):
        cookiers_password = random.randbytes(64).hex()
        os.environ["COOKIE_PASSWORD"] = cookiers_password
    if not st.session_state.get('cookier_password', None):
        st.session_state.cookier_password = os.environ["COOKIE_PASSWORD"]

    cookies = EncryptedCookieManager(prefix="biogen_", password=st.session_state.cookier_password)
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated and cookies.ready():
        if cookies.get('authenticated') == 'True':
            try:
                st.session_state.authenticated = True
                st.session_state.login_time = datetime.datetime.fromisoformat(cookies.get('login_time', ''))
                st.session_state.username = cookies.get('username', '')
                st.rerun()
            except Exception:
                cookies['authenticated'] = 'False'
                cookies.save()
                st.session_state.authenticated = False

    if not st.session_state.authenticated:
        _render_login_ui(cookies, storage)
        st.stop()
    else:
        if (datetime.datetime.now() - st.session_state.login_time) > timedelta(days=3):
            st.session_state.authenticated = False
            cookies['authenticated'] = 'False'
            cookies.save()
            st.rerun()
        else:
            if 'session_loaded' not in st.session_state:
                if 'project_id' in cookies and 'project_id' not in st.session_state:
                    st.session_state.project_id = cookies['project_id']
                storage.load_session(st.session_state.username, st.session_state)
                st.session_state.session_loaded = True
                if st.session_state.get('processing', False) and 'reconnect_warning_shown' not in st.session_state:
                    st.warning("Reconnection detected during an active task. Monitoring session.")
                    st.session_state.reconnect_warning_shown = True
                    storage.save_session(st.session_state.username, st.session_state)
    return cookies

def _render_login_ui(cookies, storage):
    st.markdown("""
        <style>
        [data-testid="stAppViewContainer"] { background: linear-gradient(-45deg, #f8fafc, #e2e8f0, #e0f2fe, #f1f5f9); background-size: 400% 400%; animation: gradientBG 15s ease infinite; position: relative; }
        @keyframes gradientBG { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        .shape-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; overflow: hidden; z-index: 0; pointer-events: none; }
        .bg-shape { position: absolute; border-radius: 50%; filter: blur(60px); opacity: 0.5; animation: drift 15s infinite alternate; }
        .shape1 { top: -10%; left: -10%; width: 50vw; height: 50vw; background: rgba(59, 130, 246, 0.4); }
        .shape2 { bottom: -10%; right: -10%; width: 40vw; height: 40vw; background: rgba(16, 185, 129, 0.3); animation-delay: -5s; }
        .shape3 { top: 40%; left: 60%; width: 30vw; height: 30vw; background: rgba(139, 92, 246, 0.2); animation-delay: -10s; }
        @keyframes drift { 0% { transform: translate(0, 0) scale(1); } 100% { transform: translate(30px, 30px) scale(1.1); } }
        div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stVerticalBlock"] { background: rgba(255, 255, 255, 0.7) !important; backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-radius: 24px; padding: 2.5rem 2rem; box-shadow: 0 10px 40px -10px rgba(31, 38, 135, 0.15), inset 0 0 0 1px rgba(255, 255, 255, 0.5); transition: transform 0.3s ease, box-shadow 0.3s ease; position: relative; z-index: 1; }
        div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stVerticalBlock"]:hover { transform: translateY(-5px); box-shadow: 0 20px 40px -10px rgba(31, 38, 135, 0.2), inset 0 0 0 1px rgba(255, 255, 255, 0.6); }
        .stTextInput input { border-radius: 12px !important; border: 1px solid rgba(203, 213, 225, 0.8) !important; background: rgba(255, 255, 255, 0.9) !important; transition: all 0.3s ease !important; }
        .stTextInput input:focus { box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3) !important; border-color: #3b82f6 !important; }
        .stButton button { border-radius: 12px !important; font-weight: 600 !important; letter-spacing: 0.5px !important; transition: all 0.3s ease !important; }
        </style>
        <div class="shape-container"><div class="bg-shape shape1"></div><div class="bg-shape shape2"></div><div class="bg-shape shape3"></div></div>
    """, unsafe_allow_html=True)

    logo_url = "https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505"
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(f'<div style="text-align: center; position: relative; z-index: 1;"><img src="{logo_url}" alt="Logo" style="max-width: 220px; height: auto;"></div>', unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center; color: #1E293B; margin-top: 10px; position: relative; z-index: 1;'> </h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b; position: relative; z-index: 1;'>Sign in to your intelligent bioinformatics workspace</p><br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.container():
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            with st.expander("⚙️ Advanced Settings"):
                usrname_id_login = st.text_input("Project ID (optional)", value="", help="Bind to a specific BioWorker project session")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Sign In", type="primary", width="stretch"):
                app_user = os.environ.get('APP_USER')
                salt = os.environ.get('PASSWORD_SALT')
                
                def get_hashed(pwd, s): return hashlib.sha256((pwd + s).encode('utf-8')).hexdigest()

                is_valid_login = False
                if app_user and os.path.isfile(app_user):
                    try:
                        with open(app_user, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if not line or line.startswith('#'): continue
                                parts = line.split(':', 1)
                                if len(parts) == 2:
                                    file_user, file_pass = parts
                                    if file_user == username:
                                        if (get_hashed(password, salt) if salt else password) == file_pass:
                                            is_valid_login = True
                                        break
                    except Exception: pass
                else:
                    expected_username, expected_password = (app_user.split(':', 1) + [''])[:2] if app_user else ("admin", "admin")
                    if username == expected_username and (get_hashed(password, salt) if salt else password) == expected_password:
                        is_valid_login = True

                if is_valid_login:
                    st.session_state.authenticated = True
                    st.session_state.login_time = datetime.datetime.now()
                    st.session_state.username = username
                    cookies['authenticated'] = 'True'
                    cookies['login_time'] = st.session_state.login_time.isoformat()
                    cookies['username'] = username
                    if usrname_id_login:
                        st.session_state.project_id = usrname_id_login
                        cookies['project_id'] = usrname_id_login
                    cookies.save()
                    storage.load_session(st.session_state.username, st.session_state)
                    st.rerun()
                else:
                    st.error("Invalid credentials. Please try again.")