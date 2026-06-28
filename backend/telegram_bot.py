#!/usr/bin/env python3
"""FelineFinder Telegram bot — sends 12h cat diary entries and handles /summary."""

import datetime as dt
import json
import logging

import anthropic
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from day_json import get_timelines
from telegram_bot_config import CAT_PROFILES, SYSTEM_PROMPT, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

ACTIVE_CATS = {"Arthur", "King"}
TIMEZONE = pytz.timezone("Europe/Zurich")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def generate_summary(window_hours=12):
    """Returns {cat_name: diary_entry_text} for the past window_hours."""
    tz = pytz.timezone("Europe/Zurich")
    end = dt.datetime.now(tz)
    start = end - dt.timedelta(hours=window_hours)

    timelines = get_timelines(start, end, active_cats=ACTIVE_CATS)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    summaries = {}

    for cat_name, event_log in timelines.items():
        profile = CAT_PROFILES.get(cat_name, "")
        user_content = (
            f"Character Profile:\n{profile}\n\n"
            f"Story Log:\n{json.dumps(event_log, indent=2)}"
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        summaries[cat_name] = response.content[0].text

    return summaries


async def summary_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    status = await update.message.reply_text("Fetching summary...")
    try:
        summaries = generate_summary()
        await status.delete()
        for text in summaries.values():
            await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /summary: {e}")
        await status.edit_text("Sorry, couldn't generate the summary right now.")


async def scheduled_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        summaries = generate_summary()
        for text in summaries.values():
            await context.bot.send_message(
                chat_id=int(TELEGRAM_CHAT_ID), text=text, parse_mode="HTML"
            )
        logger.info("Scheduled summary sent.")
    except Exception as e:
        logger.error(f"Error in scheduled summary: {e}")
        await context.bot.send_message(
            chat_id=int(TELEGRAM_CHAT_ID),
            text="Sorry, couldn't generate the scheduled summary right now.",
        )


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    user_filter = filters.User(user_id=int(TELEGRAM_CHAT_ID))
    application.add_handler(CommandHandler("summary", summary_command, filters=user_filter))

    job_queue = application.job_queue
    job_queue.run_daily(
        scheduled_summary,
        dt.time(hour=8, minute=0, tzinfo=TIMEZONE),
        name="morning_summary",
    )
    job_queue.run_daily(
        scheduled_summary,
        dt.time(hour=20, minute=0, tzinfo=TIMEZONE),
        name="evening_summary",
    )

    logger.info("FelineFinder Telegram bot started.")
    application.run_polling(timeout=30)


if __name__ == "__main__":
    main()
