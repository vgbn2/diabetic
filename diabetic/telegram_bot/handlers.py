import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from functools import wraps

from diabetic.config import config
from diabetic.telegram_bot.decision_matrix import Alert

class TelegramNotifier:
    """
    Asynchronous Telegram Notifier for real-time alerts.
    Supports interactive buttons for alert confirmation.
    """
    def __init__(self):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.USER_ID
        self.bot: Optional[Bot] = None
        self.logger = logging.getLogger("Bio-Quant.Telegram")

        if self.token:
            self.bot = Bot(token=self.token)

    async def send_alert(self, alert: Alert):
        """Pushes an alert to the user with interactive buttons."""
        if not self.bot or not self.chat_id:
            self.logger.error("Telegram token or Chat ID missing. Cannot send alert.")
            return

        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmed", callback_data=f"confirm_{alert.type}"),
                InlineKeyboardButton("❌ False Alarm", callback_data=f"false_{alert.type}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            f"<b>{alert.type} Alert</b>\n"
            f"------------------\n"
            f"{alert.message}\n\n"
            f"Current: {alert.glucose_value:.1f}\n"
        )
        if alert.prediction_30m:
            text += f"Predicted (30m): {alert.prediction_30m:.1f}"

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            self.logger.info(f"Telegram alert sent: {alert.type}")
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")

    async def send_chart(self, photo_path: str, caption: str = ""):
        """Pushes a chart image to the user."""
        if not self.bot or not self.chat_id:
            return

        try:
            with open(photo_path, 'rb') as photo:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
            self.logger.info(f"Telegram chart sent: {photo_path}")
        except Exception as e:
            self.logger.error(f"Failed to send Telegram photo: {e}")

class TelegramApp:
    """The bot application wrapper for handling callbacks/commands."""
    def __init__(self, coordinator=None, audit_logger=None):
        self.app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
        self.coordinator = coordinator
        self.audit_logger = audit_logger
        self.logger = logging.getLogger("Bio-Quant.TelegramApp")
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self._start_cmd))
        self.app.add_handler(CommandHandler("meal", self._meal_cmd))
        self.app.add_handler(CallbackQueryHandler(self._handle_button))

    def authorized_only(func):
        """Decorator to restrict access to the patient and caregiver only."""
        @wraps(func)
        async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            authorized_ids = [config.USER_ID]
            if config.CAREGIVER_ID:
                authorized_ids.append(config.CAREGIVER_ID)
            
            if user.id not in authorized_ids:
                self.logger.warning(f"UNAUTHORIZED ACCESS ATTEMPT: User {user.id} ({user.username}) tried to call {func.__name__}")
                if update.message:
                    await update.message.reply_text("⛔ Access Denied. You are not authorized to control this Metabolic Engine.")
                elif update.callback_query:
                    await update.callback_query.answer("⛔ Access Denied.", show_alert=True)
                return
            return await func(self, update, context)
        return wrapper

    @authorized_only
    async def _start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Bio-Quant Predictor Online. Monitoring signals...")

    @authorized_only
    async def _meal_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /meal [desc] [grams]"""
        if not context.args or len(context.args) < 1:
            await update.message.reply_text("Usage: /meal <description> <grams> (e.g., /meal rice 60)")
            return

        try:
            grams = float(context.args[-1])
            import re
            desc = re.sub(r'[^a-zA-Z0-9\s]', '', " ".join(context.args[:-1])).strip().lower()[:100]

            fast_keywords = ["honey", "sugar", "juice", "liquid", "soda", "gel"]
            gi_type = "LIQUID" if any(k in desc for k in fast_keywords) else "STARCH"

            await update.message.reply_text(f"Logged {grams}g of {desc} ({gi_type} profile). Generating Digital Twin forecast...")

            if self.coordinator:
                await self.coordinator.handle_meal_input(desc, grams, gi_type)

        except ValueError:
            await update.message.reply_text("Please provide grams as a number at the end.")

    @authorized_only
    async def _handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        # FIX: guard against malformed callback data — previously crashed with ValueError
        parts = query.data.split("_", 1)
        if len(parts) != 2:
            self.logger.warning(f"Malformed callback data received: {query.data!r}")
            await query.edit_message_text(text="Unknown action.")
            return

        action, alert_type = parts

        if self.audit_logger:
            task = asyncio.create_task(self.audit_logger.log_feedback(alert_type, action))
            if self.coordinator and hasattr(self.coordinator, 'background_tasks'):
                self.coordinator.background_tasks.add(task)
                task.add_done_callback(self.coordinator.background_tasks.discard)

        if action == "confirm":
            await query.edit_message_text(text=f"✅ Alert {alert_type} acknowledged. Stay safe.")
        else:
            await query.edit_message_text(text=f"⚠️ {alert_type} marked as False Alarm. Logic will be audited.")

    def run(self):
        """Starts the bot in blocking mode (for standalone service)."""
        self.app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    async def test():
        notifier = TelegramNotifier()
        alert = Alert(
            timestamp=datetime.now(timezone.utc),
            type="TEST_ALERT",
            severity="HIGH",
            message="This is a test notification from Bio-Quant.",
            glucose_value=120.0
        )
        await notifier.send_alert(alert)
    # asyncio.run(test())