import os
from datetime import datetime
from typing import Optional, Union

import typer
from decouple import UndefinedValueError, config
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.db import GetDB, crud
from app.db.models import Admin, User
from app.models.admin import AdminCreate, AdminPartialModify, pwd_context
from app.utils.system import readable_size

from . import utils

app = typer.Typer(no_args_is_help=True)


def validate_telegram_id(value: Union[int, str]) -> Union[int, None]:
    if not value:
        return 0
    if not isinstance(value, int) and not value.isdigit():
        raise typer.BadParameter("Telegram ID must be an integer.")
    if int(value) < 0:
        raise typer.BadParameter("Telegram ID must be a positive integer.")
    return value


def validate_discord_webhook(value: str) -> Union[str, None]:
    if not value or value == "0":
        return ""
    if not value.startswith("https://discord.com/api/webhooks/"):
        utils.error("Discord webhook must start with 'https://discord.com/api/webhooks/'")
    return value


def calculate_admin_usage(admin_id: int) -> str:
    with GetDB() as db:
        usage = db.query(func.sum(User.used_traffic)).filter_by(admin_id=admin_id).first()[0]
        return readable_size(int(usage or 0))


def calculate_admin_reseted_usage(admin_id: int) -> str:
    with GetDB() as db:
        usage = db.query(func.sum(User.reseted_usage)).filter_by(admin_id=admin_id).scalar()
        return readable_size(int(usage or 0))


@app.command(name="list")
def list_admins(
    offset: Optional[int] = typer.Option(None, *utils.FLAGS["offset"]),
    limit: Optional[int] = typer.Option(None, *utils.FLAGS["limit"]),
    username: Optional[str] = typer.Option(None, *utils.FLAGS["username"], help="Search by username"),
):
    """Displays a table of admins"""
    with GetDB() as db:
        admins: list[Admin] = crud.get_admins(db, offset=offset, limit=limit, username=username)
        utils.print_table(
            table=Table("Username", 'Usage', 'Reseted usage', "Users Usage", "Is sudo",
                        "Created at", "Telegram ID", "Discord Webhook"),
            rows=[
                (str(admin.username),
                 calculate_admin_usage(admin.id),
                 calculate_admin_reseted_usage(admin.id),
                 readable_size(admin.users_usage),
                 "✔️" if admin.is_sudo else "✖️",
                 utils.readable_datetime(admin.created_at),
                 str(admin.telegram_id or "✖️"),
                 str(admin.discord_webhook or "✖️"))
                for admin in admins
            ]
        )


@app.command(name="delete")
def delete_admin(
    username: str = typer.Option(..., *utils.FLAGS["username"], prompt=True),
    yes_to_all: bool = typer.Option(False, *utils.FLAGS["yes_to_all"], help="Skips confirmations")
):
    """
    Deletes the specified admin

    Confirmations can be skipped using `--yes/-y` option.
    """
    with GetDB() as db:
        admin: Union[Admin, None] = crud.get_admin(db, username=username)
        if not admin:
            utils.error(f"There's no admin with username \"{username}\"!")

        if yes_to_all or typer.confirm(f'Are you sure about deleting "{username}"?', default=False):
            crud.remove_admin(db, admin)
            utils.success(f'"{username}" deleted successfully.')
        else:
            utils.error("Operation aborted!")


@app.command(name="create")
def create_admin(
    username: str = typer.Option(..., *utils.FLAGS["username"], show_default=False, prompt=True),
    is_sudo: bool = typer.Option(False, *utils.FLAGS["is_sudo"], prompt=True),
    password: str = typer.Option(..., prompt=True, confirmation_prompt=True,
                                 hide_input=True, hidden=True, envvar=utils.PASSWORD_ENVIRON_NAME),
    telegram_id: str = typer.Option('', *utils.FLAGS["telegram_id"], prompt="Telegram ID",
                                    show_default=False, callback=validate_telegram_id),
    discord_webhook: str = typer.Option('', *utils.FLAGS["discord_webhook"], prompt=True,
                                        show_default=False, callback=validate_discord_webhook),
):
    """
    Creates an admin

    Password can also be set using `NEXUSPANEL_ADMIN_PASSWORD`.
    """
    with GetDB() as db:
        try:
            crud.create_admin(db, AdminCreate(username=username,
                                              password=password,
                                              is_sudo=is_sudo,
                                              telegram_id=telegram_id,
                                              discord_webhook=discord_webhook))
            utils.success(f'Admin "{username}" created successfully.')
        except IntegrityError:
            utils.error(f'Admin "{username}" already exists!')


