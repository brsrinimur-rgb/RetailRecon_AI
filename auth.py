import streamlit as st

USERS = {
    "admin": {"password":"admin123","role":"Admin","name":"System Admin"},
    "finance": {"password":"finance123","role":"Finance Manager","name":"Finance Manager"},
    "maker": {"password":"maker123","role":"Finance Maker","name":"Finance Maker"},
    "checker": {"password":"checker123","role":"Finance Checker","name":"Finance Checker"},
}

def require_login(allowed_roles=None):
    if "user" not in st.session_state:
        st.session_state.user = None
    if st.session_state.user is None:
        st.title("Retail Control Tower")
        st.caption("Secure finance access")
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", use_container_width=True, type="primary")
        if ok:
            rec = USERS.get(u.strip().lower())
            if rec and rec["password"] == p:
                st.session_state.user = {"username":u.strip().lower(), **rec}
                st.rerun()
            else:
                st.error("Invalid username or password.")
        with st.expander("Demo logins"):
            st.write("admin / admin123")
            st.write("finance / finance123")
            st.write("maker / maker123")
            st.write("checker / checker123")
        st.stop()
    if allowed_roles and st.session_state.user["role"] not in allowed_roles:
        st.error("You do not have permission to access this page.")
        st.stop()

def render_user_sidebar():
    u = st.session_state.get("user")
    if not u: return
    st.sidebar.caption(f"{u['name']} · {u['role']}")
    if st.sidebar.button("Log out", use_container_width=True):
        st.session_state.user = None
        st.rerun()

def current_role():
    u = st.session_state.get("user")
    return u["role"] if u else ""
