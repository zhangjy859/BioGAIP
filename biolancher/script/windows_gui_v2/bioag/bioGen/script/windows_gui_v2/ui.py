import streamlit as st

def inject_dialog_style():
    """Injects CSS to prevent closing the dialog by clicking outside of it, while retaining the top-right 'X' button."""
    st.markdown("""
    <style>
    /* Prevent closing when clicking outside the dialog by disabling pointer events on the backdrop */
    div[data-testid="stModal"] > div:first-child { 
        pointer-events: none !important; 
    }
    
    /* Disable clicks on the main app background to prevent interacting with the app while modal is active */
    .stApp:has(div[data-testid="stModal"]) { 
        pointer-events: none !important; 
    }
    
    /* Safely re-enable clicks inside the dialog so content and the 'X' remain fully functional */
    div[role="dialog"] { 
        pointer-events: auto !important; 
    }
    
    @keyframes step-pulse {
        0% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(0, 123, 255, 0); }
        100% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0); }
    }
    </style>
    """, unsafe_allow_html=True)

def render_step(container, state="PENDING", text=""):
    icon = "⚪"
    color = "#6c757d"
    bg_color = "transparent"
    border_color = "rgba(128, 128, 128, 0.2)"
    animation = ""
    
    if state == "RUNNING":
        icon = "⏳"
        color = "#007BFF"
        bg_color = "rgba(0, 123, 255, 0.05)"
        border_color = "#007BFF"
        animation = "animation: step-pulse 1.5s infinite;"
    elif state == "SUCCESS":
        icon = "✅"
        color = "#28A745"
        bg_color = "rgba(40, 167, 69, 0.05)"
        border_color = "#28A745"
    elif state == "SKIPPED":
        icon = "❗"
        color = "#FD7E14"
        bg_color = "rgba(253, 126, 20, 0.05)"
        border_color = "#FD7E14"
    elif state == "ERROR":
        icon = "❌"
        color = "#DC3545"
        bg_color = "rgba(220, 53, 69, 0.05)"
        border_color = "#DC3545"

    html = f"""
    <div style="padding: 14px 18px; margin: 10px 0; border-radius: 10px; border: 1px solid {border_color}; background-color: {bg_color}; display: flex; align-items: center; transition: all 0.3s ease; {animation}">
        <span style="font-size: 1.5em; margin-right: 18px; line-height: 1;">{icon}</span>
        <span style="color: {color}; font-weight: 600; font-size: 1.1em; letter-spacing: 0.2px;">{text}</span>
    </div>
    """
    container.markdown(html, unsafe_allow_html=True)

def render_config_form(config, prefix=""):
    for key, value in config.items():
        full_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            st.subheader(key.capitalize())
            render_config_form(value, prefix=full_key)
        elif isinstance(value, bool):
            st.checkbox(key.capitalize(), value=value, key=full_key)
        elif isinstance(value, (int, float)):
            st.number_input(key.capitalize(), value=value, key=full_key)
        elif isinstance(value, str):
            input_type = "password" if "api_key" in key.lower() else "default"
            st.text_input(key.capitalize(), value=value, key=full_key, type=input_type)
        else:
            st.text_input(key.capitalize(), value=str(value), key=full_key)

def collect_edited_config(config, prefix=""):
    edited = {}
    for key, value in config.items():
        full_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            edited[key] = collect_edited_config(value, prefix=full_key)
        else:
            edited[key] = st.session_state.get(full_key, value)
    return edited