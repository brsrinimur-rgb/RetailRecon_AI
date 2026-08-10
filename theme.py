def global_css():
    return """
    <style>
    .block-container {padding-top: 1.2rem; max-width: 1250px;}
    [data-testid="stSidebar"] {background:#0d2345;}
    [data-testid="stSidebar"] * {color:white;}
    .ct-banner {background:#0d2345;color:white;padding:14px 20px;border-radius:0 0 12px 12px;margin-bottom:16px;}
    .ct-banner h2 {margin:0;font-size:21px;}
    .ct-banner p {margin:2px 0 0 0;color:#b9c9dd;font-size:12px;}
    .ct-card {border:1px solid #d9dee7;border-radius:10px;padding:16px;margin:8px 0;background:white;}
    .ct-flow {background:#e7f0fb;border-radius:8px;padding:13px 16px;color:#174a84;margin:12px 0 20px 0;}
    .small {color:#6c7580;font-size:13px;}
    </style>
    """

def top_banner(title, subtitle, notif_count=5):
    return f"""<div class="ct-banner"><h2>{title}</h2><p>{subtitle}</p></div>"""

def section_title(n, title):
    return f"<h3>{n}. {title}</h3>"

def data_source_note(is_live=True):
    return '<div class="small">Upload source files or use data from the current reconciliation session.</div>'
