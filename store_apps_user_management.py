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


def initialize_firebase() -> None:
    key_path = os.environ.get("FIREBASE_ADMIN_CREDENTIALS", "").strip()
    if not key_path:
        key_path = input("Path to Firebase Admin service-account JSON: ").strip().strip('"')
    path = Path(key_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Credential file not found: {path}")

    with path.open("r", encoding="utf-8") as key_file:
        service_account = json.load(key_file)
    firebase_admin.initialize_app(credentials.Certificate(service_account))


def get_user(email: str):
    return auth.get_user_by_email(email.strip())


def assign_mobile_access(uid: str, enabled: bool = True) -> None:
    user = auth.get_user(uid)
    claims = dict(user.custom_claims or {})
    claims["mobile_app"] = enabled
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
    user = auth.create_user(email=email, password=password, display_name=display_name)
    assign_mobile_access(user.uid)
    print(f"Created mobile app account for {user.email}.")


def list_users() -> None:
    page = auth.list_users()
    users = []
    while page:
        users.extend(page.users)
        page = page.get_next_page()
    if not users:
        print("No accounts found.")
        return
    print("\nFirebase accounts (mobile app access)")
    print("--------------------------------------")
    for user in sorted(users, key=lambda entry: (entry.email or "").lower()):
        claims = user.custom_claims or {}
        access = "enabled" if claims.get("mobile_app") else "no access"
        state = "DISABLED" if user.disabled else "active"
        name = f" — {user.display_name}" if user.display_name else ""
        print(f"{state:8}  {user.email or '(no email)'}{name} [{access}]")


def reset_password() -> None:
    user = get_user(input("Account email: "))
    password = prompt_password("New")
    if not password:
        return
    auth.update_user(user.uid, password=password)
    auth.revoke_refresh_tokens(user.uid)
    print(f"Password reset for {user.email}; existing sessions were revoked.")


def set_mobile_access(enabled: bool) -> None:
    user = get_user(input("Account email: "))
    assign_mobile_access(user.uid, enabled)
    state = "enabled" if enabled else "removed"
    print(f"Mobile app access {state} for {user.email}; they must sign in again.")


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
        "1": ("Add storekeeper", add_user),
        "2": ("List accounts", list_users),
        "3": ("Reset password", reset_password),
        "4": ("Grant mobile app access", lambda: set_mobile_access(True)),
        "5": ("Remove mobile app access", lambda: set_mobile_access(False)),
        "6": ("Disable account", lambda: set_user_disabled(True)),
        "7": ("Enable account", lambda: set_user_disabled(False)),
        "8": ("Delete account", delete_user),
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
