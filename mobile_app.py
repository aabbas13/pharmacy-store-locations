import json
import html
import requests
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
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


def load_device_bin_settings(device_id: str) -> dict:
    """Load bin setup from a file unique to this browser profile."""
    path = os.path.join(".device_settings", f"bin_{device_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as state_file:
            settings = json.load(state_file)
            return settings if isinstance(settings, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_device_bin_settings(device_id: str, settings: dict):
    """Save this browser's bin setup without overwriting other devices."""
    directory = ".device_settings"
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"bin_{device_id}.json")
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as state_file:
            json.dump(settings, state_file)
        os.replace(temp_path, path)
    except OSError:
        try:
            os.remove(temp_path)
        except OSError:
            pass


persisted_data = load_persistent_state()

# --- PAGE CONFIG & STYLING ---
st.set_page_config(page_title="Pharmacy Store Locations", layout="centered")

# Keep Firebase's refresh token in this browser tab so a page reload can restore
# the signed-in session. Passwords and ID tokens are never written to storage.
AUTH_SESSION_COMPONENT = st.components.v2.component(
    name="store_auth_session_persistence",
    html="<span></span>",
    js="""
      export default function({ data, setStateValue }) {
        const key = "store-locations-firebase-session";
        let saved = {};
        try {
          if (data?.clear) {
            window.sessionStorage.removeItem(key);
          } else if (data?.refresh_token) {
            saved = {
              refresh_token: data.refresh_token,
              email: data.email || "",
              role: data.role || "store"
            };
            window.sessionStorage.setItem(key, JSON.stringify(saved));
          } else {
            saved = JSON.parse(window.sessionStorage.getItem(key) || "{}");
          }
        } catch (error) {
          saved = {};
        }
        setStateValue("ready", true);
        setStateValue("refresh_token", saved.refresh_token || "");
        setStateValue("email", saved.email || "");
        setStateValue("role", saved.role || "store");
      }
    """,
)


# --- INDIVIDUAL FIREBASE AUTHENTICATION ---
def firebase_settings():
    try:
        return (
            str(st.secrets["firebase"]["web_api_key"]),
            str(st.secrets["firebase"]["project_id"]),
            dict(st.secrets["firebase_admin"]),
        )
    except (KeyError, TypeError):
        st.error(
            "Firebase sign-in is not configured. Add the [firebase] and "
            "[firebase_admin] sections to Streamlit Cloud Secrets."
        )
        st.stop()


@st.cache_resource
def get_firebase_admin_app():
    _, project_id, service_account = firebase_settings()
    try:
        return firebase_admin.get_app("store_locations_auth")
    except ValueError:
        credential = firebase_credentials.Certificate(service_account)
        return firebase_admin.initialize_app(
            credential,
            options={"projectId": project_id},
            name="store_locations_auth",
        )


def firebase_sign_in(email: str, password: str) -> dict:
    web_api_key, _, _ = firebase_settings()
    response = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
        params={"key": web_api_key},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def refresh_firebase_id_token(refresh_token: str) -> dict:
    web_api_key, _, _ = firebase_settings()
    response = requests.post(
        "https://securetoken.googleapis.com/v1/token",
        params={"key": web_api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def firebase_update_password(id_token: str, new_password: str) -> dict:
    web_api_key, _, _ = firebase_settings()
    response = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:update",
        params={"key": web_api_key},
        json={"idToken": id_token, "password": new_password, "returnSecureToken": True},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def queue_password_change(result: dict, email: str) -> None:
    st.session_state["password_change_id_token"] = result["idToken"]
    st.session_state["password_change_refresh_token"] = result["refreshToken"]
    st.session_state["password_change_email"] = email


def restore_browser_auth_session() -> None:
    clear_requested = bool(st.session_state.pop("_clear_browser_auth", False))
    if clear_requested:
        auth_data = {"clear": True}
    elif st.session_state.get("password_change_refresh_token"):
        auth_data = {
            "refresh_token": st.session_state["password_change_refresh_token"],
            "email": st.session_state.get("password_change_email", ""),
            "role": "password_change",
        }
    elif st.session_state.get("store_admin_refresh_token"):
        auth_data = {
            "refresh_token": st.session_state["store_admin_refresh_token"],
            "email": st.session_state.get("store_admin_email", ""),
            "role": "admin",
        }
    else:
        auth_data = {
            "refresh_token": st.session_state.get("store_locations_refresh_token", ""),
            "email": st.session_state.get("store_locations_email", ""),
            "role": "store",
        }

    browser_auth = AUTH_SESSION_COMPONENT(
        data=auth_data,
        default={"ready": False, "refresh_token": "", "email": "", "role": "store"},
        key="store_auth_session",
        height=1,
        width="stretch",
    )
    if clear_requested:
        clear_firebase_session()
        return

    if not getattr(browser_auth, "ready", False):
        st.info("Restoring your sign-in…")
        st.stop()

    if any(st.session_state.get(key) for key in (
        "password_change_id_token",
        "store_admin_id_token",
        "store_locations_id_token",
    )):
        return

    refresh_token = getattr(browser_auth, "refresh_token", "")
    role = getattr(browser_auth, "role", "store")
    email = getattr(browser_auth, "email", "")
    if not refresh_token:
        return

    try:
        refreshed = refresh_firebase_id_token(refresh_token)
        app = get_firebase_admin_app()
        decoded = firebase_auth.verify_id_token(
            refreshed["id_token"], check_revoked=True, app=app
        )
        if role == "password_change" and decoded.get("must_change_password", False):
            queue_password_change(refreshed, decoded.get("email", email))
            st.rerun()
        elif role == "admin" and decoded.get("store_admin", False):
            st.session_state["store_admin_id_token"] = refreshed["id_token"]
            st.session_state["store_admin_refresh_token"] = refreshed.get(
                "refresh_token", refresh_token
            )
            st.session_state["store_admin_email"] = decoded.get("email", email)
            st.session_state.pop("show_user_management_login", None)
            st.rerun()
        elif role == "store" and decoded.get("mobile_app", False):
            st.session_state["store_locations_id_token"] = refreshed["id_token"]
            st.session_state["store_locations_refresh_token"] = refreshed.get(
                "refresh_token", refresh_token
            )
            st.session_state["store_locations_email"] = decoded.get("email", email)
            st.rerun()
        else:
            st.session_state["_clear_browser_auth"] = True
    except (
        requests.RequestException,
        KeyError,
        ValueError,
        firebase_admin.exceptions.FirebaseError,
    ):
        st.session_state["_clear_browser_auth"] = True


def show_required_password_change() -> bool:
    token = st.session_state.get("password_change_id_token")
    if not token:
        return False

    st.title("🔑 Change your temporary password")
    st.info("Choose a new password before using either Store Apps application.")
    with st.form("required_first_login_password_change"):
        new_password = st.text_input(
            "New password (at least 8 characters)", type="password", autocomplete="new-password"
        )
        confirm_password = st.text_input(
            "Confirm new password", type="password", autocomplete="new-password"
        )
        submitted = st.form_submit_button(
            "Change password", type="primary", use_container_width=True
        )

    if submitted:
        if new_password != confirm_password:
            st.error("The passwords do not match.")
        elif len(new_password) < 8:
            st.error("Use a password with at least 8 characters.")
        else:
            try:
                updated = firebase_update_password(token, new_password)
                app = get_firebase_admin_app()
                decoded = firebase_auth.verify_id_token(
                    updated["idToken"], check_revoked=False, app=app
                )
                user = firebase_auth.get_user(decoded["uid"], app=app)
                claims = dict(user.custom_claims or {})
                claims.pop("must_change_password", None)
                firebase_auth.set_custom_user_claims(user.uid, claims, app=app)
                firebase_auth.revoke_refresh_tokens(user.uid, app=app)
                for key in (
                    "password_change_id_token",
                    "password_change_refresh_token",
                    "password_change_email",
                    "store_locations_id_token",
                    "store_locations_refresh_token",
                    "store_locations_email",
                    "store_admin_id_token",
                    "store_admin_refresh_token",
                    "store_admin_email",
                ):
                    st.session_state.pop(key, None)
                st.session_state["_clear_browser_auth"] = True
                st.session_state["password_changed_notice"] = True
                st.rerun()
            except (
                requests.RequestException,
                KeyError,
                ValueError,
                firebase_admin.exceptions.FirebaseError,
            ):
                st.error("Could not change the password. Sign in again or contact the administrator.")

    if st.button("Cancel and sign out", use_container_width=True):
        for key in (
            "password_change_id_token",
            "password_change_refresh_token",
            "password_change_email",
        ):
            st.session_state.pop(key, None)
        st.rerun()
    st.stop()
    return True


def clear_firebase_session() -> None:
    for key in (
        "store_locations_id_token",
        "store_locations_refresh_token",
        "store_locations_email",
    ):
        st.session_state.pop(key, None)


def show_firebase_login(message: str = "") -> None:
    st.title("🔐 Store Locations Sign In")
    if message:
        st.info(message)
    with st.form("store_locations_login_form"):
        email = st.text_input("Email", autocomplete="username")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password"
        )
        submitted = st.form_submit_button(
            "Sign in", type="primary", use_container_width=True
        )
    if not submitted:
        if st.button("User management", use_container_width=True):
            st.session_state["show_user_management_login"] = True
            st.rerun()
        return

    try:
        result = firebase_sign_in(email.strip(), password)
        app = get_firebase_admin_app()
        decoded = firebase_auth.verify_id_token(
            result["idToken"], check_revoked=True, app=app
        )
        if decoded.get("must_change_password", False):
            queue_password_change(result, decoded.get("email", email.strip()))
            st.rerun()
        if not decoded.get("mobile_app", False):
            st.error("This account is not enabled for the mobile app. Contact the administrator.")
            return
        st.session_state["store_locations_id_token"] = result["idToken"]
        st.session_state["store_locations_refresh_token"] = result["refreshToken"]
        st.session_state["store_locations_email"] = decoded.get("email", email.strip())
        st.rerun()
    except (
        requests.RequestException,
        KeyError,
        ValueError,
        firebase_admin.exceptions.FirebaseError,
    ):
        st.error("Sign-in failed. Check your email and password, or contact the administrator.")


def show_user_management_login() -> None:
    st.title("🔐 Administrator Sign In")
    st.caption("Only an account with user-management administrator access can continue.")
    with st.form("store_locations_admin_login_form"):
        email = st.text_input("Administrator email", autocomplete="username")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password"
        )
        submitted = st.form_submit_button(
            "Open user management", type="primary", use_container_width=True
        )
    if submitted:
        try:
            result = firebase_sign_in(email.strip(), password)
            decoded = firebase_auth.verify_id_token(
                result["idToken"], check_revoked=True, app=get_firebase_admin_app()
            )
            if decoded.get("must_change_password", False):
                queue_password_change(result, decoded.get("email", email.strip()))
                st.rerun()
            if not decoded.get("store_admin", False):
                st.error("This account is not an administrator.")
            else:
                st.session_state["store_admin_id_token"] = result["idToken"]
                st.session_state["store_admin_refresh_token"] = result["refreshToken"]
                st.session_state["store_admin_email"] = decoded.get("email", email.strip())
                st.session_state.pop("show_user_management_login", None)
                st.rerun()
        except (
            requests.RequestException,
            KeyError,
            ValueError,
            firebase_admin.exceptions.FirebaseError,
        ):
            st.error("Sign-in failed. Check your credentials or contact the administrator.")

    if st.button("Back to storekeeper sign in", use_container_width=True):
        st.session_state.pop("show_user_management_login", None)
        st.rerun()


def load_firebase_users(app):
    users = []
    page = firebase_auth.list_users(app=app)
    while page:
        users.extend(page.users)
        page = page.get_next_page()
    return sorted(users, key=lambda user: (user.email or "").lower())


def set_user_app_access(user, claim: str, enabled: bool, app) -> None:
    claims = dict(user.custom_claims or {})
    claims[claim] = enabled
    firebase_auth.set_custom_user_claims(user.uid, claims, app=app)
    firebase_auth.revoke_refresh_tokens(user.uid, app=app)


def render_user_management() -> None:
    app = get_firebase_admin_app()
    decoded = None
    token = st.session_state.get("store_admin_id_token")
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=True, app=app)
    except firebase_auth.ExpiredIdTokenError:
        try:
            refreshed = refresh_firebase_id_token(
                st.session_state["store_admin_refresh_token"]
            )
            decoded = firebase_auth.verify_id_token(
                refreshed["id_token"], check_revoked=True, app=app
            )
            st.session_state["store_admin_id_token"] = refreshed["id_token"]
            if refreshed.get("refresh_token"):
                st.session_state["store_admin_refresh_token"] = refreshed["refresh_token"]
        except (
            requests.RequestException,
            KeyError,
            firebase_admin.exceptions.FirebaseError,
        ):
            decoded = None
    except firebase_admin.exceptions.FirebaseError:
        decoded = None

    if not decoded or not decoded.get("store_admin", False):
        st.session_state.pop("store_admin_id_token", None)
        st.session_state.pop("store_admin_refresh_token", None)
        st.session_state.pop("store_admin_email", None)
        st.session_state["show_user_management_login"] = True
        st.rerun()

    st.title("👥 Store Location User Management")
    st.caption(f"Administrator: {st.session_state.get('store_admin_email', '')}")
    col_signout, col_back = st.columns(2)
    if col_signout.button("Sign out", use_container_width=True):
        for key in ("store_admin_id_token", "store_admin_refresh_token", "store_admin_email"):
            st.session_state.pop(key, None)
        st.session_state.pop("show_user_management_login", None)
        st.session_state["_clear_browser_auth"] = True
        st.rerun()
    if col_back.button("Back to app sign in", use_container_width=True):
        for key in ("store_admin_id_token", "store_admin_refresh_token", "store_admin_email"):
            st.session_state.pop(key, None)
        st.session_state["_clear_browser_auth"] = True
        st.rerun()

    st.subheader("Add a storekeeper")
    with st.form("create_storekeeper_form"):
        email = st.text_input("Email address", key="new_storekeeper_email")
        display_name = st.text_input("Name", key="new_storekeeper_name")
        password = st.text_input(
            "Temporary password (at least 8 characters)",
            type="password",
            key="new_storekeeper_password",
        )
        confirm_password = st.text_input(
            "Confirm temporary password",
            type="password",
            key="new_storekeeper_password_confirm",
        )
        app_access_choice = st.selectbox(
            "App access",
            ["Both apps", "Store mobile app only", "Picker HTML only", "No app access"],
            key="new_storekeeper_app_access",
        )
        create_submitted = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )
    if create_submitted:
        if password != confirm_password:
            st.error("The passwords do not match.")
        elif len(password) < 8:
            st.error("Use a password with at least 8 characters.")
        else:
            try:
                user = firebase_auth.create_user(
                    email=email.strip(),
                    password=password,
                    display_name=display_name.strip() or None,
                    app=app,
                )
                claims = dict(user.custom_claims or {})
                claims["mobile_app"] = app_access_choice in ("Both apps", "Store mobile app only")
                claims["picking_helper"] = app_access_choice in ("Both apps", "Picker HTML only")
                claims["must_change_password"] = app_access_choice != "No app access"
                firebase_auth.set_custom_user_claims(user.uid, claims, app=app)
                st.success(f"Created {user.email} with {app_access_choice.lower()} access.")
                st.rerun()
            except (ValueError, firebase_admin.exceptions.FirebaseError) as exc:
                st.error(f"Could not create the account: {exc}")

    st.subheader("Existing accounts")
    try:
        users = load_firebase_users(app)
    except firebase_admin.exceptions.FirebaseError:
        st.error("Could not load Firebase accounts. Check the app's Firebase Admin permissions.")
        return
    if not users:
        st.info("No accounts found.")
        return

    st.dataframe(
        [
            {
                "Email": user.email or "",
                "Name": user.display_name or "",
                "Status": "Disabled" if user.disabled else "Active",
                "Mobile app access": "Yes" if (user.custom_claims or {}).get("mobile_app") else "No",
                "Picker HTML access": "Yes" if (user.custom_claims or {}).get("picking_helper") else "No",
                "Administrator": "Yes" if (user.custom_claims or {}).get("store_admin") else "No",
            }
            for user in users
        ],
        use_container_width=True,
        hide_index=True,
    )

    eligible_users = [user for user in users if not (user.custom_claims or {}).get("store_admin")]
    if not eligible_users:
        st.info("There are no non-administrator accounts to manage.")
        return

    st.subheader("Manage an account")
    selected_email = st.selectbox(
        "Storekeeper account",
        [user.email for user in eligible_users],
        key="managed_storekeeper_email",
    )
    selected_user = next(user for user in eligible_users if user.email == selected_email)
    c_mobile, c_picker, c_status = st.columns(3)
    claims = selected_user.custom_claims or {}
    has_mobile_access = bool(claims.get("mobile_app"))
    has_picker_access = bool(claims.get("picking_helper"))
    mobile_label = "Remove Store access" if has_mobile_access else "Grant Store access"
    picker_label = "Remove Picker access" if has_picker_access else "Grant Picker access"
    if c_mobile.button(mobile_label, use_container_width=True):
        try:
            set_user_app_access(selected_user, "mobile_app", not has_mobile_access, app)
            st.success(f"Updated Store app access for {selected_email}. They must sign in again.")
            st.rerun()
        except firebase_admin.exceptions.FirebaseError as exc:
            st.error(f"Could not update Store app access: {exc}")
    if c_picker.button(picker_label, use_container_width=True):
        try:
            set_user_app_access(selected_user, "picking_helper", not has_picker_access, app)
            st.success(f"Updated Picker access for {selected_email}. They must sign in again.")
            st.rerun()
        except firebase_admin.exceptions.FirebaseError as exc:
            st.error(f"Could not update Picker access: {exc}")

    if selected_user.disabled:
        if c_status.button("Enable account", use_container_width=True):
            try:
                firebase_auth.update_user(selected_user.uid, disabled=False, app=app)
                st.success(f"Enabled {selected_email}.")
                st.rerun()
            except firebase_admin.exceptions.FirebaseError as exc:
                st.error(f"Could not enable the account: {exc}")
    elif c_status.button("Disable account", use_container_width=True):
        try:
            firebase_auth.update_user(selected_user.uid, disabled=True, app=app)
            firebase_auth.revoke_refresh_tokens(selected_user.uid, app=app)
            st.success(f"Disabled {selected_email}; existing sessions were revoked.")
            st.rerun()
        except firebase_admin.exceptions.FirebaseError as exc:
            st.error(f"Could not disable the account: {exc}")

    with st.form("reset_storekeeper_password_form"):
        new_password = st.text_input(
            "New password (at least 8 characters)", type="password"
        )
        new_password_confirm = st.text_input("Confirm new password", type="password")
        reset_submitted = st.form_submit_button("Reset password", use_container_width=True)
    if reset_submitted:
        if new_password != new_password_confirm:
            st.error("The passwords do not match.")
        elif len(new_password) < 8:
            st.error("Use a password with at least 8 characters.")
        else:
            try:
                firebase_auth.update_user(
                    selected_user.uid, password=new_password, app=app
                )
                claims = dict(selected_user.custom_claims or {})
                claims['must_change_password'] = True
                firebase_auth.set_custom_user_claims(selected_user.uid, claims, app=app)
                firebase_auth.revoke_refresh_tokens(selected_user.uid, app=app)
                st.success(f"Password reset for {selected_email}; they must change it at next sign-in.")
            except firebase_admin.exceptions.FirebaseError as exc:
                st.error(f"Could not reset the password: {exc}")


