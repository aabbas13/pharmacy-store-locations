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
    /* Extra highlight for every button in the app */
    .stButton > button, .stLinkButton > a, .stDownloadButton > button {
        border: 2px solid #1F4E78 !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        box-shadow: 0 2px 6px rgba(31, 78, 120, 0.30) !important;
        transition: all 0.15s ease-in-out !important;
    }
    .stButton > button:hover, .stLinkButton > a:hover, .stDownloadButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(31, 78, 120, 0.45) !important;
        border-color: #FF4B4B !important;
        color: #FF4B4B !important;
    }
    .stButton > button[kind="primary"] {
        box-shadow: 0 2px 10px rgba(255, 75, 75, 0.45) !important;
        border-color: #FF4B4B !important;
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

    if not matched_items:
        st.warning("No matching items found.")
    elif search_term:
        # Searching: resolve directly instead of using a dropdown, since a
        # selectbox whose option list changes every keystroke can desync
        # from the selected value in Streamlit (clicking an option doesn't
        # always register). A single match jumps straight in; multiple
        # matches get a plain click-to-select list.
        matched_indices = [items.index(itm) for itm in matched_items]
        if len(matched_items) == 1:
            if st.session_state.current_index != matched_indices[0]:
                st.session_state.current_index = matched_indices[0]
                save_persistent_state({"last_item_index": st.session_state.current_index})
        else:
            if st.session_state.current_index not in matched_indices:
                st.session_state.current_index = matched_indices[0]
                save_persistent_state({"last_item_index": st.session_state.current_index})
            st.caption(f"{len(matched_items)} matches — tap one to view:")
            for itm in matched_items:
                idx = items.index(itm)
                label = f"[{itm['item_code'][-4:]}] {itm['item_code']} — {itm['description']}"
                is_selected = (idx == st.session_state.current_index)
                if st.button(
                    ("✅ " if is_selected else "") + label,
                    key=f"searchsel_{idx}",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                ):
                    st.session_state.current_index = idx
                    save_persistent_state({"last_item_index": idx})
                    st.rerun()
    else:
        # Browsing with no search term: a static full list, so the plain
        # dropdown is fine here (its options don't change every keystroke).
        item_options = {}
        for itm in matched_items:
            code = itm["item_code"]
            desc = itm["description"]
            last_4 = code[-4:] if len(code) >= 4 else code
            label = f"[{last_4}] {code} — {desc}"
            item_options[label] = items.index(itm)

        def on_dropdown_select():
            selected_str = st.session_state.search_dropdown
            if selected_str in item_options:
                st.session_state.current_index = item_options[selected_str]
                save_persistent_state({"last_item_index": st.session_state.current_index})

        st.session_state.current_index = max(0, min(st.session_state.current_index, len(items) - 1))
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

    with st.expander("📍 Locations", expanded=False):
        current_locations = current_item["locations"]
        if current_locations:
            st.write("#### Registered Locations:")
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
        st.write("#### ➕ Add New Location")

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
    p_bounds = persisted_data.get("vertical_bounds", {"start": "AA", "max": "AO", "max_col": "30"})

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

    with st.expander("📍 Manual Location Input", expanded=False):
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
        else:
            target_bin_location = ""

        st.markdown("**⚙️ Row / Column Settings**")
        c_conf1, c_conf2, c_conf3 = st.columns(3)
        start_row = c_conf1.text_input(
            "Start Row (Top)",
            value=p_bounds.get("start", "AA"),
            help="Defines the row FORMAT. E.g. 'AA' = 2-char alphabetical (prefix 'A' fixed, row identifier is the 2nd letter, starting at 'A'). 'A' = 1-char alphabetical. '01' = 2-digit numeric."
        ).strip().upper()
        max_row = c_conf2.text_input(
            "Max Row (Bottom)",
            value=p_bounds.get("max", "AO")).strip().upper()
        max_col_raw = c_conf3.text_input(
            "Max Column",
            value=p_bounds.get("max_col", "30"),
            help="Once Sigma 4 (Col#) passes this number, it wraps back to 01."
        ).strip()
        st.caption("Max Row can be the full row (e.g. 'AO') or just the row identifier (e.g. 'O'). Only the row identifier (the last character/digits) is used as the limit — the prefix is never auto-incremented.")
        try:
            max_col_val = int(max_col_raw)
            if max_col_val < 1:
                max_col_val = 30
        except ValueError:
            max_col_val = 30
        # Save these bounds for the next session
        save_persistent_state({"vertical_bounds": {"start": start_row, "max": max_row, "max_col": max_col_raw}})

        def get_row_format(fmt_start_row: str, fmt_max_row: str) -> dict:
            """
            The Starting Row defines the FORMAT of the row (numeric vs alphabetical,
            and whether there's a fixed prefix). The row identifier that actually
            increments is always the LAST character/digit(s):
              - "AA" -> prefix "A" (fixed, never auto-increments), identifier "A".."Z"
              - "A"  -> no prefix, identifier "A".."Z"
              - "01" -> no prefix, numeric identifier, 2-digit zero padded
            Max Row may be given as the full row (e.g. "AO") or just the identifier
            (e.g. "O") - only its last character/digits are used as the limit.
            """
            if fmt_start_row.isdigit():
                pad_len = len(fmt_start_row)
                start_val = int(fmt_start_row)
                digits = ''.join(ch for ch in fmt_max_row if ch.isdigit())
                max_val = int(digits) if digits else start_val
                return {"numeric": True, "pad_len": pad_len, "start_val": start_val, "max_val": max_val}
            else:
                prefix = fmt_start_row[:-1] if len(fmt_start_row) >= 2 else ""
                start_char = fmt_start_row[-1] if fmt_start_row else "A"
                max_char = fmt_max_row[-1] if fmt_max_row else start_char
                return {"numeric": False, "prefix": prefix, "start_char": start_char, "max_char": max_char}

        def advance_vertical():
            curr_row = st.session_state.bin_sig1_in.strip().upper()
            curr_col = st.session_state.bin_sig2_in.strip()
            fmt = get_row_format(start_row, max_row)

            bump_col = False

            if fmt["numeric"]:
                try:
                    curr_val = int(curr_row)
                except ValueError:
                    curr_val = fmt["start_val"]

                if curr_val >= fmt["max_val"]:
                    new_row = str(fmt["start_val"]).zfill(fmt["pad_len"])
                    bump_col = True
                else:
                    new_row = str(curr_val + 1).zfill(fmt["pad_len"])
            else:
                # The prefix (if any) is fixed and preserved as-is; only the last
                # character (the row identifier) ever increments or wraps.
                if len(curr_row) >= 2:
                    curr_prefix, curr_char = curr_row[:-1], curr_row[-1]
                else:
                    curr_prefix, curr_char = "", (curr_row or fmt["start_char"])

                if curr_char >= fmt["max_char"]:
                    new_row = curr_prefix + fmt["start_char"]
                    bump_col = True
                else:
                    new_row = curr_prefix + chr(ord(curr_char) + 1)

            st.session_state.bin_sig1_in = new_row

            # If we wrapped past the max row, advance to the next column,
            # wrapping the column back to 01 once it passes Max Column
            if bump_col:
                try:
                    curr_num = int(curr_col)
                    next_num = curr_num + 1
                    if next_num > max_col_val:
                        next_num = 1
                    st.session_state.bin_sig2_in = f"{next_num:02d}"
                except ValueError:
                    pass  # Keep as is if not a number

            # Always refocus the item search box after navigating
            st.session_state.focus_item_search = True

        def retreat_vertical():
            curr_row = st.session_state.bin_sig1_in.strip().upper()
            curr_col = st.session_state.bin_sig2_in.strip()
            fmt = get_row_format(start_row, max_row)

            drop_col = False

            if fmt["numeric"]:
                try:
                    curr_val = int(curr_row)
                except ValueError:
                    curr_val = fmt["start_val"]

                if curr_val <= fmt["start_val"]:
                    new_row = str(fmt["max_val"]).zfill(fmt["pad_len"])
                    drop_col = True
                else:
                    new_row = str(curr_val - 1).zfill(fmt["pad_len"])
            else:
                if len(curr_row) >= 2:
                    curr_prefix, curr_char = curr_row[:-1], curr_row[-1]
                else:
                    curr_prefix, curr_char = "", (curr_row or fmt["start_char"])

                if curr_char <= fmt["start_char"]:
                    new_row = curr_prefix + fmt["max_char"]
                    drop_col = True
                else:
                    new_row = curr_prefix + chr(ord(curr_char) - 1)

            st.session_state.bin_sig1_in = new_row

            # If we wrapped below the start row, step back to the previous
            # column, wrapping to Max Column once it drops below 01
            if drop_col:
                try:
                    curr_num = int(curr_col)
                    prev_num = curr_num - 1
                    if prev_num < 1:
                        prev_num = max_col_val
                    st.session_state.bin_sig2_in = f"{prev_num:02d}"
                except ValueError:
                    pass  # Keep as is if not a number

            # Always refocus the item search box after navigating
            st.session_state.focus_item_search = True

        row_fmt_info = get_row_format(start_row, max_row)

    if all_fields_filled:
        st.success(f"📍 Active Target Bin: **`{target_bin_location}`**")
    else:
        st.warning("⚠️ Please complete all location fields (Area, Type, Sigma 3, Sigma 4).")

    if row_fmt_info["numeric"]:
        _pad = row_fmt_info["pad_len"]
        row_def_caption = (
            f"Numeric row, {_pad}-digit, from `{str(row_fmt_info['start_val']).zfill(_pad)}` "
            f"to `{str(row_fmt_info['max_val']).zfill(_pad)}`."
        )
    else:
        _prefix_part = f"prefix `{row_fmt_info['prefix']}` fixed, " if row_fmt_info["prefix"] else ""
        row_def_caption = (
            f"{_prefix_part}row identifier `{row_fmt_info['start_char']}`–`{row_fmt_info['max_char']}` "
            f"(wraps back to `{row_fmt_info['start_char']}` and bumps the column after `{row_fmt_info['max_char']}`)."
        )
    st.caption(f"📏 **Max Row:** `{max_row}` — {row_def_caption} **Max Column:** `{max_col_val:02d}`.")

    if all_fields_filled:
        b_prevloc, b_nextloc = st.columns(2)
        b_prevloc.button("⬆️ Previous Vertical Location", use_container_width=True, on_click=retreat_vertical)
        b_nextloc.button("⬇️ Next Vertical Location", use_container_width=True, on_click=advance_vertical)

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