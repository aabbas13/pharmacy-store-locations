"""Local command-line manager for Store Apps Firebase Auth accounts.

The Firebase service-account key is requested at runtime and should be kept
outside the synchronized project folder and GitHub repository.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials

APP_CLAIMS = ("mobile_app", "picking_helper")


def initialize_firebase() -> None:
    key_path = os.environ.get("FIREBASE_ADMIN_CREDENTIALS", "").strip()
    if not key_path:
        key_path = input("Path to Firebase Admin service-account JSON: ").strip().strip('"')
    path = Path(key_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Credential file not found: {path}")

    with path.open("r", encoding="utf-8") as key_file:
        service_account = json.load(key_file)
    credential = credentials.Certificate(service_account)
    firebase_admin.initialize_app(credential)


def find_user(email: str):
    return auth.get_user_by_email(email.strip())


def add_user() -> None:
    email = input("Storekeeper email: ").strip()
    display_name = input("Storekeeper name (optional): ").strip() or None
    password = getpass.getpass("Temporary password (minimum 8 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords did not match; no account was created.")
        return
    if len(password) < 8:
        print("Use a password with at least 8 characters; no account was created.")
        return
    user = auth.create_user(email=email, password=password, display_name=display_name)
    set_app_access(user.uid)
    print(f"Created account for {user.email}.")


def list_users() -> None:
    page = auth.list_users()
    users = []
    while page:
        users.extend(page.users)
        page = page.get_next_page()
    if not users:
        print("No accounts found.")
        return
    print("\nStore Apps accounts")
    print("-------------------")
    for user in sorted(users, key=lambda entry: (entry.email or "").lower()):
        state = "DISABLED" if user.disabled else "active"
        name = f" — {user.display_name}" if user.display_name else ""
        claims = user.custom_claims or {}
        access = ", ".join(
            label
            for claim, label in (("mobile_app", "Mobile"), ("picking_helper", "HTML helper"))
            if claims.get(claim)
        ) or "no app access"
        print(f"{state:8}  {user.email or '(no email)'}{name} [{access}]")


def set_app_access(uid=None) -> None:
    if uid is None:
        email = input("Account email: ").strip()
        uid = find_user(email).uid
    print("Choose app access: 1) Mobile app  2) HTML helper  3) Both  4) None")
    choice = input("Access: ").strip()
    values = {
        "1": {"mobile_app": True, "picking_helper": False},
        "2": {"mobile_app": False, "picking_helper": True},
        "3": {"mobile_app": True, "picking_helper": True},
        "4": {"mobile_app": False, "picking_helper": False},
    }
    if choice not in values:
        print("No access changes were made.")
        return
    auth.set_custom_user_claims(uid, values[choice])
    auth.revoke_refresh_tokens(uid)
    print("App permissions updated. The user must sign in again for the change to take effect.")


def reset_password() -> None:
    email = input("Account email: ").strip()
    user = find_user(email)
    password = getpass.getpass("New password (minimum 8 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        print("Passwords did not match; no change was made.")
        return
    if len(password) < 8:
        print("Use a password with at least 8 characters; no change was made.")
        return
    auth.update_user(user.uid, password=password)
    auth.revoke_refresh_tokens(user.uid)
    print(f"Password reset for {user.email}; existing sessions were revoked.")


def set_user_disabled(disabled: bool) -> None:
    email = input("Account email: ").strip()
    user = find_user(email)
    auth.update_user(user.uid, disabled=disabled)
    if disabled:
        auth.revoke_refresh_tokens(user.uid)
    action = "disabled" if disabled else "enabled"
    print(f"Account {user.email} is now {action}.")


def delete_user() -> None:
    email = input("Account email to delete: ").strip()
    user = find_user(email)
    confirmation = input(f"Type {email} to permanently delete this account: ").strip()
    if confirmation != email:
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
        "3": ("Change app access", set_app_access),
        "4": ("Reset password", reset_password),
        "5": ("Disable account", lambda: set_user_disabled(True)),
        "6": ("Enable account", lambda: set_user_disabled(False)),
        "7": ("Delete account", delete_user),
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
