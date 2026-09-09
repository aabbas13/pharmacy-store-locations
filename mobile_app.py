from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets Setup
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = "credentials.json"
SHEET_NAME = "HMC MCP Store Locations"

def get_sheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def load_data_and_locations():
    sheet = get_sheet()
    records = sheet.get_all_records()
    items_dict = {}
    all_locations = set()
    
    for row_idx, row in enumerate(records, start=2): # Row 2 accounts for headers
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

def update_item_locations(row_indices, locations_list):
    sheet = get_sheet()
    
    # Update cells corresponding to Column E (Location column)
    cells_to_update = []
    for i, row_idx in enumerate(row_indices):
        loc_val = locations_list[i] if i < len(locations_list) else ""
        cells_to_update.append(gspread.Cell(row=row_idx, col=5, value=loc_val))
        
    if len(locations_list) > len(row_indices):
        extra_locs = ", ".join(locations_list[len(row_indices)-1:])
        cells_to_update.append(gspread.Cell(row=row_indices[-1], col=5, value=extra_locs))
        
    sheet.update_cells(cells_to_update)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Cloud Oracle Store Location Editor</title>
    <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: #f4f6f9; margin: 0; padding: 16px; color: #333; }
        .card { background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); margin-bottom: 16px; }
        .progress { font-size: 14px; color: #666; font-weight: 600; text-align: center; margin-bottom: 12px; }
        .badge { display: inline-block; background: #eef2ff; color: #4f46e5; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .title { font-size: 18px; font-weight: 700; margin: 12px 0 8px 0; color: #111; line-height: 1.3; }
        .detail-row { display: flex; justify-content: space-between; margin: 8px 0; font-size: 14px; border-bottom: 1px solid #f0f0f0; padding-bottom: 6px; }
        .label { color: #777; }
        .value { font-weight: 600; }
        .loc-header { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; }
        label { font-weight: 700; font-size: 14px; color: #444; }
        .add-btn { background: #e0e7ff; color: #4338ca; border: none; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 13px; cursor: pointer; }
        .quick-tags { display: flex; gap: 6px; margin-top: 8px; overflow-x: auto; padding-bottom: 4px; }
        .tag-btn { background: #f1f5f9; border: 1px solid #cbd5e1; color: #334155; font-size: 12px; font-weight: 600; padding: 4px 8px; border-radius: 6px; cursor: pointer; white-space: nowrap; }
        .loc-input-wrap { display: flex; gap: 8px; margin-top: 8px; }
        input[type="text"] { flex: 1; padding: 14px; font-size: 16px; border: 2px solid #e2e8f0; border-radius: 10px; outline: none; text-transform: uppercase; }
        input[type="text"]:focus { border-color: #4f46e5; }
        .remove-btn { background: #fee2e2; color: #dc2626; border: none; border-radius: 10px; padding: 0 14px; font-weight: bold; }
        .btn-group { display: flex; gap: 10px; margin-top: 24px; }
        button.action { flex: 1; padding: 16px; font-size: 16px; font-weight: 700; border: none; border-radius: 12px; cursor: pointer; }
        .btn-prev { background: #e2e8f0; color: #475569; }
        .btn-next { background: #4f46e5; color: white; }
    </style>
</head>
<body>
    <div class="progress" id="progress">Loading Cloud Data...</div>
    <div class="card">
        <span class="badge" id="subInv">-</span>
        <div class="title" id="itemDesc">Item Description</div>
        <div class="detail-row"><span class="label">Item Code:</span><span class="value" id="itemCode">-</span></div>
        <div class="detail-row"><span class="label">UOM:</span><span class="value" id="uom">-</span></div>
        
        <div class="loc-header">
            <label>Oracle Locators:</label>
            <button class="add-btn" onclick="addLocationInput('')">+ Add Location</button>
        </div>
        
        <div class="quick-tags">
            <span style="font-size: 11px; align-self: center; color: #888;">Prefix:</span>
            <button class="tag-btn" onclick="insertPrefix('A1.SH.')">A1.SH.</button>
            <button class="tag-btn" onclick="insertPrefix('A1.DR.')">A1.DR.</button>
            <button class="tag-btn" onclick="insertPrefix('A1.PL.')">A1.PL.</button>
            <button class="tag-btn" onclick="insertPrefix('CR.FR.')">CR.FR.</button>
        </div>

        <div id="locationsContainer"></div>
        <datalist id="existingLocations"></datalist>

        <div class="btn-group">
            <button class="action btn-prev" onclick="navigate(-1)">Previous</button>
            <button class="action btn-next" onclick="saveAndNext()">Save & Next</button>
        </div>
    </div>

    <script>
        let items = [];
        let globalLocations = [];
        let currentIndex = 0;
        let activeInput = null;

        async function loadData() {
            const res = await fetch('/api/items');
            const data = await res.json();
            items = data.items;
            globalLocations = data.locations;
            
            updateDatalist();
            render();
        }

        function updateDatalist() {
            const datalist = document.getElementById('existingLocations');
            datalist.innerHTML = '';
            globalLocations.forEach(loc => {
                const opt = document.createElement('option');
                opt.value = loc;
                datalist.appendChild(opt);
            });
        }

        function render() {
            if (items.length === 0) return;
            const item = items[currentIndex];
            document.getElementById('progress').innerText = `Medication ${currentIndex + 1} of ${items.length}`;
            document.getElementById('itemDesc').innerText = item.description;
            document.getElementById('itemCode').innerText = item.item_code;
            document.getElementById('uom').innerText = item.uom;
            document.getElementById('subInv').innerText = item.sub_inv;
            
            const container = document.getElementById('locationsContainer');
            container.innerHTML = '';
            
            const locs = item.locations.length > 0 ? item.locations : [''];
            locs.forEach(loc => addLocationInput(loc));
        }

        function addLocationInput(value = '') {
            const container = document.getElementById('locationsContainer');
            const wrap = document.createElement('div');
            wrap.className = 'loc-input-wrap';
            
            const input = document.createElement('input');
            input.type = 'text';
            input.value = value;
            input.placeholder = 'e.g., A1.SH.A.01';
            input.className = 'loc-field';
            input.setAttribute('list', 'existingLocations');
            
            input.onfocus = () => { activeInput = input; };
            
            const removeBtn = document.createElement('button');
            removeBtn.className = 'remove-btn';
            removeBtn.innerText = '✕';
            removeBtn.onclick = () => {
                if (container.children.length > 1) wrap.remove();
            };
            
            wrap.appendChild(input);
            wrap.appendChild(removeBtn);
            container.appendChild(wrap);
            input.focus();
            activeInput = input;
        }

        function insertPrefix(prefix) {
            if (activeInput) {
                if (!activeInput.value.startsWith(prefix)) {
                    activeInput.value = prefix + activeInput.value;
                }
                activeInput.focus();
            }
        }

        async function saveAndNext() {
            const inputs = document.querySelectorAll('.loc-field');
            const locations = Array.from(inputs).map(i => i.value.trim().toUpperCase()).filter(i => i !== '');
            
            items[currentIndex].locations = locations;

            locations.forEach(loc => {
                if (!globalLocations.includes(loc)) globalLocations.push(loc);
            });
            updateDatalist();

            await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    row_indices: items[currentIndex].row_indices, 
                    locations: locations 
                })
            });

            if (currentIndex < items.length - 1) {
                currentIndex++;
                render();
            } else {
                alert('All items completed!');
            }
        }

        function navigate(direction) {
            if (currentIndex + direction >= 0 && currentIndex + direction < items.length) {
                currentIndex += direction;
                render();
            }
        }

        loadData();
    </script>
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/items":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            items, locations = load_data_and_locations()
            self.wfile.write(json.dumps({"items": items, "locations": locations}).encode("utf-8"))

    def do_POST(self):
        if self.path == "/api/save":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))
            
            update_item_locations(payload['row_indices'], payload['locations'])
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8000), RequestHandler)
    print("Google Sheets Cloud App running at http://localhost:8000")
    server.serve_forever()