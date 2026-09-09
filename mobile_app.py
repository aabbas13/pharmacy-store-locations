import re
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG & COMPACT CSS ---
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

# Inject CSS for maximum compact view on mobile browsers
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 0.5rem; padding-right: 0.5rem; }
    div[data-testid="stVerticalBlock"] > div { gap: 0.35rem; }
    h1 { font-size: 1.3rem !important; margin-bottom: 0.2rem !important; }
    h2 { font-size: 1.1rem !important; margin-bottom: 0.2rem !important; }
    h3 { font-size: 0.95rem !important; margin-bottom: 0.2rem !important; }
    .stButton button { padding: 0.2rem 0.5rem !important; font-size: 0.85rem !important; height: auto !important; }
    .stTextInput input { padding: 0.25rem 0.5rem !important; font-size: 0.85rem !important; }
    .stSelectbox div[data-baseweb="select"] { min-height: 32px !important; }
    hr { margin: 0.4rem 0 !important; }
    .stCaption { font-size: 0.75rem !important; margin-bottom: 0px !important; }
</style>
""", unsafe_allow_html=True)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_gspread_client():
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    else:
        st.error("Missing [gcp_service_account] in Streamlit Secrets!")
        st.stop()

try:
    gc = get_gspread_client()
    SHEET_NAME = "HMC MCP Store Locations"
    sheet = gc.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {e}")
    st.stop()

def fix_location_format(loc_str: str) -> str:
    if not loc_str:
        return ""
    cleaned = loc_str.upper().strip()
    if re.match(r"^[A-Z0-9]{2}\.[A-Z0-9]{2}\.[A-Z0-9]{1,2}\.[A-Z0-9]{1,2}$", cleaned):
        return cleaned
    raw_chars = re.sub(r'[^A-Z0-9]', '', cleaned)
    if len(raw_chars) == 7:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:5]}.{raw_chars[5:7]}"
    elif len(raw_chars) == 8:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:6]}.{raw_chars[6:8]}"
    return cleaned

@st.cache_data(ttl=30)
def load_data():
    records = sheet.get_all_records()
    items_dict = {}

    for row_idx, row in enumerate(records, start=2):
        code = str(row.get('Item Code', '')).strip().upper()
        desc = str(row.get('Item Description', '')).strip()
        uom = str(row.get('UOM', '')).strip()
        sub_inv = str(row.get('Sub Inventory', '')).strip()
        raw_loc = str(row.get('Location', '')).strip()

        parsed_locations = []
        if raw_loc:
            lines = raw_loc.split('\n')
            for line in lines:
                parts = line.split(',')
                for p in parts:
                    cleaned_p = p.strip().upper()
                    if cleaned_p and cleaned_p not in parsed_locations:
                        parsed_locations.append(cleaned_p)

        if code not in items_dict:
            items_dict[code] = {
                "item_code": code,
                "description": desc,
                "uom": uom,
                "sub_inv": sub_inv,
                "locations": parsed_locations,
                "row_indices": [row_idx]
            }
        else:
            for loc in parsed_locations:
                if loc not in items_dict[code]["locations"]:
                    items_dict[code]["locations"].append(loc)
            items_dict[code]["row_indices"].append(row_idx)

    return list(items_dict.values())

items = load_data()

if not items:
    st.warning("No item records found in Google Sheet.")
    st.stop()

# --- COMPACT WORKFLOW MODE SELECTOR ---
app_mode = st.radio(
    "Mode:",
    ["Item-by-Item Mode", "Bin-Filling Mode"],
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("<hr/>", unsafe_allow_html=True)

# ==============================================================================
# MODE 1: ITEM-BY-ITEM
# ==============================================================================
if app_mode == "Item-by-Item Mode":
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0

    item_options = {}
    for idx, itm in enumerate(items):
        code = itm["item_code"]
        desc = itm["description"]
        last_4 = code[-4:] if len(code) >= 4 else code
        label = f"[{last_4}] {code} — {desc}"
        item_options[label] = idx

    search_query = st.selectbox(
        "Search Medicine:",
        options=[""] + list(item_options.keys()),
        index=0,
        key="search_dropdown"
    )

    if search_query and search_query in item_options:
        selected_idx = item_options[search_query]
        if st.session_state.current_index != selected_idx:
            st.session_state.current_index = selected_idx
            st.rerun()

    current_item = items[st.session_state.current_index]

    # Compact Header Block
    st.caption(f"Med {st.session_state.current_index + 1}/{len(items)} | `{current_item['item_code']}` | UOM: `{current_item['uom']}`")
    st.subheader(current_item["description"])

    # Registered Locations Compact Grid
    current_locations = current_item["locations"]
    if current_locations:
        st.caption("📍 **Registered Locations:**")
        for loc_idx, loc_val in enumerate(current_locations):
            c_loc, c_del = st.columns([4, 1])
            c_loc.markdown(f"`{loc_val}`")
            if c_del.button("❌", key=f"del_{st.session_state.current_index}_{loc_idx}"):
                updated_locs = [l for l in current_locations if l != loc_val]
                cell_text = "\n".join(updated_locs)
                sheet.update_cell(current_item["row_indices"][0], 5, cell_text)
                st.toast(f"Removed {loc_val}!", icon="🗑️")
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("No location assigned yet.")

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.caption("➕ **Add Location:**")

    input_key = f"new_loc_{st.session_state.current_index}"
    if input_key not in st.session_state:
        st.session_state[input_key] = ""

    # Compact Storage Quick Selectors
    loc_type = st.radio("Type:", ["Drawers (DR)", "Shelves (SH)", "Fridge (FR)"], horizontal=True)

    if loc_type == "Drawers (DR)":
        c_dr1, c_dr2 = st.columns(2)
        dr_prefix = c_dr1.selectbox("Drawer:", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key=f"dr_p_{st.session_state.current_index}")
        dr_num = c_dr2.selectbox("Bin #:", [f"{i:02d}" for i in range(1, 21)], key=f"dr_n_{st.session_state.current_index}")
        target_gen = f"A1.DR.{dr_prefix}.{dr_num}"
    elif loc_type == "Shelves (SH)":
        c_sh1, c_sh2 = st.columns(2)
        sh_sec = c_sh1.selectbox("Section:", ["A", "B", "C", "D", "E", "F"], key=f"sh_s_{st.session_state.current_index}")
        sh_num = c_sh2.selectbox("Shelf #:", [f"{i:02d}" for i in range(1, 30)], key=f"sh_n_{st.session_state.current_index}")
        target_gen = f"A1.SH.{sh_sec}.{sh_num}"
    else:
        c_fr1, c_fr2 = st.columns(2)
        fr_sec = c_fr1.selectbox("Section:", ["FR", "RA", "RB"], key=f"fr_s_{st.session_state.current_index}")
        fr_num = c_fr2.selectbox("Bin #:", [f"{i:02d}" for i in range(1, 15)], key=f"fr_n_{st.session_state.current_index}")
        target_gen = f"CR.{fr_sec}.01.{fr_num}"

    c_in, c_btn = st.columns([3, 2])
    raw_location = c_in.text_input("Loc:", value=target_gen, key=input_key, label_visibility="collapsed").strip().upper()
    fixed_location = fix_location_format(raw_location)

    if c_btn.button("➕ Add", type="primary", use_container_width=True):
        if fixed_location in current_locations:
            st.warning("Already added.")
        else:
            updated_locs = current_locations + [fixed_location]
            sheet.update_cell(current_item["row_indices"][0], 5, "\n".join(updated_locs))
            st.toast(f"Added {fixed_location}!", icon="✅")
            st.cache_data.clear()
            st.rerun()

    # Navigation Buttons
    st.markdown("<hr/>", unsafe_allow_html=True)
    b_prev, b_next = st.columns(2)
    if b_prev.button("⬅️ Previous", use_container_width=True) and st.session_state.current_index > 0:
        st.session_state.current_index -= 1
        st.rerun()
    if b_next.button("Next ➡️", use_container_width=True) and st.session_state.current_index < len(items) - 1:
        st.session_state.current_index += 1
        st.rerun()

# ==============================================================================
# MODE 2: BIN-FILLING MODE
# ==============================================================================
else:
    st.caption("📦 **Select Storage Bin:**")
    
    bin_type = st.radio("Storage Category:", ["Drawers (DR)", "Shelves (SH)", "Fridge (FR)"], horizontal=True)

    if bin_type == "Drawers (DR)":
        col_b1, col_b2 = st.columns(2)
        b_prefix = col_b1.selectbox("Series:", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key="b_dr_p")
        b_num = col_b2.selectbox("Number:", [f"{i:02d}" for i in range(1, 21)], key="b_dr_n")
        active_bin = f"A1.DR.{b_prefix}.{b_num}"
    elif bin_type == "Shelves (SH)":
        col_s1, col_s2 = st.columns(2)
        s_sec = col_s1.selectbox("Shelf Section:", ["A", "B", "C", "D", "E", "F"], key="b_sh_s")
        s_num = col_s2.selectbox("Shelf Level:", [f"{i:02d}" for i in range(1, 30)], key="b_sh_n")
        active_bin = f"A1.SH.{s_sec}.{s_num}"
    else:
        col_f1, col_f2 = st.columns(2)
        f_sec = col_f1.selectbox("Fridge Section:", ["FR", "RA", "RB"], key="b_fr_s")
        f_num = col_f2.selectbox("Fridge Bin:", [f"{i:02d}" for i in range(1, 15)], key="b_fr_n")
        active_bin = f"CR.{f_sec}.01.{f_num}"

    target_location = fix_location_format(active_bin)
    st.info(f"📍 Active Bin: **`{target_location}`**")

    st.markdown("<hr/>", unsafe_allow_html=True)
    
    # Quick Search & Add Med to Bin
    c_srch, c_num_in = st.columns([3, 2])
    digit_input = c_srch.text_input("Item Search:", placeholder="Last 4 digits / code", key="bin_digit_srch", label_visibility="collapsed").strip().upper()

    matched_items = [itm for itm in items if digit_input and (itm["item_code"].endswith(digit_input) or digit_input in itm["item_code"])]

    if matched_items:
        for m in matched_items:
            m_code = m["item_code"]
            m_desc = m["description"]
            m_locs = m["locations"]
            
            cm1, cm2 = st.columns([3, 1])
            cm1.caption(f"**{m_desc}** (`{m_code}`)")
            if cm2.button("➕ Assign", key=f"bin_assign_{m_code}", type="primary"):
                if target_location not in m_locs:
                    updated_locs = m_locs + [target_location]
                    sheet.update_cell(m["row_indices"][0], 5, "\n".join(updated_locs))
                    st.toast(f"Assigned {m_code}!", icon="✅")
                    st.cache_data.clear()
                    st.rerun()

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.caption(f"📋 **Meds currently in `{target_location}`:**")
    current_bin_items = [itm for itm in items if target_location in itm["locations"]]

    if not current_bin_items:
        st.caption("No items in this bin.")
    else:
        for idx, b_item in enumerate(current_bin_items, start=1):
            cb_info, cb_del = st.columns([4, 1])
            cb_info.markdown(f"**{idx}.** {b_item['description']} (`{b_item['item_code']}`)")
            if cb_del.button("❌", key=f"bin_unassign_{b_item['item_code']}_{idx}"):
                updated_locs = [l for l in b_item["locations"] if l != target_location]
                sheet.update_cell(b_item["row_indices"][0], 5, "\n".join(updated_locs))
                st.toast(f"Unassigned {b_item['item_code']}", icon="🗑️")
                st.cache_data.clear()
                st.rerun()