import json
import os
import re
import urllib.parse
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- PERSISTENT STATE HELPER ---
STATE_FILE = ".last_state.json"

def load_persistent_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_persistent_state(data: dict):
    try:
        current = load_persistent_state()
        current.update(data)
        with open(STATE_FILE, "w") as f:
            json.dump(current, f)
    except Exception:
        pass

persisted_data = load_persistent_state()

# --- PAGE CONFIG & STYLING ---
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

st.markdown("""
<style>
    .block-container { 
        padding-top: 3.5rem !important; 
        padding-bottom: 1rem !important; 
    }
    div[role="radiogroup"] {
        background-color: #f0f2f6;
        padding: 4px;
        border-radius: 8px;
        display: flex;
        justify-content: space-around;
        margin-bottom: 10px;
    }
    input {
        text-transform: uppercase;
    }
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
    spreadsheet = gc.open(SHEET_NAME)
    sheet = spreadsheet.sheet1
    sheet_url = spreadsheet.url
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
        desc = str(row.get('Item Description', '')).strip().upper()
        uom = str(row.get('UOM', '')).strip().upper()
        sub_inv = str(row.get('Sub Inventory', '')).strip().upper()
        raw_loc = str(row.get('Location', '')).strip().upper()

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

# --- INITIALIZE GLOBAL NAVIGATION STATE ---
if "current_index" not in st.session_state:
    st.session_state.current_index = persisted_data.get("last_item_index", 0)

default_mode = persisted_data.get("app_mode", "🔍 Item Search")

col_mode, col_sheet_btn = st.columns([3, 1])

with col_mode:
    app_mode = st.radio(
        "Select Mode",
        options=["🔍 Item Search", "📦 Bin Filling"],
        index=0 if default_mode == "🔍 Item Search" else 1,
        horizontal=True,
        key="global_app_mode_toggle",
        label_visibility="collapsed"
    )

with col_sheet_btn:
    st.link_button("📂 Open Sheet", sheet_url, use_container_width=True)

save_persistent_state({"app_mode": app_mode})

st.divider()

# ==============================================================================
# MODE 1: ITEM SEARCH MODE
# ==============================================================================
if app_mode == "🔍 Item Search":
    st.subheader("🔍 Item Search")
    
    raw_search = st.text_input(
        "Search Medicine (Type 4 digits or Name)",
        key="search_term_input",
        placeholder="E.G. 1234 OR PARACETAMOL"
    )
    search_term = raw_search.strip().upper()

    if search_term:
        if len(search_term) == 4 and search_term.isdigit():
            matched_items = [itm for itm in items if itm["item_code"].endswith(search_term)]
        else:
            matched_items = [
                itm for itm in items 
                if search_term in itm["item_code"] or search_term in itm["description"]
            ]
    else:
        matched_items = items

    item_options = {}
    for idx, itm in enumerate(matched_items):
        code = itm["item_code"]
        desc = itm["description"]
        last_4 = code[-4:] if len(code) >= 4 else code
        label = f"[{last_4}] {code} — {desc}"
        item_options[label] = items.index(itm)

    if not item_options:
        st.warning("No matching items found.")
    else:
        def on_dropdown_select():
            selected_str = st.session_state.search_dropdown
            if selected_str in item_options:
                st.session_state.current_index = item_options[selected_str]
                save_persistent_state({"last_item_index": st.session_state.current_index})

        st.session_state.current_index = max(0, min(st.session_state.current_index, len(items) - 1))

        current_item_obj = items[st.session_state.current_index]
        current_label = next((lbl for lbl, idx in item_options.items() if idx == st.session_state.current_index), list(item_options.keys())[0])
        dropdown_idx = list(item_options.keys()).index(current_label)

        st.selectbox(
            "Select Item Result",
            options=list(item_options.keys()),
            index=dropdown_idx,
            key="search_dropdown",
            on_change=on_dropdown_select
        )

    current_item = items[st.session_state.current_index]
    save_persistent_state({"last_item_index": st.session_state.current_index})

    st.caption(f"Item {st.session_state.current_index + 1} of {len(items)} | Code: `{current_item['item_code']}` | UOM: `{current_item['uom']}`")
    st.subheader(current_item["description"])

    current_locations = current_item["locations"]
    if current_locations:
        st.write("### 📍 Registered Locations:")
        for loc_idx, loc_val in enumerate(current_locations):
            c_loc, c_del = st.columns([4, 1])
            c_loc.info(f"`{loc_val}`")
            if c_del.button("❌", key=f"del_{st.session_state.current_index}_{loc_idx}"):
                updated_locs = [l for l in current_locations if l != loc_val]
                cell_text = "\n".join(updated_locs)
                sheet.update_cell(current_item["row_indices"][0], 5, cell_text)
                st.toast(f"Removed {loc_val}!", icon="🗑️")
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("No locations assigned to this item yet.")

    st.divider()
    st.write("### ➕ Add New Location")

    col_a, col_t, col_s1, col_s2 = st.columns(4)
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
        "Final Location Code", 
        value=generated_location, 
        key=f"item_loc_input_{st.session_state.current_index}"
    ).strip().upper()

    fixed_location = fix_location_format(target_loc_input)

    if c_btn.button("Add Location", type="primary", use_container_width=True):
        if not fixed_location:
            st.warning("Invalid Location Format.")
        elif fixed_location in current_locations:
            st.warning("Location already assigned.")
        else:
            updated_locs = current_locations + [fixed_location]
            sheet.update_cell(current_item["row_indices"][0], 5, "\n".join(updated_locs))
            st.toast(f"Added {fixed_location}!", icon="✅")
            st.cache_data.clear()
            st.rerun()

    st.divider()
    
    def prev_item():
        if st.session_state.current_index > 0:
            st.session_state.current_index -= 1
            save_persistent_state({"last_item_index": st.session_state.current_index})

    def next_item():
        if st.session_state.current_index < len(items) - 1:
            st.session_state.current_index += 1
            save_persistent_state({"last_item_index": st.session_state.current_index})

    b_prev, b_next = st.columns(2)
    b_prev.button("⬅️ Previous Item", use_container_width=True, on_click=prev_item, disabled=(st.session_state.current_index <= 0))
    b_next.button("Next Item ➡️", use_container_width=True, on_click=next_item, disabled=(st.session_state.current_index >= len(items) - 1))

# ==============================================================================
# MODE 2: BIN FILLING MODE
# ==============================================================================
else:
    st.subheader("📦 Bin Filling Mode")

    p_bin = persisted_data.get("last_bin_parts", {"area": "A1", "type": "DR", "sig1": "", "sig2": ""})
    p_bounds = persisted_data.get("vertical_bounds", {"start": "AA", "max": "AO"})

    # Direct integration to widget keys to avoid variable mismatch
    if "bin_area_in" not in st.session_state:
        st.session_state.bin_area_in = p_bin.get("area", "A1")
    if "bin_type_in" not in st.session_state:
        st.session_state.bin_type_in = p_bin.get("type", "DR")
    if "bin_sig1_in" not in st.session_state:
        st.session_state.bin_sig1_in = p_bin.get("sig1", "")
    if "bin_sig2_in" not in st.session_state:
        st.session_state.bin_sig2_in = p_bin.get("sig2", "")
    if "focus_item_search" not in st.session_state:
        st.session_state.focus_item_search = False

    with st.expander("⚙️ Vertical Navigation Bounds", expanded=False):
        c_conf1, c_conf2 = st.columns(2)
        start_row = c_conf1.text_input("Start Row (Top)", value=p_bounds.get("start", "AA")).strip().upper()
        max_row = c_conf2.text_input("Max Row (Bottom)", value=p_bounds.get("max", "AO")).strip().upper()
        # Save these bounds for the next session
        save_persistent_state({"vertical_bounds": {"start": start_row, "max": max_row}})

    col_a, col_t, col_s1, col_s2 = st.columns(4)

    in_area = col_a.text_input("Area*", key="bin_area_in").strip().upper()
    in_type = col_t.text_input("Type*", key="bin_type_in").strip().upper()
    in_sig1 = col_s1.text_input("Sigma 3 (Row)*", key="bin_sig1_in").strip().upper()
    in_sig2 = col_s2.text_input("Sigma 4 (Col#)*", key="bin_sig2_in").strip().upper()

    all_fields_filled = all([in_area, in_type, in_sig1, in_sig2])

    if all_fields_filled:
        if in_type == "FR":
            active_bin_gen = f"{in_area}.{in_sig1}.01.{in_sig2}"
        else:
            active_bin_gen = f"{in_area}.{in_type}.{in_sig1}.{in_sig2}"
        target_bin_location = fix_location_format(active_bin_gen)
        save_persistent_state({
            "last_bin_parts": {"area": in_area, "type": in_type, "sig1": in_sig1, "sig2": in_sig2},
            "last_bin_location": target_bin_location
        })
        st.success(f"📍 Active Target Bin: **`{target_bin_location}`**")
    else:
        target_bin_location = ""
        st.warning("⚠️ Please complete all location fields (Area, Type, Sigma 3, Sigma 4).")

    def advance_vertical():
        curr_row = st.session_state.bin_sig1_in.strip().upper()
        curr_col = st.session_state.bin_sig2_in.strip()
        
        # If we have reached the defined maximum row, wrap around to next column
        if curr_row == max_row:
            st.session_state.bin_sig1_in = start_row
            try:
                curr_num = int(curr_col)
                st.session_state.bin_sig2_in = f"{curr_num + 1:02d}"
            except ValueError:
                pass # Keep as is if not a number
        else:
            # Increment row downwards
            if len(curr_row) == 2:
                first_char, second_char = curr_row[0], curr_row[1]
                if second_char < 'Z':
                    next_row = first_char + chr(ord(second_char) + 1)
                else:
                    next_row = chr(ord(first_char) + 1) + 'A'
                st.session_state.bin_sig1_in = next_row
            elif len(curr_row) == 1:
                st.session_state.bin_sig1_in = chr(ord(curr_row) + 1)
                
        # Always refocus the item search box after navigating
        st.session_state.focus_item_search = True

    if all_fields_filled:
        st.button("⬇️ Next Vertical Location (Row ↓, then Col →)", use_container_width=True, on_click=advance_vertical)

    st.divider()

    if "last_assigned_item" not in st.session_state:
        st.session_state.last_assigned_item = persisted_data.get("last_assigned_item_data", None)

    def execute_assignment(target_item):
        if target_bin_location not in target_item["locations"]:
            updated = target_item["locations"] + [target_bin_location]
            sheet.update_cell(target_item["row_indices"][0], 5, "\n".join(updated))
            st.toast(f"Assigned {target_item['item_code']} to {target_bin_location}!", icon="✅")
            st.cache_data.clear()
            st.session_state.last_assigned_item = target_item
            save_persistent_state({"last_assigned_item_data": target_item})
            st.session_state["bin_digit_srch"] = ""

    def handle_search_and_assign():
        val = st.session_state.get("bin_digit_srch", "").strip().upper()
        if val:
            st.session_state.last_assigned_item = None

        if val and target_bin_location:
            if len(val) == 4 and val.isdigit():
                matches = [i for i in items if i["item_code"].endswith(val)]
            else:
                matches = [i for i in items if val in i["item_code"] or val in i["description"]]
            
            if len(matches) == 1:
                execute_assignment(matches[0])
            elif len(matches) == 0 and len(val) == 4 and val.isdigit():
                st.toast(f"Item '{val}' not available in formulary!", icon="❌")
                st.session_state["bin_digit_srch"] = ""
                st.session_state.focus_item_search = True

    st.text_input(
        "Search Item to Assign (Type 4 digits or Name)",
        placeholder="E.G. 1234 OR PARACETAMOL",
        key="bin_digit_srch",
        on_change=handle_search_and_assign,
        disabled=not all_fields_filled
    )

    should_focus = "true" if st.session_state.focus_item_search else "false"
    js_code = f"""
    <!DOCTYPE html>
    <html>
      <body style="margin:0;padding:0;">
        <script>
          const shouldFocus = {should_focus};
          if (shouldFocus) {{
              const doc = window.parent.document;
              setTimeout(() => {{
                  const inputs = doc.querySelectorAll('input[type="text"]');
                  inputs.forEach(input => {{
                      if (input.placeholder && input.placeholder.includes("E.G. 1234")) {{
                          input.focus();
                          input.select();
                      }}
                  }});
              }}, 150);
          }}
        </script>
      </body>
    </html>
    """
    data_url = f"data:text/html;charset=utf-8,{urllib.parse.quote(js_code)}"
    st.iframe(src=data_url, height=1)
    st.session_state.focus_item_search = False

    search_val = st.session_state.get("bin_digit_srch", "").strip().upper()
    if search_val:
        if len(search_val) == 4 and search_val.isdigit():
            matched_items = [itm for itm in items if itm["item_code"].endswith(search_val)]
        else:
            matched_items = [itm for itm in items if search_val in itm["item_code"] or search_val in itm["description"]]
        
        if matched_items and all_fields_filled:
            for m in matched_items:
                m_code = m["item_code"]
                m_desc = m["description"]
                m_locs = m["locations"]
                
                cm1, cm2 = st.columns([3, 1])
                cm1.write(f"**{m_desc}** (`{m_code}`)")
                if cm2.button("➕ Assign", key=f"bin_assign_{m_code}", type="primary"):
                    execute_assignment(m)
                    st.rerun()

    if st.session_state.last_assigned_item and not search_val:
        last_item = st.session_state.last_assigned_item
        st.info(f"✅ **Last Assigned Item:** {last_item['description']} (`{last_item['item_code']}`) — UOM: `{last_item['uom']}`")

    st.divider()
    if all_fields_filled:
        st.write(f"### 📋 Items currently in `{target_bin_location}`:")
        current_bin_items = [itm for itm in items if target_bin_location in itm["locations"]]

        if not current_bin_items:
            st.info("No items assigned to this bin yet.")
        else:
            for idx, b_item in enumerate(current_bin_items, start=1):
                cb_info, cb_del = st.columns([4, 1])
                cb_info.write(f"**{idx}.** {b_item['description']} (`{b_item['item_code']}`)")
                if cb_del.button("❌", key=f"bin_unassign_{b_item['item_code']}_{idx}"):
                    updated_locs = [l for l in b_item["locations"] if l != target_bin_location]
                    sheet.update_cell(b_item["row_indices"][0], 5, "\n".join(updated_locs))
                    st.toast(f"Unassigned {b_item['item_code']}", icon="🗑️")
                    st.cache_data.clear()
                    st.rerun()