@app.command(name="update")
def update_admin(username: str = typer.Option(..., *utils.FLAGS["username"], prompt=True, show_default=False)):
    """
    Updates the specified admin

    NOTE: This command CAN NOT be used non-interactively.
    """

    def _get_modify_model(admin: Admin):
        Console().print(
            Panel(f'Editing "{username}". Just press "Enter" to leave each field unchanged.')
        )

        is_sudo: bool = typer.confirm("Is sudo", default=admin.is_sudo)
        new_password: Union[str, None] = typer.prompt(
            "New password",
            default="",
            show_default=False,
            confirmation_prompt=True,
            hide_input=True
        ) or None

        telegram_id: str = typer.prompt("Telegram ID (Enter 0 to clear current value)",
                                        default=admin.telegram_id or "")
        telegram_id = validate_telegram_id(telegram_id)

        discord_webhook: str = typer.prompt("Discord webhook (Enter 0 to clear current value)",
                                            default=admin.discord_webhook or "")
        discord_webhook = validate_discord_webhook(discord_webhook)

        return AdminPartialModify(
            is_sudo=is_sudo,
            password=new_password,
            telegram_id=telegram_id,
            discord_webhook=discord_webhook
        )

    with GetDB() as db:
        admin: Union[Admin, None] = crud.get_admin(db, username=username)
        if not admin:
            utils.error(f"There's no admin with username \"{username}\"!")

        crud.partial_update_admin(db, admin, _get_modify_model(admin))
        utils.success(f'Admin "{username}" updated successfully.')


@app.command(name="set-password")
def set_password(
    username: str = typer.Option(..., *utils.FLAGS["username"], prompt=True, show_default=False),
    password: str = typer.Option(
        ..., prompt="New password", confirmation_prompt=True, hide_input=True,
        envvar=utils.PASSWORD_ENVIRON_NAME,
    ),
):
    """
    Changes an admin's password (non-interactive friendly).

    Password can also be supplied via the ``NEXUSPANEL_ADMIN_PASSWORD`` env var.
    Changing the password also invalidates the admin's existing login sessions.
    """
    with GetDB() as db:
        admin: Union[Admin, None] = crud.get_admin(db, username=username)
        if not admin:
            utils.error(f'There\'s no admin with username "{username}"!')

        # Set the hash directly (mirrors crud.partial_update_admin) instead of
        # going through AdminPartialModify, whose annotations hack makes every
        # field required under pydantic v2.
        admin.hashed_password = pwd_context.hash(password)
        admin.password_reset_at = datetime.utcnow()
        db.commit()
        utils.success(f'Password for "{username}" updated successfully.')


def _resolve_target_admin(db, username: Optional[str]) -> Admin:
    """Pick the admin to operate on for a recovery-style credential reset.

    When ``username`` is given it is used directly. Otherwise we target the
    *sole* sudo admin — this is the whole point of the recovery flow: the
    operator can set brand-new credentials without remembering the old
    username. Ambiguity (0 or >1 sudo admins) is a hard error so we never
    silently reset the wrong account.
    """
    if username:
        admin = crud.get_admin(db, username=username)
        if not admin:
            utils.error(f'There\'s no admin with username "{username}"!')
        return admin

    sudo_admins = db.query(Admin).filter(Admin.is_sudo.is_(True)).order_by(Admin.id).all()
    if not sudo_admins:
        utils.error("No sudo admin found to reset.")
    if len(sudo_admins) > 1:
        names = ", ".join(a.username for a in sudo_admins)
        utils.error(
            "Multiple sudo admins exist; pass --username to pick one. "
            f"Candidates: {names}"
        )
    return sudo_admins[0]


