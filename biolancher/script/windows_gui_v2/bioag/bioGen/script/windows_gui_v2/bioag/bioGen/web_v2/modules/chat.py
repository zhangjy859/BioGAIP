import re
import streamlit as st
from bioGen.web_v2.utils import get_avatar

def render_welcome_and_messages(storage, starters):
    welcome_placeholder = st.empty()

    if not st.session_state.messages and st.session_state.get('api_setup_done', False):
        with welcome_placeholder.container():
            st.markdown("""
                <style>
                .welcome-bg-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background-image: radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.08), transparent 30%), radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.08), transparent 30%), linear-gradient(rgba(15, 23, 42, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(15, 23, 42, 0.03) 1px, transparent 1px); background-size: 100% 100%, 100% 100%, 40px 40px, 40px 40px; z-index: -1; pointer-events: none; }
                .welcome-title-anim { background: linear-gradient(90deg, #1E293B, #3B82F6, #10B981, #1E293B); background-size: 300% 100%; -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: gradient-shift 8s ease infinite; }
                @keyframes gradient-shift { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
                </style>
                <div class="welcome-bg-container"></div><div style='margin-top: 5rem;'></div>
                <h1 class='welcome-title-anim' style='text-align: center; font-size: 3rem; font-weight: 800;'>BioGAIP Workspace</h1>
                <p style='text-align: center; color: #64748b; margin-bottom: 3rem; font-size: 1.1rem;'>Select an intelligent template below or begin typing to interact with the agents.</p>
            """, unsafe_allow_html=True)
            cols = st.columns(2)
            for i, starter in enumerate(starters):
                with cols[i % 2]:
                    if st.button(f"✨ {starter['label']}", key=f"starter_{i}", width="stretch", help=starter['message']):
                        st.session_state.messages.append({"role": "user", "content": starter["message"]})
                        storage.save_session(st.session_state.username, st.session_state)
                        st.rerun()
    else:
        welcome_placeholder.empty()

    for message in st.session_state.messages:
        message_uuid = message.get('message_uuid', None)
        if message["role"] != "user_proxy" and message["content"].startswith("@user_proxy:") and message["content"].startswith("user_proxy:"): continue
        if message["role"] == "thought":
            with st.expander(f"🧠 Internal Thought Stream: {message['source']}"): st.markdown(message["content"])
        else:
            with st.chat_message(message["role"], avatar=get_avatar(message["role"])):
                if "cleaned_content" not in message or "file_blocks" not in message:
                    content = message["content"]
                    message["file_blocks"] = re.findall(r'<uploaded_file name="(.*?)" ext="(.*?)"\>(.*?)</uploaded_file>', content, re.DOTALL)
                    message["cleaned_content"] = re.sub(r'<uploaded_file name=".*?" ext=".*?"\>(.*?)</uploaded_file>', '', content, flags=re.DOTALL)
                
                st.markdown(message["cleaned_content"].strip())
                for name, ext, file_content in message["file_blocks"]:
                    with st.expander(f"📄 Attached Document: {name}"): st.code(file_content.strip(), language=ext.lower() if ext.lower() in ['python', 'json', 'html', 'md', 'txt'] else None)
        if message_uuid: st.session_state.message_processed_front_ui_uuid.append(message_uuid)