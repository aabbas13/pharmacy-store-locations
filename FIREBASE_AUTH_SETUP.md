# Individual sign-in for the mobile app

The mobile app uses Firebase Authentication email/password accounts. The local
`store_apps_user_management.py` utility creates and manages those accounts.
This setup applies to the Streamlit mobile app only.

## One-time Firebase setup

1. In Firebase Console, select the project for the mobile app and enable
   **Authentication → Sign-in method → Email/Password**.
2. The app has no public registration flow. Create accounts from its
   administrator-only user-management page or the local manager.
3. Copy the Firebase project's Web API key and project ID.
4. Create separate service accounts for the local manager and the hosted app.
   Both need the **Firebase Authentication Admin** role
   (`roles/firebaseauth.admin`) because the in-app management page creates
   accounts, resets passwords, and changes access. Keep the local manager key
   outside this project and GitHub. The hosted key belongs only in Streamlit
   Secrets; never expose it to the browser or commit it to GitHub.
5. In Streamlit Community Cloud **Manage app → Settings → Secrets**, retain the
   existing `[gcp_service_account]` section and add the Firebase web API key,
   project ID, and the hosted app's service-account values:

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

   Keep the existing Google Sheets credentials intact. The hosted Admin SDK
   key grants user-management privileges across this Firebase project's user
   accounts, so keep the Firebase project dedicated to this app and protect
   access to the Streamlit app's settings. Never commit private keys or
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

Use the manager's **Grant in-app user-management administrator** action for
the administrator account that should open the login page's **User
management** button. The admin claim cannot be granted from the web page.
