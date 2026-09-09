import re
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

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
    SHEET_NAME = "HMC MCP Store Locations" # Ensure exact sheet title
    sheet = gc.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {e}")
    st.stop()

def fix_location_format(loc_str: str) -> str:
    """
    Auto-fixes location format to standard Oracle locator pattern (e.g., A1.SH.A.01).
    Handles missing dots, extra spaces, and lowercase letters.
    """
    if not loc_str:
        return ""
    
    # Capitalize and strip leading/trailing spaces
    cleaned = loc_str.upper().strip()
    
    # If already matches standard pattern XX.XX.X.XX or similar, return cleaned
    if re.match(r"^[A-Z0-9]{2}\.[A-Z0-9]{2}\.[A-Z0-9]{1,2}\.[A-Z0-9]{1,2}$", cleaned):
        return cleaned

    # Attempt auto-fix for plain alphanumeric string like A1SHA01 or A1 SH A 01
    raw_chars = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    # Expected standard length: 7 characters (e.g., A1 SH A 01 -> A1SHA01)
    if len(raw_chars) == 7:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:5]}.{raw_chars[5:7]}"
    # 8 characters (e.g., CRFR0101)
    elif len(raw_chars) == 8:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:6]}.{raw_chars[6:8]}"
        
    # Return cleaned if no auto-rule matched
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
        loc = str(row.get('Location', '')).strip().upper()

        if code not in items_dict:
            items_dict[code] = {
                "item_code": code,
                "description": desc,
                "uom": uom,
                "sub_inv": sub_inv,
                "locations": [],
                "row_indices": []
            }
        if loc and loc not in items_dict[code]["locations"]:
            items_dict[code]["locations"].append(loc)
        items_dict[code]["row_indices"].append(row_idx)

    return list(items_dict.values())

items = load_data()

if not items:
    st.warning("No item records found in Google Sheet.")
    st.stop()

# --- APP MODE SELECTION ---
app_mode = st.radio(
    "Select Workflow Mode:",
    ["Item-by-Item Mode", "Bin-Filling Mode (Set Location First)"],
    horizontal=True
)

st.markdown("---")

# ==============================================================================
# MODE 1: ITEM-BY-ITEM (SEQUENTIAL / SEARCH MODE)
# ==============================================================================
if app_mode == "Item-by-Item Mode":
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0

    st.subheader("🔍 Search Medicine")
    item_options = {}
    for idx, itm in enumerate(items):
        code = itm["item_code"]
        desc = itm["description"]
        last_4 = code[-4:] if len(code) >= 4 else code
        label = f"[{last_4}] {code} — {desc}"
        item_options[label] = idx

    search_query = st.selectbox(
        "Search by last 4 digits, full code, or name:",
        options=[""] + list(item_options.keys()),
        index=0,
        key="search_dropdown"
    )

    if search_query and search_query in item_options:
        selected_idx = item_options[search_query]
        if st.session_state.current_index != selected_idx:
            st.session_state.current_index = selected_idx
            st.rerun()

    st.markdown("---")
    current_item = items[st.session_state.current_index]

    input_key = f"loc_input_{st.session_state.current_index}"
    if input_key not in st.session_state:
        initial_val = current_item["locations"][0] if current_item["locations"] else ""
        st.session_state[input_key] = initial_val

    def apply_prefix(prefix):
        curr_text = st.session_state.get(input_key, "").upper()
        known_prefixes = ["A1.SH.", "A1.DR.", "A1.PL.", "CR.FR."]
        for p in known_prefixes:
            if curr_text.startswith(p):
                curr_text = curr_text[len(p):]
                break
        st.session_state[input_key] = prefix + curr_text

    st.caption(f"Medication {st.session_state.current_index + 1} of {len(items)}")
    st.title(current_item["description"])

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Item Code:** `{current_item['item_code']}`")
        st.write(f"**Sub Inventory:** `{current_item['sub_inv']}`")
    with col2:
        st.write(f"**UOM:** `{current_item['uom']}`")

    st.markdown("---")
    st.subheader("Oracle Locators")

    st.write("**Quick Prefixes:**")
    prefix_cols = st.columns(4)
    prefix_cols[0].button("A1.SH.", on_click=apply_prefix, args=("A1.SH.",), key="p1", use_container_width=True)
    prefix_cols[1].button("A1.DR.", on_click=apply_prefix, args=("A1.DR.",), key="p2", use_container_width=True)
    prefix_cols[2].button("A1.PL.", on_click=apply_prefix, args=("A1.PL.",), key="p3", use_container_width=True)
    prefix_cols[3].button("CR.FR.", on_click=apply_prefix, args=("CR.FR.",), key="p4", use_container_width=True)

    raw_location = st.text_input("Location 1", key=input_key).strip().upper()
    fixed_location = fix_location_format(raw_location)

    if fixed_location != raw_location and raw_location:
        st.caption(f"💡 Auto-formatted location to: `{fixed_location}`")

    st.markdown("---")
    btn_col1, btn_col2 = st.columns(2)

    if btn_col1.button("⬅️ Previous", use_container_width=True):
        if st.session_state.current_index > 0:
            st.session_state.current_index -= 1
            st.rerun()

    if btn_col2.button("Save & Next ➡️", type="primary", use_container_width=True):
        row_idx = current_item["row_indices"][0]
        sheet.update_cell(row_idx, 5, fixed_location)
        st.toast(f"Saved: {fixed_location}", icon="✅")
        st.cache_data.clear()
        if st.session_state.current_index < len(items) - 1:
            st.session_state.current_index += 1
            st.rerun()
        else:
            st.success("All items completed!")

