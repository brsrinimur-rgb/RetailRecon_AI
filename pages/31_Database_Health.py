import streamlit as st
import auth,theme,db

st.set_page_config(page_title="Database Health",layout="wide",page_icon="🩺")
auth.require_login({"Admin"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Database Health & Migration"),unsafe_allow_html=True)

st.title("🩺 Database Health & Migration")

if st.button("RUN DATABASE MIGRATION / HEALTH CHECK",type="primary",use_container_width=True):
    try:
        db.migrate_database()
        st.success("Database migration completed.")
    except Exception as e:
        st.error(f"Database migration failed: {e}")

h=db.get_database_health()

c1,c2,c3=st.columns(3)
c1.metric("Schema Status","HEALTHY ✅" if h["Healthy"] else "REVIEW REQUIRED")
c2.metric("Current Schema Version",h["Schema Version"])
c3.metric("Required Schema Version",h["Required Version"])

st.caption(f"Last schema update: {h['Updated At'] or 'Not available'}")
st.dataframe(h["Tables"],use_container_width=True,hide_index=True)

st.markdown("### Migration History")
conn=db.get_conn()
try:
    hist=__import__("pandas").read_sql_query(
        """SELECT time AS "Time", from_version AS "From Version",
                  to_version AS "To Version", status AS "Status", notes AS "Notes"
           FROM schema_migration_log ORDER BY id DESC LIMIT 100""",conn
    )
finally:
    conn.close()
st.dataframe(hist,use_container_width=True,hide_index=True)

st.info(
    "This page is diagnostic only. Migrations use CREATE TABLE IF NOT EXISTS and ALTER TABLE ADD COLUMN. "
    "Existing production records are not deleted."
)
