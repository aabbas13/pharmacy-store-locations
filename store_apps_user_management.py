"""Local manager for individual Firebase Authentication accounts.

Run this on the administrator's computer. The service-account key is requested
at runtime and should be stored outside this project and outside GitHub.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials

SHARED_FIREBASE_PROJECT_ID = "hmc-picker-checks"

APP_ACCESS = {
    "1": ("mobile_app", "Store mobile app"),
    "2": ("picking_helper", "Picker HTML app"),
    "3": (None, "Both apps"),
    "4": ("none", "No app access"),
}


def initialize_firebase() -> None:
    key_path = os.environ.get("FIREBASE_ADMIN_CREDENTIALS", "").strip()
    if not key_path:
        key_path = input("Path to Firebase Admin service-account JSON: ").strip().strip('"')
    path = Path(key_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Credential file not found: {path}")

    with path.open("r", encoding="utf-8") as key_file:
        service_account = json.load(key_file)
    project_id = service_account.get("project_id")
    if project_id != SHARED_FIREBASE_PROJECT_ID:
        raise ValueError(
            "This manager must use a service-account key from the shared "
            f"Firebase project '{SHARED_FIREBASE_PROJECT_ID}'. The selected "
            f"key belongs to '{project_id or 'an unknown project'}'."
        )
    firebase_admin.initialize_app(credentials.Certificate(service_account))


def get_user(email: str):
    return auth.get_user_by_email(email.strip())


def prompt_app_access() -> str | None:
    print("Choose app access: 1) Store mobile app  2) Picker HTML app  3) Both  4) None")
    choice = input("App access: ").strip()
    if choice not in APP_ACCESS:
        print("No access changes were made.")
        return None
    return choice


def assign_app_access(uid: str, choice: str) -> None:
    user = auth.get_user(uid)
    claims = dict(user.custom_claims or {})
    if choice == "3":
        claims["mobile_app"] = True
        claims["picking_helper"] = True
    elif choice == "4":
        claims["mobile_app"] = False
        claims["picking_helper"] = False
    else:
        selected_claim, _ = APP_ACCESS[choice]
        claims[selected_claim] = True
        other_claim = "picking_helper" if selected_claim == "mobile_app" else "mobile_app"
        claims[other_claim] = False
    auth.set_custom_user_claims(uid, claims)
    auth.revoke_refresh_tokens(uid)


def require_password_change(uid: str) -> None:
    user = auth.get_user(uid)
    claims = dict(user.custom_claims or {})
    claims["must_change_password"] = True
    auth.set_custom_user_claims(uid, claims)
    auth.revoke_refresh_tokens(uid)


def prompt_password(action: str) -> str | None:
    password = getpass.getpass(f"{action} password (minimum 8 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords did not match; no change was made.")
        return None
    if len(password) < 8:
        print("Use a password with at least 8 characters; no change was made.")
        return None
    return password


def add_user() -> None:
    email = input("Storekeeper email: ").strip()
    display_name = input("Storekeeper name (optional): ").strip() or None
    password = prompt_password("Temporary")
    if not password:
        return
    choice = prompt_app_access()
    if not choice:
        return
    user = auth.create_user(email=email, password=password, display_name=display_name)
    assign_app_access(user.uid, choice)
    if choice != "4":
        require_password_change(user.uid)
        print(
            f"Created shared Store Apps account for {user.email}. "
            "The temporary password must be changed before using either app."
        )
    else:
        print(f"Created account for {user.email} with no app access.")


def list_users() -> None:
    page = auth.list_users()
    users = []
    while page:
        users.extend(page.users)
        page = page.get_next_page()
    if not users:
        print("No accounts found.")
        return
    print("\nShared Firebase accounts")
    print("------------------------")
    for user in sorted(users, key=lambda entry: (entry.email or "").lower()):
        claims = user.custom_claims or {}
        access = ", ".join(
            label
            for claim, label in (("mobile_app", "Store mobile"), ("picking_helper", "Picker HTML"))
            if claims.get(claim)
        ) or "no app access"
        admin = ", user admin" if claims.get("store_admin") else ""
        state = "DISABLED" if user.disabled else "active"
        if claims.get("must_change_password"):
            state += "; password change required"
        name = f" — {user.display_name}" if user.display_name else ""
        print(f"{state:8}  {user.email or '(no email)'}{name} [{access}{admin}]")


def reset_password() -> None:
    user = get_user(input("Account email: "))
    password = prompt_password("New")
    if not password:
        return
    auth.update_user(user.uid, password=password)
    require_password_change(user.uid)
    auth.revoke_refresh_tokens(user.uid)
    print(
        f"Temporary password set for {user.email}; they must change it before using either app. "
        "Existing sessions were revoked."
    )


def set_app_access_for_user() -> None:
    user = get_user(input("Account email: "))
    choice = prompt_app_access()
    if not choice:
        return
    assign_app_access(user.uid, choice)
    print(f"App access updated for {user.email}; they must sign in again.")


def set_store_admin(enabled: bool) -> None:
    user = get_user(input("Account email: "))
    if enabled:
        confirmation = input(
            f"Type {user.email} to grant in-app user-management administrator access: "
        ).strip()
        if confirmation.lower() != (user.email or "").lower():
            print("Confirmation did not match; administrator access was not changed.")
            return
    claims = dict(user.custom_claims or {})
    claims["store_admin"] = enabled
    auth.set_custom_user_claims(user.uid, claims)
    auth.revoke_refresh_tokens(user.uid)
    state = "granted to" if enabled else "removed from"
    print(f"In-app user-management administrator access {state} {user.email}.")


def set_user_disabled(disabled: bool) -> None:
    user = get_user(input("Account email: "))
    auth.update_user(user.uid, disabled=disabled)
    if disabled:
        auth.revoke_refresh_tokens(user.uid)
    state = "disabled" if disabled else "enabled"
    print(f"Account {user.email} is now {state}.")


def delete_user() -> None:
    email = input("Account email to delete: ").strip()
    user = get_user(email)
    if input(f"Type {email} to permanently delete this account: ").strip() != email:
        print("Confirmation did not match; no account was deleted.")
        return
    auth.delete_user(user.uid)
    print(f"Deleted account {user.email}.")


def main() -> None:
    try:
        initialize_firebase()
    except (OSError, ValueError, json.JSONDecodeError, firebase_admin.exceptions.FirebaseError) as exc:
        print(f"Could not connect to Firebase: {exc}")
        return

    actions = {
        "1": ("Add account", add_user),
        "2": ("List accounts", list_users),
        "3": ("Reset password", reset_password),
        "4": ("Change app access (picker/store/both/none)", set_app_access_for_user),
        "5": ("Grant in-app user-management administrator", lambda: set_store_admin(True)),
        "6": ("Remove in-app user-management administrator", lambda: set_store_admin(False)),
        "7": ("Disable account", lambda: set_user_disabled(True)),
        "8": ("Enable account", lambda: set_user_disabled(False)),
        "9": ("Delete account", delete_user),
    }
    while True:
        print("\nStore Apps User Management")
        for number, (label, _) in actions.items():
            print(f"{number}. {label}")
        print("0. Exit")
        choice = input("Choose an action: ").strip()
        if choice == "0":
            break
        selected = actions.get(choice)
        if not selected:
            print("Choose one of the listed options.")
            continue
        try:
            selected[1]()
        except firebase_admin.exceptions.FirebaseError as exc:
            print(f"Firebase could not complete that action: {exc}")
        except (ValueError, OSError) as exc:
            print(f"Could not complete that action: {exc}")


if __name__ == "__main__":
    main()