def route_user_management() -> bool:
    if st.session_state.get("show_user_management_login") and not st.session_state.get(
        "store_admin_id_token"
    ):
        show_user_management_login()
        st.stop()
    if not st.session_state.get("store_admin_id_token"):
        return False
    render_user_management()
    st.stop()
    return True


def require_firebase_user() -> None:
    token = st.session_state.get("store_locations_id_token")
    if not token:
        show_firebase_login()
        st.stop()

    try:
        app = get_firebase_admin_app()
        decoded = firebase_auth.verify_id_token(token, check_revoked=True, app=app)
    except firebase_auth.ExpiredIdTokenError:
        try:
            refreshed = refresh_firebase_id_token(
                st.session_state["store_locations_refresh_token"]
            )
            decoded = firebase_auth.verify_id_token(
                refreshed["id_token"], check_revoked=True, app=get_firebase_admin_app()
            )
            st.session_state["store_locations_id_token"] = refreshed["id_token"]
            if refreshed.get("refresh_token"):
                st.session_state["store_locations_refresh_token"] = refreshed["refresh_token"]
        except (
            requests.RequestException,
            KeyError,
            firebase_admin.exceptions.FirebaseError,
        ):
            clear_firebase_session()
            show_firebase_login("Your sign-in expired. Please sign in again.")
            st.stop()
    except firebase_admin.exceptions.FirebaseError:
        clear_firebase_session()
        show_firebase_login("Your access is no longer active. Please sign in again.")
        st.stop()

    if not decoded.get("mobile_app", False):
        clear_firebase_session()
        st.title("🔐 Store Locations Sign In")
        st.error("This account is not enabled for the mobile app. Contact the administrator.")
        st.stop()


