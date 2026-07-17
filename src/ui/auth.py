"""Password gate."""
import streamlit as st

def _get_correct_password():
    try:
        return st.secrets["passwords"]["svc_password"]
    except Exception:
        pass
    try:
        return st.secrets["svc_password"]     # top-level fallback
    except Exception:
        return ""



def require_login():
    if not st.session_state.get("_authenticated"):
        correct = _get_correct_password()
        st.markdown("## 🥬 SVC Vegetables · Login")
        pwd = st.text_input("Password", type="password", key="_pwd_input")
        if st.button("Login"):
            if correct and pwd == correct:
                st.session_state["_authenticated"] = True
                st.rerun()
            elif not correct:
                st.session_state["_authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password. Try again.")
        st.stop()
