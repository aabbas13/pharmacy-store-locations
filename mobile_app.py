import re
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG & ULTRA-COMPACT MOBILE STYLING ---
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

st.markdown("""
<style>
    /* Global Compact Layout */
    .block-container { padding-top: 0.2rem !important; padding-bottom: 0.3rem !important; padding-left: 0.3rem !important; padding-right: 0.3rem !important; }
    div[data-testid="stVerticalBlock"] > div { gap: 0.15rem !important; }
    
    /* Segmented Control / Radio Buttons Top Bar */
    div[data-testid="stRadio"] { margin-bottom: 0.2rem !important; }
    div[role="radiogroup"] {
        background-color: #e2e8f0 !important;
        padding: 4px !important;
        border-radius: 8px !important;
        display: flex !important;
        width: 100% !important;
        justify-content: space-between !important;
    }
    div[role="radiogroup"] label {
        flex: 1 !important;
        text-align: center !important;
        padding: 4px 0px !important;
        margin: 0px !important;
        border-radius: 6px !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        cursor: pointer !important;
    }

    /* Small Pill Button Styling for Location Selections */
    .stButton button { 
        padding: 0.1rem 0.2rem !important; 
        font-size: 0.75rem !important; 
        height: 28px !important; 
        min-height: 28px !important;
    }

    .stTextInput input, .stSelectbox div[data-baseweb="select"] { 
        padding: 0.15rem 0.3rem !important; 
        font-size: 0.8rem !important; 
        min-height: 32px !important; 
    }

    hr { margin: 0.25rem 0 !important; }
    .stCaption { font-size: 0.72rem !important; margin-bottom: 0px !important; line-height: 1.1 !important; }
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
# ALWAYS-VISIBLE MODE SELECTOR AT TOP
# ==============================================================================
app_mode = st.radio(
    "App Mode",
    options=["🔍 Item Search", "📦 Bin Filling"],
    horizontal=True,
    key="global_app_mode_toggle",
    label_visibility="collapsed"
)

st.markdown("<hr/>", unsafe_allow_html=True)

# Helper function to render horizontal button selection pills
def render_button_picker(prefix_key, options, default_val):
    if f"{prefix_key}_selected" not in st.session_state:
        st.session_state[f"{prefix_key}_selected"] = default_val

    cols = st.columns(len(options))
    for idx, opt in enumerate(options):
        is_active = (st.session_state[f"{prefix_key}_selected"] == opt)
        btn_type = "primary" if is_active else "secondary"
        if cols[idx].button(opt, key=f"{prefix_key}_btn_{opt}", type=btn_type, use_container_width=True):
            st.session_state[f"{prefix_key}_selected"] = opt
            st.rerun()
            
    return st.session_state[f"{prefix_key}_selected"]

# ==============================================================================
# MODE 1: ITEM SEARCH MODE (SINGLE UNIFIED SEARCH FIELD)
# ==============================================================================
if app_mode == "🔍 Item Search":
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0

    st.caption("🔍 **Search & Select Medicine:**")
    
    # Build options mapping for the searchable selectbox
    search_options = {}
    for idx, itm in enumerate(items):
        code = itm["item_code"]
        desc = itm["description"]
        last_4 = code[-4:] if len(code) >= 4 else code
        label = f"[{last_4}] {code} — {desc}"
        search_options[label] = idx

    # Unified 1-field search: users type 4 digits or name directly here
    selected_item_label = st.selectbox(
        "Search Item",
        options=list(search_options.keys()),
        index=st.session_state.current_index,
        key="unified_item_search",
        placeholder="Type 4 digits or item name...",
        label_visibility="collapsed"
    )

    if selected_item_label and selected_item_label in search_options:
        st.session_state.current_index = search_options[selected_item_label]

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
    st.caption("📍 **Configure Location (Button Picker):**")

    # Area Selection Pills
    st.caption("Area:")
    sel_area = render_button_picker("item_area", ["A1", "A2", "CR", "B1"], "A1")

    # Type Selection Pills
    st.caption("Type:")
    sel_type = render_button_picker("item_type", ["DR", "SH", "FR"], "DR")

    # Series/Sec and Bin/Level Selections
    col1, col2 = st.columns(2)
    with col1:
        if sel_type == "DR":
            sig1 = st.selectbox("Series", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key="item_sig1_dr")
        elif sel_type == "SH":
            sig1 = st.selectbox("Sec", ["A", "B", "C", "D", "E", "F"], key="item_sig1_sh")
        else:
            sig1 = st.selectbox("Sec", ["FR", "RA", "RB"], key="item_sig1_fr")

    with col2:
        if sel_type == "DR":
            sig2 = st.selectbox("Bin#", [f"{i:02d}" for i in range(1, 30)], key="item_sig2_dr")
            generated_location = f"{sel_area}.DR.{sig1}.{sig2}"
        elif sel_type == "SH":
            sig2 = st.selectbox("Level#", [f"{i:02d}" for i in range(1, 40)], key="item_sig2_sh")
            generated_location = f"{sel_area}.SH.{sig1}.{sig2}"
        else:
            sig2 = st.selectbox("Bin#", [f"{i:02d}" for i in range(1, 20)], key="item_sig2_fr")
            generated_location = f"{sel_area}.{sig1}.01.{sig2}"

    c_in, c_btn = st.columns([3, 1])
    target_loc_input = c_in.text_input(
        "Final Locator", 
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
# MODE 2: BIN FILLING MODE
# ==============================================================================
else:
    st.caption("📦 **Set Active Bin Location:**")

    # Area Selection Pills
    st.caption("Area:")
    bin_area = render_button_picker("bin_area", ["A1", "A2", "CR", "B1"], "A1")

    # Type Selection Pills
    st.caption("Type:")
    bin_type = render_button_picker("bin_type", ["DR", "SH", "FR"], "DR")

    # Series/Sec & Bin# Selections
    col1, col2 = st.columns(2)
    with col1:
        if bin_type == "DR":
            b_sig1 = st.selectbox("Series", ["BA", "BB", "BC", "BD", "BE", "BF", "DA", "DB", "DC"], key="bin_sig1_dr")
        elif bin_type == "SH":
            b_sig1 = st.selectbox("Sec", ["A", "B", "C", "D", "E", "F"], key="bin_sig1_sh")
        else:
            b_sig1 = st.selectbox("Sec", ["FR", "RA", "RB"], key="bin_sig1_fr")

    with col2:
        if bin_type == "DR":
            b_sig2 = st.selectbox("Bin#", [f"{i:02d}" for i in range(1, 30)], key="bin_sig2_dr")
            active_bin_gen = f"{bin_area}.DR.{b_sig1}.{b_sig2}"
        elif bin_type == "SH":
            b_sig2 = st.selectbox("Level#", [f"{i:02d}" for i in range(1, 40)], key="bin_sig2_sh")
            active_bin_gen = f"{bin_area}.SH.{b_sig1}.{b_sig2}"
        else:
            b_sig2 = st.selectbox("Bin#", [f"{i:02d}" for i in range(1, 20)], key="bin_sig2_fr")
            active_bin_gen = f"{bin_area}.{b_sig1}.01.{b_sig2}"

    target_bin_location = fix_location_format(active_bin_gen)
    st.markdown(f"📍 Active Target: **`{target_bin_location}`**")

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
        "Search Medicine to Add",
        placeholder="Type 4 digits or name to assign",
        key="bin_digit_srch",
        on_change=handle_assign_by_enter,
        label_visibility="collapsed"
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
    st.caption(f"📋 **Items in `{target_bin_location}`:**")
    current_bin_items = [itm for itm in items if target_bin_location in itm["locations"]]

    if not current_bin_items:
        st.caption("No items assigned to this bin yet.")
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