restore_browser_auth_session()

if show_required_password_change():
    st.stop()
if not route_user_management():
    require_firebase_user()
    st.sidebar.caption(f"Signed in: {st.session_state.get('store_locations_email', '')}")
    if st.sidebar.button("Sign out", key="store_locations_sign_out"):
        clear_firebase_session()
        st.session_state["_clear_browser_auth"] = True
        st.rerun()

# Give each browser profile a stable, separate settings key. Streamlit v2
# state sends the browser ID directly to Python without a page reload.
DEVICE_ID_COMPONENT = st.components.v2.component(
    name="store_device_identity",
    html="<span></span>",
    js="""
      export default function({ setStateValue }) {
        const storageKey = 'store-location-manager-device-id';
        const makeDeviceId = () => window.crypto && crypto.randomUUID ? crypto.randomUUID() :
          'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
          });
        let browserId;
        try {
          browserId = localStorage.getItem(storageKey);
          if (!browserId) browserId = makeDeviceId();
          localStorage.setItem(storageKey, browserId);
        } catch (error) {
          try {
            browserId = sessionStorage.getItem(storageKey);
            if (!browserId) browserId = makeDeviceId();
            sessionStorage.setItem(storageKey, browserId);
          } catch (storageError) {
            browserId = window.__storeLocationDeviceId || makeDeviceId();
            window.__storeLocationDeviceId = browserId;
          }
        }
        setStateValue("device_id", browserId);

        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete("device_id");
        cleanUrl.searchParams.delete("device_ready");
        if (cleanUrl.href !== window.location.href) {
          window.history.replaceState(window.history.state, "", cleanUrl.toString());
        }
      }
    """,
)
device_state = DEVICE_ID_COMPONENT(key="store_device_identity", height=1, width="stretch")
device_id = getattr(device_state, "device_id", None)
if not isinstance(device_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", device_id):
    st.info("Preparing this device’s settings…")
    st.stop()


BIN_LOCATION_COMPONENT = st.components.v2.component(
    name="store_bin_location_input",
    html='<label for="bin-location-input">Bin location*</label><input id="bin-location-input" type="text" autocomplete="off" autocapitalize="characters" placeholder="XX.XX.XX.XXXX"><small>Format: XX.XX.XX.XXXX — dots are added automatically.</small>',
    css="""
      label { display: block; margin-bottom: 0.35rem; color: var(--st-text-color); font: 600 .9rem var(--st-font); }
      input { box-sizing: border-box; width: 100%; min-height: 44px; padding: .55rem .7rem; border: 1px solid var(--st-border-color); border-radius: .5rem; background: var(--st-background-color); color: var(--st-text-color); font: 1rem var(--st-font); }
      input:focus { outline: 2px solid var(--st-primary-color); outline-offset: 1px; }
      small { display: block; margin-top: .35rem; color: var(--st-text-color); opacity: .72; font: .82rem var(--st-font); }
    """,
    js="""
      export default function({ parentElement, data, setStateValue }) {
        const input = parentElement.querySelector("#bin-location-input");
        const format = (value) => {
          const raw = String(value || "").replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 10);
          return [raw.slice(0, 2), raw.slice(2, 4), raw.slice(4, 6), raw.slice(6, 10)]
            .filter(Boolean).join(".");
        };
        if (input.value !== (data?.value || "")) input.value = data?.value || "";

        const handleInput = () => {
          const caret = input.selectionStart ?? input.value.length;
          const rawBeforeCaret = input.value.slice(0, caret).replace(/[^a-z0-9]/gi, "").length;
          const formatted = format(input.value);
          const charsBeforeCaret = Math.min(rawBeforeCaret, formatted.split(".").join("").length);
          const dotsBeforeCaret = Math.min(3, Math.floor(charsBeforeCaret / 2));
          input.value = formatted;
          const nextCaret = Math.min(formatted.length, charsBeforeCaret + dotsBeforeCaret);
          input.setSelectionRange(nextCaret, nextCaret);
          setStateValue("value", formatted);
        };
        input.addEventListener("input", handleInput);
        return () => input.removeEventListener("input", handleInput);
      }
    """,
)


VOICE_COMPONENT = st.components.v2.component(
    name="store_voice_command_control",
    html="""
      <div class="voice-control">
        <button id="voice-start" type="button">🎙️ Speak command</button>
        <span id="voice-status" aria-live="polite">Tap to speak one command.</span>
      </div>
    """,
    css="""
      .voice-control { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-family: sans-serif; }
      #voice-start { border: 2px solid #1F4E78; border-radius: 10px; padding: 10px 16px; font-weight: 700; background: #1F4E78; color: white; cursor: pointer; }
      #voice-start:disabled { opacity: .65; cursor: wait; }
      #voice-status { font-size: .9rem; color: #334155; }
    """,
    js="""
      export default function ({ parentElement, setTriggerValue }) {
        const button = parentElement.querySelector("#voice-start");
        const status = parentElement.querySelector("#voice-status");
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!Recognition) {
          button.disabled = true;
          status.textContent = "Voice input is not supported in this browser. Use the search field.";
          return;
        }

        const recognition = new Recognition();
        recognition.lang = "en-US";
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        let listening = false;
        const resetButton = () => {
          listening = false;
          button.textContent = "🎙️ Speak command";
          button.disabled = false;
        };

        button.addEventListener("click", () => {
          if (listening) {
            recognition.stop();
            return;
          }
          status.textContent = "Listening…";
          button.textContent = "⏹ Stop listening";
          listening = true;
          try {
            recognition.start();
          } catch (error) {
            resetButton();
            status.textContent = "Could not start voice input. Tap and try again.";
          }
        });

        recognition.onresult = (event) => {
          const transcript = Array.from(event.results)
            .map((result) => result[0].transcript)
            .join(" ")
            .trim();
          status.textContent = transcript ? "Heard: " + transcript : "No speech was recognized.";
          if (transcript) setTriggerValue("command", transcript);
        };
        recognition.onerror = (event) => {
          const messages = {
            "not-allowed": "Microphone access was denied. Allow microphone access in your browser settings.",
            "service-not-allowed": "Speech recognition is unavailable in this browser.",
            "no-speech": "No speech was detected. Tap and try again.",
            "network": "Speech recognition needs a working internet connection."
          };
          status.textContent = messages[event.error] || "Voice input stopped. Tap and try again.";
          resetButton();
        };
        recognition.onend = resetButton;

        return () => {
          try { recognition.abort(); } catch (error) {}
        };
      }
    """,
)

def show_voice_commands():
    result = VOICE_COMPONENT(
        key="store_voice_commands",
        height=58,
        width="stretch",
        on_command_change=lambda: None,
    )
    return getattr(result, "command", None)


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
    @media (max-width: 640px) {
        /* Keep the first controls below Streamlit's fixed mobile toolbar. */
        .block-container { padding: 4rem .65rem .65rem !important; }
        div[data-testid="stVerticalBlock"] { gap: .55rem; }
        .stCaption { line-height: 1.25; }
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
    if re.match(r"^[A-Z0-9]{2}\.[A-Z0-9]{2}\.[A-Z0-9]{1,2}\.[A-Z0-9]{1,4}$", cleaned):
        return cleaned
    raw_chars = re.sub(r'[^A-Z0-9]', '', cleaned)
    if len(raw_chars) == 7:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:5]}.{raw_chars[5:7]}"
    elif len(raw_chars) == 8:
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:6]}.{raw_chars[6:8]}"
    elif len(raw_chars) in (9, 10):
        return f"{raw_chars[0:2]}.{raw_chars[2:4]}.{raw_chars[4:6]}.{raw_chars[6:]}"
    return cleaned


