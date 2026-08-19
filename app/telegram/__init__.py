import importlib.util
from os.path import dirname
from threading import Thread
from config import TELEGRAM_API_TOKEN, TELEGRAM_PROXY_URL
from app import app
from telebot import TeleBot, apihelper


bot = None
if TELEGRAM_API_TOKEN:
    apihelper.proxy = {'http': TELEGRAM_PROXY_URL, 'https': TELEGRAM_PROXY_URL}
    bot = TeleBot(TELEGRAM_API_TOKEN)

handler_names = ["admin", "report", "user"]
_polling_started = False


def start_bot_polling() -> None:
    """Exactly one process may poll Telegram. API uvicorn workers must not."""
    global _polling_started
    if not bot or _polling_started:
        return
    from app.runtime_role import owns_control_plane

    if not owns_control_plane():
        return
    handler_dir = dirname(__file__) + "/handlers/"
    for name in handler_names:
        spec = importlib.util.spec_from_file_location(name, f"{handler_dir}{name}.py")
        spec.loader.exec_module(importlib.util.module_from_spec(spec))

    from app.telegram import utils  # setup custom handlers

    utils.setup()
    _polling_started = True
    thread = Thread(target=bot.infinity_polling, daemon=True)
    thread.start()


@app.on_event("startup")
def start_bot():
    start_bot_polling()


from .handlers.report import (  # noqa
    report,
    report_new_user,
    report_user_modification,
    report_user_deletion,
    report_status_change,
    report_user_usage_reset,
    report_user_data_reset_by_next,
    report_user_subscription_revoked,
    report_login
)

__all__ = [
    "bot",
    "report",
    "report_new_user",
    "report_user_modification",
    "report_user_deletion",
    "report_status_change",
    "report_user_usage_reset",
    "report_user_data_reset_by_next",
    "report_user_subscription_revoked",
    "report_login"
]
