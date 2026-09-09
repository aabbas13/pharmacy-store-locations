import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# Set up page config for mobile views
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_gspread_client():
    # Read credentials from Streamlit Secrets in Cloud
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    else:
        st.error("Missing [gcp_service_account] in Streamlit Secrets!")
        st.stop()

# Initialize Google Sheet
try:
    gc = get_gspread_client()
    # Replace with the EXACT title of your Google Sheet
    SHEET_NAME = "HMC MCP Store Locations" 
    sheet = gc.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {e}")
    st.stop()

# Load Data
@st.cache_data(ttl=60)
def load_data():
    records = sheet.get_all_records()
    items_dict = {}
    all_locations = set()

    for row_idx, row in enumerate(records, start=2): # Start at row 2 (row 1 is headers)
        code = str(row.get('Item Code', ''))
        desc = str(row.get('Item Description', ''))
        uom = str(row.get('UOM', ''))
        sub_inv = str(row.get('Sub Inventory', ''))
        loc = str(row.get('Location', '')).strip()

        if loc:
            all_locations.add(loc)

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

    return list(items_dict.values()), sorted(list(all_locations))

items, global_locations = load_data()

# Navigation state
if "current_index" not in st.session_state:
    st.session_state.current_index = 0

if not items:
    st.warning("No item records found in Google Sheet.")
    st.stop()

current_item = items[st.session_state.current_index]

# UI Layout
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

# Prefix Quick Insert Buttons
st.write("**Quick Prefixes:**")
prefix_cols = st.columns(4)
selected_prefix = ""
if prefix_cols[0].button("A1.SH."): selected_prefix = "A1.SH."
if prefix_cols[1].button("A1.DR."): selected_prefix = "A1.DR."
if prefix_cols[2].button("A1.PL."): selected_prefix = "A1.PL."
if prefix_cols[3].button("CR.FR."): selected_prefix = "CR.FR."

# Location Inputs
existing_loc = current_item["locations"][0] if current_item["locations"] else ""
if selected_prefix and not existing_loc.startswith(selected_prefix):
    existing_loc = selected_prefix + existing_loc

new_location = st.text_input("Location 1", value=existing_loc, key=f"loc_{st.session_state.current_index}").strip().upper()

# Navigation & Save Controls
st.markdown("---")
btn_col1, btn_col2 = st.columns(2)

if btn_col1.button("⬅️ Previous", use_container_width=True):
    if st.session_state.current_index > 0:
        st.session_state.current_index -= 1
        st.rerun()

if btn_col2.button("Save & Next ➡️", type="primary", use_container_width=True):
    # Update Google Sheet
    row_idx = current_item["row_indices"][0]
    sheet.update_cell(row_idx, 5, new_location) # Column 5 = Location
    
    st.toast("Updated Google Sheet successfully!", icon="✅")
    
    # Clear cache and move to next
    st.cache_data.clear()
    if st.session_state.current_index < len(items) - 1:
        st.session_state.current_index += 1
        st.rerun()
    else:
        st.success("All items completed!")