def format_bin_location_input(value: str) -> str:
    """Insert dots after each two-character location part while typing."""
    raw = re.sub(r"[^A-Z0-9]", "", str(value).upper())[:10]
    parts = [raw[:2], raw[2:4], raw[4:6], raw[6:10]]
    return ".".join(part for part in parts if part)


def sync_bin_location_parts() -> None:
    """Normalize the full location field and keep navigation state in sync."""
    component_state = st.session_state.get("bin_location_component", {})
    typed_value = component_state.get("value", "") if isinstance(component_state, dict) else ""
    formatted = format_bin_location_input(typed_value)
    st.session_state.bin_location_in = formatted
    parts = formatted.split(".") if formatted else []
    parts += [""] * (4 - len(parts))

    area, second, third, fourth = parts[:4]
    current_type = st.session_state.get("bin_type_in", "DR").strip().upper()
    if second == "FR":
        bin_type, row, column = "FR", third, fourth
    elif current_type == "FR" and third == "01":
        bin_type, row, column = "FR", second, fourth
    else:
        bin_type, row, column = second, third, fourth

    st.session_state.bin_area_in = area
    st.session_state.bin_type_in = bin_type
    st.session_state.bin_sig1_in = row
    st.session_state.bin_sig2_in = column



SPOKEN_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9",
}
SPOKEN_LETTERS = {
    "ay": "a", "bee": "b", "cee": "c", "see": "c", "dee": "d",
    "are": "r", "ar": "r",
}
LOCATION_FILLER_WORDS = {
    "location", "bin", "area", "type", "row", "series", "section",
    "number", "code", "is", "please", "the",
}

