# Individual sign-in for the mobile app

The mobile app uses Firebase Authentication email/password accounts. The local
`store_apps_user_management.py` utility creates and manages those accounts.
This setup applies to the Streamlit mobile app only.

## One-time Firebase setup

1. In Firebase Console, select the project for the mobile app and enable
   **Authentication → Sign-in method → Email/Password**.
2. Disable public account creation in the app's user flow. Accounts are created
   by the local manager, not by anonymous visitors.
3. Copy the Firebase project's Web API key and project ID.
4. Create two service accounts. Give the local account manager the
   **Firebase Authentication Admin** role (`roles/firebaseauth.admin`). Give
   the hosted app a separate account with the read-only **Firebase
   Authentication Viewer** role (`roles/firebaseauth.viewer`). The hosted app
   only needs to validate accounts and check their access; it should not hold
   the account-management key. Store both JSON keys outside this project and
   outside GitHub.
5. In Streamlit Community Cloud **Manage app → Settings → Secrets**, retain the
   existing `[gcp_service_account]` section and add the Firebase web API key,
   project ID, and the hosted app's read-only service-account values:

   ```toml
   [firebase]
   web_api_key = "YOUR_FIREBASE_WEB_API_KEY"
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

   Keep the existing Google Sheets credentials intact. Use the local admin key
   only when running the user manager. Never commit Firebase private keys or
   passwords to GitHub.

## Manage storekeeper accounts locally

Install dependencies once from this folder:

```powershell
py -m pip install -r requirements.txt
```

Run the account manager:

```powershell
py store_apps_user_management.py
```

It asks for the local Firebase Admin service-account JSON path at startup and
does not save that path. It can create accounts, list access, reset passwords, grant
or remove mobile app access, disable or enable accounts, and delete accounts.
Newly created accounts are granted access to this mobile app. Passwords are
prompted without echoing them to the screen.