@app.command(name="reset-credentials")
def reset_credentials(
    new_username: Optional[str] = typer.Option(
        None, "--new-username", "-nu", help="New username (blank/omit = keep current)."
    ),
    username: Optional[str] = typer.Option(
        None, *utils.FLAGS["username"],
        help="Target admin. Only needed when more than one sudo admin exists.",
    ),
):
    """
    Reset the sudo admin's username and/or password WITHOUT the old username.

    This is the "I forgot my login" recovery path: it targets the sole sudo
    admin automatically, so you can set a fresh username and password even if
    the previous ones are lost. The new password is read from the
    ``NEXUSPANEL_ADMIN_PASSWORD`` env var (never passed on the command line);
    leave it unset to keep the current password. Resetting the password also
    invalidates existing login sessions.
    """
    password = os.environ.get(utils.PASSWORD_ENVIRON_NAME) or None
    new_username = (new_username or "").strip() or None

    if not password and not new_username:
        utils.error(
            "Nothing to change: set NEXUSPANEL_ADMIN_PASSWORD and/or pass --new-username."
        )

    with GetDB() as db:
        admin = _resolve_target_admin(db, username)

        if new_username and new_username != admin.username:
            if crud.get_admin(db, username=new_username):
                utils.error(f'An admin with username "{new_username}" already exists!')
            admin.username = new_username

        if password:
            admin.hashed_password = pwd_context.hash(password)
            admin.password_reset_at = datetime.utcnow()

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            utils.error(f'An admin with username "{new_username}" already exists!')

        utils.success(
            f'Credentials reset. Login username is now "{admin.username}".'
        )


@app.command(name="whoami")
def whoami():
    """
    Prints the username of the sole sudo admin (for scripting/tooling).

    Lets management tooling (e.g. the ``nexus`` server manager) resolve which
    admin account to act on without asking the operator to retype a username
    they may not even remember. Fails if there isn't exactly one sudo admin.
    """
    with GetDB() as db:
        sudo_admins = db.query(Admin).filter(Admin.is_sudo.is_(True)).order_by(Admin.id).all()
        if not sudo_admins:
            utils.error("No sudo admin found.")
        if len(sudo_admins) > 1:
            utils.error(
                "Multiple sudo admins found; use `admin list` and target one explicitly."
            )
        typer.echo(sudo_admins[0].username)


@app.command(name="rename")
def rename_admin(
    current: str = typer.Option(..., "--current", "-c", prompt="Current username", show_default=False),
    new: str = typer.Option(..., "--new", "-n", prompt="New username", show_default=False),
):
    """Renames an admin's username. Users linked by ``admin_id`` are unaffected."""
    new = (new or "").strip()
    if not new:
        utils.error("New username must not be empty.")
    if current == new:
        utils.error("New username is identical to the current one.")

    with GetDB() as db:
        admin: Union[Admin, None] = crud.get_admin(db, username=current)
        if not admin:
            utils.error(f'There\'s no admin with username "{current}"!')
        if crud.get_admin(db, username=new):
            utils.error(f'An admin with username "{new}" already exists!')

        admin.username = new
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            utils.error(f'An admin with username "{new}" already exists!')
        utils.success(f'Admin "{current}" renamed to "{new}" successfully.')


@app.command(name="import-from-env")
def import_from_env(yes_to_all: bool = typer.Option(False, *utils.FLAGS["yes_to_all"], help="Skips confirmations")):
    """
    Imports the sudo admin from env

    Confirmations can be skipped using `--yes/-y` option.

    What does it do?
      - Creates a sudo admin according to `SUDO_USERNAME` and `SUDO_PASSWORD`.
      - Links any user which doesn't have an `admin_id` to the imported sudo admin.
    """
    try:
        username, password = config("SUDO_USERNAME"), config("SUDO_PASSWORD")
    except UndefinedValueError:
        utils.error(
            "Unable to get SUDO_USERNAME and/or SUDO_PASSWORD.\n"
            "Make sure you have set them in the env file or as environment variables."
        )

    if not (username and password):
        utils.error("Unable to retrieve username and password.\n"
                    "Make sure both SUDO_USERNAME and SUDO_PASSWORD are set.")

    with GetDB() as db:
        admin: Union[None, Admin] = None

        # If env admin already exists
        if current_admin := crud.get_admin(db, username=username):
            if not yes_to_all and not typer.confirm(
                f'Admin "{username}" already exists. Do you want to sync it with env?', default=None
            ):
                utils.error("Aborted.")

            admin = crud.partial_update_admin(
                db,
                current_admin,
                AdminPartialModify(password=password, is_sudo=True)
            )
        # If env admin does not exist yet
        else:
            admin = crud.create_admin(db, AdminCreate(
                username=username,
                password=password,
                is_sudo=True
            ))

        updated_user_count = db.query(User).filter_by(admin_id=None).update({"admin_id": admin.id})
        db.commit()

        utils.success(
            f'Admin "{username}" imported successfully.\n'
            f"{updated_user_count} users' admin_id set to the {username}'s id.\n"
            'You must delete SUDO_USERNAME and SUDO_PASSWORD from your env file now.'
        )