def parse_voice_command(transcript: str) -> dict:
    words = re.findall(r"[a-z]+|[0-9]+", str(transcript).lower())
    tokens = [SPOKEN_DIGITS.get(word, SPOKEN_LETTERS.get(word, word)) for word in words]

    if any(word in {"next", "forward", "advance"} for word in tokens):
        return {"action": "next"}
    if any(word in {"previous", "prev", "back", "backward", "backwards"} for word in tokens):
        return {"action": "previous"}

    separators = {"in", "at", "to", "location", "bin"}
    separator_index = next((i for i, word in enumerate(tokens) if word in separators), None)
    item_tokens = tokens if separator_index is None else tokens[:separator_index]
    spoken_item_digits = "".join(ch for word in item_tokens for ch in word if ch.isdigit())
    suffix = spoken_item_digits[-4:] if len(spoken_item_digits) >= 4 else ""

    if len(suffix) != 4:
        return {"action": "invalid", "message": "Say an item’s last four digits, such as “4005”."}

    if separator_index is None:
        return {"action": "item", "suffix": suffix}

    location_tokens = tokens[separator_index + 1:]
    location_text = "".join(
        word for word in location_tokens
        if word not in LOCATION_FILLER_WORDS
    ).upper()
    location = fix_location_format(location_text)
    if not re.fullmatch(r"[A-Z0-9]{2}\.[A-Z0-9]{2}\.[A-Z0-9]{1,2}\.[A-Z0-9]{1,4}", location):
        return {
            "action": "invalid",
            "message": "I heard the item number, but not a valid location. Say, for example, “item 4005 in A1 DR CA 03”.",
        }
    return {"action": "assign", "suffix": suffix, "location": location}

