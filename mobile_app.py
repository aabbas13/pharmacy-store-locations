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
    SHEET_NAME = "HMC MCP Store Locations" # Ensure exact name
    sheet = gc.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {e}")
    st.stop()

@st.cache_data(ttl=30)
def load_data():
    records = sheet.get_all_records()
    items_dict = {}

    for row_idx, row in enumerate(records, start=2):
        code = str(row.get('Item Code', '')).strip()
        desc = str(row.get('Item Description', '')).strip()
        uom = str(row.get('UOM', '')).strip()
        sub_inv = str(row.get('Sub Inventory', '')).strip()
        loc = str(row.get('Location', '')).strip()

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

if "current_index" not in st.session_state:
    st.session_state.current_index = 0

if not items:
    st.warning("No item records found in Google Sheet.")
    st.stop()

current_item = items[st.session_state.current_index]

# Initialize input field in session_state if changing item
input_key = f"loc_input_{st.session_state.current_index}"
if input_key not in st.session_state:
    initial_val = current_item["locations"][0] if current_item["locations"] else ""
    st.session_state[input_key] = initial_val

# Helper to prepend or replace prefix in session_state
def apply_prefix(prefix):
    curr_text = st.session_state.get(input_key, "")
    # If text already starts with a recognized prefix, swap it out
    known_prefixes = ["A1.SH.", "A1.DR.", "A1.PL.", "CR.FR."]
    for p in known_prefixes:
        if curr_text.startswith(p):
            curr_text = curr_text[len(p):]
            break
    st.session_state[input_key] = prefix + curr_text

# UI Header
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

# Prefix Quick Insert Buttons using On-Click Callbacks
st.write("**Quick Prefixes:**")
prefix_cols = st.columns(4)
prefix_cols[0].button("A1.SH.", on_click=apply_prefix, args=("A1.SH.",), use_container_width=True)
prefix_cols[1].button("A1.DR.", on_click=apply_prefix, args=("A1.DR.",), use_container_width=True)
prefix_cols[2].button("A1.PL.", on_click=apply_prefix, args=("A1.PL.",), use_container_width=True)
prefix_cols[3].button("CR.FR.", on_click=apply_prefix, args=("CR.FR.",), use_container_width=True)

# Location Input Box linked to session_state
new_location = st.text_input("Location 1", key=input_key).strip().upper()

st.markdown("---")
btn_col1, btn_col2 = st.columns(2)

if btn_col1.button("⬅️ Previous", use_container_width=True):
    if st.session_state.current_index > 0:
        st.session_state.current_index -= 1
        st.rerun()

if btn_col2.button("Save & Next ➡️", type="primary", use_container_width=True):
    row_idx = current_item["row_indices"][0]
    sheet.update_cell(row_idx, 5, new_location) # Column 5 = Location
    
    st.toast(f"Saved: {new_location}", icon="✅")
    
    st.cache_data.clear()
    if st.session_state.current_index < len(items) - 1:
        st.session_state.current_index += 1
        st.rerun()
    else:
        st.success("All items completed!")