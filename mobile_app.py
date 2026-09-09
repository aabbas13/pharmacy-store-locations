import re
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG & COMPACT MOBILE STYLING ---
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

st.markdown("""
<style>
    .block-container { padding-top: 0.4rem; padding-bottom: 0.5rem; padding-left: 0.4rem; padding-right: 0.4rem; }
    div[data-testid="stVerticalBlock"] > div { gap: 0.25rem; }
    div[data-testid="column"] { padding: 0px 2px !important; }
    h1 { font-size: 1.2rem !important; margin-bottom: 0.1rem !important; }
    h2 { font-size: 1.05rem !important; margin-bottom: 0.1rem !important; }
    h3 { font-size: 0.9rem !important; margin-bottom: 0.1rem !important; }
    .stButton button { padding: 0.15rem 0.35rem !important; font-size: 0.8rem !important; height: auto !important; }
    .stTextInput input { padding: 0.15rem 0.35rem !important; font-size: 0.8rem !important; }
    .stSelectbox div[data-baseweb="select"] { min-height: 26px !important; font-size: 0.8rem !important; }
    hr { margin: 0.3rem 0 !important; }
    .stCaption { font-size: 0.72rem !important; margin-bottom: 0px !important; }
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

# ==============================================================================
# MODE SELECTOR (TOP NAVIGATION)
# ==============================================================================
mode_options = ["🔍 Item Search", "📦 Bin Filling"]

if hasattr(st, "segmented_control"):
    app_mode = st.segmented_control(
        "Select Operation Mode:",
        options=mode_options,
        default="🔍 Item Search",
        label_visibility="collapsed"
    )
else:
    app_mode = st.radio(
        "Select Operation Mode:",
        options=mode_options,
        horizontal=True,
        label_visibility="collapsed"
    )

st.markdown("<hr/>", unsafe_allow_html=True)

# ==============================================================================
# MODE 1: ITEM SEARCH
# ==============================================================================
if app_mode == "🔍 Item Search":
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0

    st.caption("🔍 **Search Medicine:**")
    search_term = st.text_input(
        "Type 4 digits (matches last 4) or medicine name:",
        key="search_term_input",
        placeholder="e.g., 1234 or Paracetamol"
    ).strip().upper()

    if search_term:
        if len(search_term) == 4 and search_term.isdigit():
            filtered_items = [itm for itm in items if itm["item_code"].endswith(search_term)]
        else:
            filtered_items = [
                itm for itm in items 
                if search_term in itm["item_code"] or search_term in itm["description"].upper()
            ]
    else:
        filtered_items = items

    item_options = {}
    for idx, itm in enumerate(filtered_items):
        code = itm["item_code"]
        desc = itm["description"]
        last_4 = code[-4:] if len(code) >= 4 else code
        label = f"[{last_4}] {code} — {desc}"
        item_options[label] = items.index(itm)

    if not item_options:
        st.warning("No items match your search criteria.")
    else:
        selected_label = st.selectbox(
            "Select Matching Medicine:",
            options=list(item_options.keys()),
            key="search_dropdown"
        )

        if selected_label in item_options:
            selected_idx = item_options[selected_label]
            if st.session_state.current_index != selected_idx:
                st.session_state.current_index = selected_idx
                st.rerun()

    current_item = items[st.session_state.current_index]

    st.caption(f"Med {st.session_state.current_index + 1}/{len(items)} | `{current_item['item_code']}` | UOM: `{current_item['uom']}`")
    st.subheader(current_item["description"])

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
    st.caption("➕ **Configure Location (Linear):**")

    # Linear Horizontal Row: Area | Type | Series/Sec | Bin#/Level#
    col_a, col_t, col_s1, col_s2 = st.columns([1, 1.2, 1.2, 1.2])
    area_val = col_a.selectbox("Area", ["A1", "A2", "CR", "B1"], key=f"item_area_{st.session_state.current_index}")
    loc_type = col_t.selectbox("Type", ["DR", "SH", "FR"], key=f"item_type_{st.session_state.current_index}")

    if loc_type == "DR":
        sig1 = col_s1.selectbox("Series", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key=f"item_sig1_{st.session_state.current_index}")
        sig2 = col_s2.selectbox("Bin#", [f"{i:02d}" for i in range(1, 30)], key=f"item_sig2_{st.session_state.current_index}")
        generated_location = f"{area_val}.DR.{sig1}.{sig2}"
    elif loc_type == "SH":
        sig1 = col_s1.selectbox("Sec", ["A", "B", "C", "D", "E", "F"], key=f"item_sig1_{st.session_state.current_index}")
        sig2 = col_s2.selectbox("Level#", [f"{i:02d}" for i in range(1, 40)], key=f"item_sig2_{st.session_state.current_index}")
        generated_location = f"{area_val}.SH.{sig1}.{sig2}"
    else:
        sig1 = col_s1.selectbox("Sec", ["FR", "RA", "RB"], key=f"item_sig1_{st.session_state.current_index}")
        sig2 = col_s2.selectbox("Bin#", [f"{i:02d}" for i in range(1, 20)], key=f"item_sig2_{st.session_state.current_index}")
        generated_location = f"{area_val}.{sig1}.01.{sig2}"

    c_in, c_btn = st.columns([3, 1])
    target_loc_input = c_in.text_input(
        "Final Locator:", 
        value=generated_location, 
        key=f"item_loc_input_{st.session_state.current_index}",
        label_visibility="collapsed"
    ).strip().upper()

    fixed_location = fix_location_format(target_loc_input)

    if c_btn.button("➕ Add", type="primary", use_container_width=True):
        if not fixed_location:
            st.warning("Invalid Location.")
        elif fixed_location in current_locations:
            st.warning("Already assigned.")
        else:
            updated_locs = current_locations + [fixed_location]
            sheet.update_cell(current_item["row_indices"][0], 5, "\n".join(updated_locs))
            st.toast(f"Added {fixed_location}!", icon="✅")
            st.cache_data.clear()
            st.rerun()

    st.markdown("<hr/>", unsafe_allow_html=True)
    b_prev, b_next = st.columns(2)
    if b_prev.button("⬅️ Previous", use_container_width=True) and st.session_state.current_index > 0:
        st.session_state.current_index -= 1
        st.rerun()
    if b_next.button("Next ➡️", use_container_width=True) and st.session_state.current_index < len(items) - 1:
        st.session_state.current_index += 1
        st.rerun()

# ==============================================================================
# MODE 2: BIN FILLING
# ==============================================================================
else:
    st.caption("📦 **Set Active Bin Location (Linear):**")

    # Linear Horizontal Controls (1 Row): Area . Type . Series/Sec . Bin#/Level#
    col_a, col_t, col_s1, col_s2 = st.columns([1, 1.2, 1.2, 1.2])

    bin_area = col_a.selectbox("Area", ["A1", "A2", "CR", "B1"], key="bin_area_sel")
    bin_type = col_t.selectbox("Type", ["DR", "SH", "FR"], key="bin_type_sel")

    if bin_type == "DR":
        b_sig1 = col_s1.selectbox("Series", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key="bin_sig1")
        b_sig2 = col_s2.selectbox("Bin#", [f"{i:02d}" for i in range(1, 30)], key="bin_sig2")
        active_bin_gen = f"{bin_area}.DR.{b_sig1}.{b_sig2}"
    elif bin_type == "SH":
        b_sig1 = col_s1.selectbox("Sec", ["A", "B", "C", "D", "E", "F"], key="bin_sig1")
        b_sig2 = col_s2.selectbox("Level#", [f"{i:02d}" for i in range(1, 40)], key="bin_sig2")
        active_bin_gen = f"{bin_area}.SH.{b_sig1}.{b_sig2}"
    else:
        b_sig1 = col_s1.selectbox("Sec", ["FR", "RA", "RB"], key="bin_sig1")
        b_sig2 = col_s2.selectbox("Bin#", [f"{i:02d}" for i in range(1, 20)], key="bin_sig2")
        active_bin_gen = f"{bin_area}.{b_sig1}.01.{b_sig2}"

    target_bin_location = fix_location_format(active_bin_gen)
    st.info(f"📍 Active Bin Target: **`{target_bin_location}`**")

    st.markdown("<hr/>", unsafe_allow_html=True)

    # Search & Assign Logic for Bin Mode
    def handle_assign_by_enter():
        val = st.session_state.get("bin_digit_srch", "").strip().upper()
        if val:
            if len(val) == 4 and val.isdigit():
                matches = [i for i in items if i["item_code"].endswith(val)]
            else:
                matches = [i for i in items if val in i["item_code"] or val in i["description"].upper()]
            
            if len(matches) == 1:
                target_item = matches[0]
                if target_bin_location not in target_item["locations"]:
                    updated = target_item["locations"] + [target_bin_location]
                    sheet.update_cell(target_item["row_indices"][0], 5, "\n".join(updated))
                    st.toast(f"Assigned {target_item['item_code']}!", icon="✅")
                    st.cache_data.clear()

    st.text_input(
        "Search Medicine to Add (Last 4 Digits or Name):",
        placeholder="Type 4 digits or name",
        key="bin_digit_srch",
        on_change=handle_assign_by_enter
    )

    digit_input = st.session_state.get("bin_digit_srch", "").strip().upper()
    if digit_input:
        if len(digit_input) == 4 and digit_input.isdigit():
            matched_items = [itm for itm in items if itm["item_code"].endswith(digit_input)]
        else:
            matched_items = [itm for itm in items if digit_input in itm["item_code"] or digit_input in itm["description"].upper()]
    else:
        matched_items = []

    if matched_items:
        for m in matched_items:
            m_code = m["item_code"]
            m_desc = m["description"]
            m_locs = m["locations"]
            
            cm1, cm2 = st.columns([3, 1])
            cm1.caption(f"**{m_desc}** (`{m_code}`)")
            if cm2.button("➕ Assign", key=f"bin_assign_{m_code}", type="primary"):
                if target_bin_location not in m_locs:
                    updated_locs = m_locs + [target_bin_location]
                    sheet.update_cell(m["row_indices"][0], 5, "\n".join(updated_locs))
                    st.toast(f"Assigned {m_code}!", icon="✅")
                    st.cache_data.clear()
                    st.rerun()

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.caption(f"📋 **Meds currently assigned to `{target_bin_location}`:**")
    current_bin_items = [itm for itm in items if target_bin_location in itm["locations"]]

    if not current_bin_items:
        st.caption("No items in this bin.")
    else:
        for idx, b_item in enumerate(current_bin_items, start=1):
            cb_info, cb_del = st.columns([4, 1])
            cb_info.markdown(f"**{idx}.** {b_item['description']} (`{b_item['item_code']}`)")
            if cb_del.button("❌", key=f"bin_unassign_{b_item['item_code']}_{idx}"):
                updated_locs = [l for l in b_item["locations"] if l != target_bin_location]
                sheet.update_cell(b_item["row_indices"][0], 5, "\n".join(updated_locs))
                st.toast(f"Unassigned {b_item['item_code']}", icon="🗑️")
                st.cache_data.clear()
                st.rerun()