def get_row_format(fmt_start_row: str, fmt_max_row: str) -> dict:
    """Return the numeric/alphabetic row bounds used by bin navigation."""
    if fmt_start_row.isdigit():
        pad_len = len(fmt_start_row)
        start_val = int(fmt_start_row)
        digits = "".join(ch for ch in fmt_max_row if ch.isdigit())
        max_val = int(digits) if digits else start_val
        return {"numeric": True, "pad_len": pad_len, "start_val": start_val, "max_val": max_val}
    prefix = fmt_start_row[:-1] if len(fmt_start_row) >= 2 else ""
    start_char = fmt_start_row[-1] if fmt_start_row else "A"
    max_char = fmt_max_row[-1] if fmt_max_row else start_char
    return {"numeric": False, "prefix": prefix, "start_char": start_char, "max_char": max_char}

def move_bin_vertical(direction: str, start_row: str, max_row: str, max_col_val: int) -> None:
    current_row = st.session_state.bin_sig1_in.strip().upper()
    current_col = st.session_state.bin_sig2_in.strip()
    fmt = get_row_format(start_row, max_row)
    wrap_column = False

    if direction == "next":
        if fmt["numeric"]:
            try:
                current_value = int(current_row)
            except ValueError:
                current_value = fmt["start_val"]
            if current_value >= fmt["max_val"]:
                new_row = str(fmt["start_val"]).zfill(fmt["pad_len"])
                wrap_column = True
            else:
                new_row = str(current_value + 1).zfill(fmt["pad_len"])
        else:
            if len(current_row) >= 2:
                prefix, current_char = current_row[:-1], current_row[-1]
            else:
                prefix, current_char = "", (current_row or fmt["start_char"])
            if current_char >= fmt["max_char"]:
                new_row = prefix + fmt["start_char"]
                wrap_column = True
            else:
                new_row = prefix + chr(ord(current_char) + 1)
    else:
        if fmt["numeric"]:
            try:
                current_value = int(current_row)
            except ValueError:
                current_value = fmt["start_val"]
            if current_value <= fmt["start_val"]:
                new_row = str(fmt["max_val"]).zfill(fmt["pad_len"])
                wrap_column = True
            else:
                new_row = str(current_value - 1).zfill(fmt["pad_len"])
        else:
            if len(current_row) >= 2:
                prefix, current_char = current_row[:-1], current_row[-1]
            else:
                prefix, current_char = "", (current_row or fmt["start_char"])
            if current_char <= fmt["start_char"]:
                new_row = prefix + fmt["max_char"]
                wrap_column = True
            else:
                new_row = prefix + chr(ord(current_char) - 1)

    st.session_state.bin_sig1_in = new_row
    if wrap_column:
        try:
            current_number = int(current_col)
            next_number = current_number + (1 if direction == "next" else -1)
            if next_number > max_col_val:
                next_number = 1
            if next_number < 1:
                next_number = max_col_val
            st.session_state.bin_sig2_in = f"{next_number:02d}"
        except ValueError:
            pass
    st.session_state.bin_location_in = format_bin_location_input(
        location_from_bin_parts(
            st.session_state.bin_area_in,
            st.session_state.bin_type_in,
            st.session_state.bin_sig1_in,
            st.session_state.bin_sig2_in,
        )
    )
    st.session_state.focus_item_search = True
    if "device_bin_settings" in globals() and "device_id" in globals():
        device_bin_settings["last_bin_parts"] = {
            "area": st.session_state.bin_area_in,
            "type": st.session_state.bin_type_in,
            "sig1": st.session_state.bin_sig1_in,
            "sig2": st.session_state.bin_sig2_in,
        }
        save_device_bin_settings(device_id, device_bin_settings)