# ==============================================================================
# MODE 2: BIN-FILLING MODE (SET LOCATION FIRST -> ADD/UNASSIGN MEDS)
# ==============================================================================
else:
    st.subheader("📦 Bin-Filling Mode")
    st.caption("Select a storage locator first, then manage medications inside it.")

    # Location Input & Prefixes
    if "bin_location" not in st.session_state:
        st.session_state.bin_location = ""

    def apply_bin_prefix(prefix):
        curr = st.session_state.bin_location.upper()
        known = ["A1.SH.", "A1.DR.", "A1.PL.", "CR.FR."]
        for p in known:
            if curr.startswith(p):
                curr = curr[len(p):]
                break
        st.session_state.bin_location = prefix + curr

    st.write("**Quick Prefixes for Target Bin:**")
    bp_cols = st.columns(4)
    bp_cols[0].button("A1.SH.", on_click=apply_bin_prefix, args=("A1.SH.",), key="bp1", use_container_width=True)
    bp_cols[1].button("A1.DR.", on_click=apply_bin_prefix, args=("A1.DR.",), key="bp2", use_container_width=True)
    bp_cols[2].button("A1.PL.", on_click=apply_bin_prefix, args=("A1.PL.",), key="bp3", use_container_width=True)
    bp_cols[3].button("CR.FR.", on_click=apply_bin_prefix, args=("CR.FR.",), key="bp4", use_container_width=True)

    raw_bin_location = st.text_input(
        "Active Location / Bin Locator:",
        key="bin_location",
        placeholder="e.g., A1.SH.A.01 or A1SHA01"
    ).strip().upper()

    target_location = fix_location_format(raw_bin_location)

    if not target_location:
        st.info("👆 Please enter or select a location above to begin adding meds.")
    else:
        if raw_bin_location != target_location:
            st.info(f"📍 Active Bin (Auto-Formatted): **{target_location}**")
        else:
            st.success(f"📍 Active Bin: **{target_location}**")
            
        st.markdown("---")

        # Quick Add Input by 4 Digits (auto-capitalized)
        st.write("### Add Medication to Bin")
        digit_input = st.text_input(
            "Enter Last 4 Digits of Item Code:", 
            max_chars=10, 
            key="digit_search_input"
        ).strip().upper()

        # Find matching items by last 4 digits
        matched_items = []
        if digit_input:
            matched_items = [
                itm for itm in items 
                if itm["item_code"].endswith(digit_input) or digit_input in itm["item_code"]
            ]

        if digit_input and not matched_items:
            st.error(f"No medication found matching code containing '{digit_input}'")
        elif matched_items:
            st.write(f"**Found {len(matched_items)} match(es):**")
            for m in matched_items:
                m_code = m["item_code"]
                m_desc = m["description"]
                m_curr_loc = m["locations"][0] if m["locations"] else "None"
                
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.write(f"**{m_desc}**")
                    st.caption(f"Code: `{m_code}` | Current Location: `{m_curr_loc}`")
                with c2:
                    if st.button("➕ Assign", key=f"assign_{m_code}", type="primary", use_container_width=True):
                        row_idx = m["row_indices"][0]
                        sheet.update_cell(row_idx, 5, target_location)
                        st.toast(f"Assigned {m_code} to {target_location}!", icon="✅")
                        st.cache_data.clear()
                        st.rerun()

        # Display all items currently in this bin with Unassign feature
        st.markdown("---")
        st.write(f"### 📋 Medications currently in `{target_location}`:")
        current_bin_items = [itm for itm in items if target_location in itm["locations"]]

        if not current_bin_items:
            st.caption("No medications are assigned to this location yet.")
        else:
            for idx, b_item in enumerate(current_bin_items, start=1):
                col_info, col_unassign = st.columns([3, 1])
                with col_info:
                    st.write(f"{idx}. **{b_item['description']}**")
                    st.caption(f"Code: `{b_item['item_code']}`")
                with col_unassign:
                    if st.button("❌ Unassign", key=f"unassign_{b_item['item_code']}_{idx}", use_container_width=True):
                        row_idx = b_item["row_indices"][0]
                        sheet.update_cell(row_idx, 5, "")
                        st.toast(f"Unassigned {b_item['item_code']} from {target_location}", icon="🗑️")
                        st.cache_data.clear()
                        st.rerun()