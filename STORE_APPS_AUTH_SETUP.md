# Store Apps accounts and sign-in

The HTML helper and Streamlit mobile app use the same Firebase Authentication
project. `store_apps_user_management.py` is a separate local administrator tool;
it does not merge the two apps or change their data sources.

## Firebase setup

1. Create a Firebase project for these apps.
2. In **Authentication → Sign-in method**, enable **Email/Password**.
3. In Firebase Authentication settings, disable end-user account creation and
   deletion. The local manager should be the only way to create accounts.
4. Add a Web app in Firebase project settings. Copy its `apiKey`, `projectId`,
   and `appId` into `STORE_APPS_FIREBASE_CONFIG` near the top of the HTML file.
   Replace the same placeholders in `docs/index.html` before publishing.
5. Create a Firebase service-account key with Firebase Authentication Admin
   permissions for the local manager. Keep the JSON file outside this synced
   folder and outside GitHub.
6. Add Firebase settings to Streamlit Community Cloud Secrets. Keep the
   existing `[gcp_service_account]` section as well:

   ```toml
   [firebase]
   web_api_key = "YOUR_WEB_API_KEY"
   project_id = "YOUR_FIREBASE_PROJECT_ID"

   [firebase_admin]
   type = "service_account"
   project_id = "YOUR_FIREBASE_PROJECT_ID"
   private_key_id = "YOUR_PRIVATE_KEY_ID"
   private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_KEY\n-----END PRIVATE KEY-----\n"
   client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
   client_id = "YOUR_CLIENT_ID"
   token_uri = "https://oauth2.googleapis.com/token"
   ```

   Use a separate service account for the hosted mobile app with only the
   permissions needed to verify users. Do not put the local manager's admin
   key in the GitHub repository.

## Run the local user manager

Install dependencies once:

```powershell
py -m pip install -r requirements.txt
```

Then, from this folder:

```powershell
py store_apps_user_management.py
```

The tool asks for the path to the Firebase Admin service-account JSON and
does not save that path. It can add accounts, list accounts and their app
permissions, change access to either app, reset passwords, enable or disable
accounts, and delete accounts. Accounts use email and password. New users do
not get access to either app until permissions are assigned.

## Access behavior

Firebase custom claims control access independently:

- `mobile_app`: access to `mobile_app.py`
- `picking_helper`: access to the HTML helper

When an access change is made, the manager revokes refresh tokens; users must
sign in again for the change to apply. The Streamlit app verifies revocation on
each run. The HTML helper reads the authenticated user's claim before showing
its interface. GitHub Pages still publishes static files publicly; this
client-side gate controls normal app use but cannot conceal the source HTML.