def location_from_bin_parts(area: str, bin_type: str, row: str, column: str) -> str:
    if not all((area, bin_type, row, column)):
        return ""
    if bin_type == "FR":
        raw_location = f"{area}.{row}.01.{column}"
    else:
        raw_location = f"{area}.{bin_type}.{row}.{column}"
    return fix_location_format(raw_location)

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


@st.cache_data(ttl=60, max_entries=1)
def export_spreadsheet_copy(spreadsheet_id: str) -> bytes:
    """Return a short-lived Excel export of the complete Google workbook."""
    return gc.export(
        spreadsheet_id,
        format="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def assign_item_to_location(item: dict, location: str) -> str:
    if location in item["locations"]:
        return "exists"
    sheet.update_cell(item["row_indices"][0], 5, "\n".join(item["locations"] + [location]))
    st.cache_data.clear()
    st.session_state.last_assigned_item = item
    save_persistent_state({"last_assigned_item_data": item})
    return "assigned"


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
    try:
        sheet_copy = export_spreadsheet_copy(spreadsheet.id)
        st.download_button(
            "⬇️ Download copy",
            data=sheet_copy,
            file_name="HMC MCP Store Locations.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="Download a copy of the complete Google Sheets workbook as an Excel file.",
        )
    except Exception:
        st.error("Could not prepare the sheet copy. Please try again later.")

save_persistent_state({"app_mode": app_mode})

st.divider()

# ==============================================================================
# MODE 1: ITEM SEARCH MODE
# ==============================================================================
if app_mode == "🔍 Item Search":
    st.subheader("🔍 Item Search")
    st.caption("Voice examples: “4005” searches the item; “item 4005 in A1 DR CA 03” adds that location; say “next item” or “previous item” to browse.")
    spoken_command = show_voice_commands()
    if spoken_command:
        command = parse_voice_command(spoken_command)
        if command["action"] in {"next", "previous"}:
            step = 1 if command["action"] == "next" else -1
            new_index = max(0, min(len(items) - 1, st.session_state.current_index + step))
            if new_index == st.session_state.current_index:
                st.info("There are no more items in that direction.")
            else:
                st.session_state.current_index = new_index
                st.session_state["search_term_input"] = ""
                save_persistent_state({"last_item_index": new_index})
                st.toast("Moved to the next item." if step > 0 else "Moved to the previous item.")
        elif command["action"] == "invalid":
            st.warning(command["message"])
        elif command["action"] == "assign":
            st.session_state["search_term_input"] = ""
            matches = [itm for itm in items if itm["item_code"].endswith(command["suffix"])]
            if len(matches) == 1:
                item = matches[0]
                st.session_state.current_index = items.index(item)
                result = assign_item_to_location(item, command["location"])
                if result == "assigned":
                    st.toast(f"Added {command['location']} to item {item['item_code']}.", icon="✅")
                    save_persistent_state({"last_item_index": st.session_state.current_index})
                    st.rerun()
                else:
                    st.info(f"Item {item['item_code']} is already assigned to {command['location']}.")
            elif not matches:
                st.warning(f"No item ends in {command['suffix']}.")
            else:
                st.warning(f"{len(matches)} items end in {command['suffix']}. Use the item search to choose the right one.")
        else:
            st.session_state["search_term_input"] = command["suffix"]
            st.toast(f"Searching item suffix {command['suffix']}.")
    
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

    current_locations = current_item["locations"]
    st.write("#### 📍 Registered Locations:")
    if current_locations:
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

    with st.expander("➕ Add New Location", expanded=False):
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

    device_bin_settings = load_device_bin_settings(device_id)
    p_bin = device_bin_settings.get("last_bin_parts", {"area": "A1", "type": "DR", "sig1": "", "sig2": ""})
    p_bounds = device_bin_settings.get("vertical_bounds", {"start": "AA", "max": "AO", "max_col": "30"})
    if "vertical_bounds" not in st.session_state:
        st.session_state.vertical_bounds = p_bounds

    # Direct integration to widget keys to avoid variable mismatch
    if "bin_area_in" not in st.session_state:
        st.session_state.bin_area_in = p_bin.get("area", "A1")
    if "bin_type_in" not in st.session_state:
        st.session_state.bin_type_in = p_bin.get("type", "DR")
    if "bin_sig1_in" not in st.session_state:
        st.session_state.bin_sig1_in = p_bin.get("sig1", "")
    if "bin_sig2_in" not in st.session_state:
        st.session_state.bin_sig2_in = p_bin.get("sig2", "")
    if "bin_location_in" not in st.session_state:
        initial_location = location_from_bin_parts(
            st.session_state.bin_area_in,
            st.session_state.bin_type_in,
            st.session_state.bin_sig1_in,
            st.session_state.bin_sig2_in,
        )
        st.session_state.bin_location_in = format_bin_location_input(initial_location)
    if "focus_item_search" not in st.session_state:
        st.session_state.focus_item_search = False

    st.caption("Voice examples: say “4005” to assign it to the active bin, “next bin” or “previous bin” to move, or “item 4005 in A1 DR CA 03” to assign to a spoken location.")
    spoken_command = show_voice_commands()
    if spoken_command:
        command = parse_voice_command(spoken_command)
        if command["action"] in {"next", "previous"}:
            bin_parts_ready = all(
                st.session_state.get(key, "").strip()
                for key in ("bin_area_in", "bin_type_in", "bin_sig1_in", "bin_sig2_in")
            )
            if not bin_parts_ready:
                st.warning("Enter the area, type, row, and column before moving to another bin.")
            else:
                bounds = st.session_state.get("vertical_bounds", p_bounds)
                try:
                    voice_max_col = int(bounds.get("max_col", "30"))
                    if voice_max_col < 1:
                        voice_max_col = 30
                except (TypeError, ValueError):
                    voice_max_col = 30
                move_bin_vertical(
                    command["action"],
                    str(bounds.get("start", "AA")).strip().upper(),
                    str(bounds.get("max", "AO")).strip().upper(),
                    voice_max_col,
                )
                st.toast("Moved to the next bin." if command["action"] == "next" else "Moved to the previous bin.")
        elif command["action"] == "invalid":
            st.warning(command["message"])
        else:
            location = command.get("location") or location_from_bin_parts(
                st.session_state.get("bin_area_in", "").strip().upper(),
                st.session_state.get("bin_type_in", "").strip().upper(),
                st.session_state.get("bin_sig1_in", "").strip().upper(),
                st.session_state.get("bin_sig2_in", "").strip().upper(),
            )
            if not location:
                st.warning("Complete the active bin location, or say the full location with the item.")
            else:
                matches = [itm for itm in items if itm["item_code"].endswith(command["suffix"])]
                if len(matches) == 1:
                    item = matches[0]
                    result = assign_item_to_location(item, location)
                    if result == "assigned":
                        st.session_state["bin_digit_srch"] = ""
                        st.session_state.focus_item_search = True
                        st.toast(f"Assigned item {item['item_code']} to {location}.", icon="✅")
                        st.rerun()
                    else:
                        st.info(f"Item {item['item_code']} is already in {location}.")
                elif not matches:
                    st.warning(f"No item ends in {command['suffix']}.")
                else:
                    st.warning(f"{len(matches)} items end in {command['suffix']}. Use the item search to choose the right one.")

    with st.expander("⚙️ Bin settings", expanded=False):
        st.caption("These settings are saved separately for this browser/device.")
        location_component = BIN_LOCATION_COMPONENT(
            data={"value": st.session_state.bin_location_in},
            default={"value": st.session_state.bin_location_in},
            key="bin_location_component",
            height=100,
            width="stretch",
            on_value_change=sync_bin_location_parts,
        )
        current_location_value = getattr(location_component, "value", None)
        if isinstance(current_location_value, str):
            st.session_state.bin_location_in = format_bin_location_input(current_location_value)

        in_area = st.session_state.bin_area_in.strip().upper()
        in_type = st.session_state.bin_type_in.strip().upper()
        in_sig1 = st.session_state.bin_sig1_in.strip().upper()
        in_sig2 = st.session_state.bin_sig2_in.strip().upper()
        all_fields_filled = bool(re.fullmatch(
            r"[A-Z0-9]{2}\.[A-Z0-9]{2}\.[A-Z0-9]{1,2}\.[A-Z0-9]{1,4}",
            st.session_state.bin_location_in.strip().upper(),
        ))
        device_bin_settings["last_bin_parts"] = {
            "area": in_area, "type": in_type, "sig1": in_sig1, "sig2": in_sig2
        }

        if all_fields_filled:
            target_bin_location = location_from_bin_parts(in_area, in_type, in_sig1, in_sig2)
            device_bin_settings["last_bin_location"] = target_bin_location
        else:
            target_bin_location = ""

        st.markdown("**Row / Column Settings**")
        c_conf1, c_conf2 = st.columns(2)
        c_conf3, _ = st.columns(2)
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
        st.caption("Max Row can be a full row (AO) or its final identifier (O).")
        try:
            max_col_val = int(max_col_raw)
            if max_col_val < 1:
                max_col_val = 30
        except ValueError:
            max_col_val = 30
        st.session_state.vertical_bounds = {
            "start": start_row, "max": max_row, "max_col": max_col_raw
        }
        device_bin_settings["vertical_bounds"] = st.session_state.vertical_bounds
        save_device_bin_settings(device_id, device_bin_settings)

        def advance_vertical():
            move_bin_vertical("next", start_row, max_row, max_col_val)

        def retreat_vertical():
            move_bin_vertical("previous", start_row, max_row, max_col_val)

    active_bin_display = html.escape(target_bin_location or "Select a bin in Bin settings")
    active_bin_class = "active" if all_fields_filled else "incomplete"
    st.markdown(
        f"""
        <style>
          .bin-location-float {{
            position: fixed;
            top: calc(3.4rem + env(safe-area-inset-top, 0px));
            left: 50%;
            transform: translateX(-50%);
            width: min(680px, calc(100vw - 1rem));
            box-sizing: border-box;
            padding: .65rem .9rem;
            border-radius: .75rem;
            color: #fff;
            background: #155e75;
            box-shadow: 0 3px 12px rgba(0, 0, 0, .24);
            text-align: center;
            font-size: 1rem;
            line-height: 1.3;
            z-index: 999999;
          }}
          .bin-location-float.incomplete {{ background: #92400e; }}
          .bin-location-float strong {{ font-size: 1.15rem; letter-spacing: .04em; }}
        </style>
        <div class="bin-location-float {active_bin_class}" role="status">
          📍 Active bin: <strong>{active_bin_display}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    if all_fields_filled:
        b_prevloc, b_nextloc = st.columns(2)
        b_prevloc.button("⬅️ Previous bin", use_container_width=True, on_click=retreat_vertical)
        b_nextloc.button("Next bin ➡️", use_container_width=True, on_click=advance_vertical)

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
        "Add item to this bin",
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
              let attempts = 0;
              const focusSearch = () => {{
                  const input = doc.querySelector('input[placeholder="E.G. 1234 OR PARACETAMOL"]');
                  if (input && !input.disabled) {{
                      input.focus();
                      input.select();
                  }} else if (attempts++ < 12) {{
                      setTimeout(focusSearch, 100);
                  }}
              }};
              setTimeout(focusSearch, 100);
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
