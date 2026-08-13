import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TimedOut,
)
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from functools import wraps

from diabetic.config import config
from diabetic.telegram_bot.decision_matrix import Alert
from diabetic.auth.authorization import is_authorized
from diabetic.ui.glucose_display import (
    format_glucose,
    format_velocity,
    unit_label,
)

DeliveryState = Literal[
    "accepted", "rejected", "rate_limited", "ambiguous", "unavailable"
]


@dataclass(frozen=True)
class AlertDeliveryResult:
    state: DeliveryState
    attempts: int
    reason: Optional[str] = None
    message_id: Optional[int] = None
    retry_after_seconds: Optional[float] = None

    @property
    def accepted(self) -> bool:
        return self.state == "accepted"


def parse_feedback_callback(
    callback_data: str,
) -> tuple[str, str, Optional[str]] | None:
    """Parse current callbacks and messages sent before alert IDs existed."""
    allowed_actions = {"confirm", "false", "neutral"}
    if "|" in callback_data:
        parts = callback_data.split("|", 2)
        if len(parts) == 3 and all(parts) and parts[0] in allowed_actions:
            return parts[0], parts[1], parts[2]
        return None
    legacy = callback_data.split("_", 1)
    if len(legacy) == 2 and all(legacy) and legacy[0] in allowed_actions:
        return legacy[0], legacy[1], None
    return None


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
        self.audit_logger = None
        self.pending_tasks = {}

        if self.token:
            self.bot = Bot(token=self.token)

    async def _auto_review_task(
        self, message_id: int, alert_type: str, alert_id: str
    ):
        try:
            await asyncio.sleep(3600)  # 60 minutes auto-review timeout
            
            # Log as neutral
            if self.audit_logger:
                await self.audit_logger.log_feedback(
                    alert_type, "neutral", alert_id=alert_id
                )
            
            # Edit the message to remove buttons
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=message_id,
                    text=f"⏳ Alert <b>{alert_type}</b> Auto-Reviewed (Neutral).",
                    parse_mode=ParseMode.HTML
                )
                self.logger.info(f"Auto-reviewed alert {alert_type} as neutral.")
            except Exception as error:
                self.logger.error(
                    "Failed to edit message for auto-review: %s",
                    error.__class__.__name__,
                )
                
        except asyncio.CancelledError:
            # User clicked the button, task was cancelled
            pass
        finally:
            self.pending_tasks.pop(message_id, None)

    @staticmethod
    def _retry_seconds(error: RetryAfter) -> float:
        retry_after = error.retry_after
        if isinstance(retry_after, timedelta):
            return max(0.0, retry_after.total_seconds())
        return max(0.0, float(retry_after))

    async def send_alert(
        self,
        alert: Alert,
        *,
        max_attempts: int = 2,
        max_retry_delay_seconds: float = 5.0,
    ) -> AlertDeliveryResult:
        """Attempt at-least-once Telegram delivery with explicit ambiguity."""
        if not self.bot or not self.chat_id:
            self.logger.error("Telegram delivery unavailable: missing configuration.")
            return AlertDeliveryResult(
                state="unavailable", attempts=0, reason="missing_configuration"
            )

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirmed",
                    callback_data=f"confirm|{alert.type}|{alert.alert_id}",
                ),
                InlineKeyboardButton(
                    "❌ False Alarm",
                    callback_data=f"false|{alert.type}|{alert.alert_id}",
                ),
                InlineKeyboardButton(
                    "Neutral",
                    callback_data=f"neutral|{alert.type}|{alert.alert_id}",
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            f"<b>{alert.type} Alert</b>\n"
            f"------------------\n"
            f"{alert.message}\n\n"
            f"Current: {format_glucose(alert.glucose_value)} {unit_label()}\n"
            f"Alert ID: <code>{alert.alert_id}</code>\n"
        )
        if alert.prediction_15m:
            text += f"📊 <b>Horizons (Predicted)</b>\n"
            unit = unit_label()
            text += f"├ 15m: {format_glucose(alert.prediction_15m)} {unit}\n"
            text += f"├ 30m: {format_glucose(alert.prediction_30m)} {unit}\n"
            text += f"└ 60m: {format_glucose(alert.prediction_60m)} {unit}\n\n"
            if alert.confidence_index is not None:
                text += f"📈 <b>Signal quality:</b> {alert.confidence_index*100:.0f}%\n"
        elif alert.prediction_30m:
            text += (
                f"Predicted (30m): {format_glucose(alert.prediction_30m)} "
                f"{unit_label()}\n"
            )

        for attempt in range(1, max(1, max_attempts) + 1):
            try:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
                self.logger.info(
                    "Telegram alert accepted: type=%s alert_id=%s",
                    alert.type,
                    alert.alert_id,
                )
                task = asyncio.create_task(
                    self._auto_review_task(
                        msg.message_id, alert.type, alert.alert_id
                    )
                )
                self.pending_tasks[msg.message_id] = task
                return AlertDeliveryResult(
                    state="accepted",
                    attempts=attempt,
                    message_id=msg.message_id,
                )
            except RetryAfter as error:
                retry_seconds = self._retry_seconds(error)
                if (
                    attempt >= max_attempts
                    or retry_seconds > max_retry_delay_seconds
                ):
                    return AlertDeliveryResult(
                        state="rate_limited",
                        attempts=attempt,
                        reason=error.__class__.__name__,
                        retry_after_seconds=retry_seconds,
                    )
                await asyncio.sleep(retry_seconds)
            except (BadRequest, Forbidden, InvalidToken) as error:
                return AlertDeliveryResult(
                    state="rejected",
                    attempts=attempt,
                    reason=error.__class__.__name__,
                )
            except (TimedOut, NetworkError) as error:
                if attempt >= max_attempts:
                    return AlertDeliveryResult(
                        state="ambiguous",
                        attempts=attempt,
                        reason=error.__class__.__name__,
                    )
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.error(
                    "Telegram delivery unavailable: %s", error.__class__.__name__
                )
                return AlertDeliveryResult(
                    state="unavailable",
                    attempts=attempt,
                    reason=error.__class__.__name__,
                )
        return AlertDeliveryResult(
            state="unavailable", attempts=max_attempts, reason="retry_exhausted"
        )

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
        
        # Wave 7: Command Menu Registration
        async def post_init(application):
            commands = [
                BotCommand("start", "Boot the Metabolic Engine HUD"),
                BotCommand("meal", "Log carbs [desc] [grams] (e.g. /meal rice 60)"),
                BotCommand("status", "Get current metabolic engine status")
            ]
            await application.bot.set_my_commands(commands)
            self.logger.info("Telegram command menu registered successfully.")

        self.app.post_init = post_init

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self._start_cmd))
        self.app.add_handler(CommandHandler("meal", self._meal_cmd))
        self.app.add_handler(CommandHandler("status", self._status_cmd))
        self.app.add_handler(CallbackQueryHandler(self._handle_button))

    def authorized_only(func):
        """Decorator to restrict access to the patient and caregiver only."""
        @wraps(func)
        async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            # Authorization is limited to the singleton patient/caregiver pair.
            authorized = await is_authorized(user.id)

            if not authorized:
                self.logger.warning(f"UNAUTHORIZED ACCESS ATTEMPT: User {user.id} ({user.username}) tried to call {func.__name__}")
                denied_msg = (
                    "⛔ <b>Access Denied</b>\n\n"
                    "Your Vessel is not registered with this Metabolic Engine.\n"
                    "Please contact the administrator or use the Bio-Quant TWA to pair your device."
                )
                if update.message:
                    await update.message.reply_text(denied_msg, parse_mode=ParseMode.HTML)
                elif update.callback_query:
                    await update.callback_query.answer("⛔ Access Denied. Vessel not registered.", show_alert=True)
                return
            return await func(self, update, context)
        return wrapper

    @authorized_only
    async def _start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(" Predictor Online. Monitoring signals")

    @authorized_only
    async def _status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /status"""
        if not self.coordinator:
            await update.message.reply_text("Engine not connected.")
            return

        snapshot = self.coordinator.snapshots[-1] if self.coordinator.snapshots else None
        if not snapshot:
            await update.message.reply_text("No readings captured yet.")
            return

        status_text = (
            f"📊 <b>Metabolic Status</b>\n"
            f"------------------\n"
            f"Current: {format_glucose(snapshot.filtered_value)} {unit_label()}\n"
            f"Velocity: {format_velocity(snapshot.velocity)} {unit_label()}/min\n"
            f"Signal Quality: {snapshot.confidence_index*100:.0f}%\n"
            f"Active Carbs: {snapshot.active_carbs:.1f}g\n"
            f"Active Insulin: {snapshot.active_insulin:.2f}U\n"
        )
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)

    @authorized_only
    async def _meal_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /meal [desc] [grams]"""
        if not context.args or len(context.args) < 1:
            await update.message.reply_text("Usage: /meal <description> <grams> (e.g., /meal rice 60)")
            return

        try:
            import math
            grams = float(context.args[-1])
            # Fix H8: Physiological input bounds — reject implausible carb values and NaN/Inf
            if math.isnan(grams) or math.isinf(grams) or grams <= 0 or grams > 500:
                await update.message.reply_text(
                    f"Invalid portion size: {grams}g. Please enter a value between 1 and 500 grams."
                )
                return
            import re
            desc = re.sub(r'[^a-zA-Z0-9\s]', '', " ".join(context.args[:-1])).strip().lower()[:100]

            LIQUID_KEYWORDS = {
                "honey", "sugar", "juice", "liquid", "soda", "gel",
                "energy drink", "sports drink", "syrup", "smoothie", "shake"
            }
            SLOW_KEYWORDS = {
                "oats", "beans", "lentils", "chickpea", "barley", "quinoa"
            }

            if any(k in desc for k in LIQUID_KEYWORDS):
                gi_type = "LIQUID"
            elif any(k in desc for k in SLOW_KEYWORDS):
                gi_type = "SLOW_STARCH"
            else:
                gi_type = "STARCH"

            await update.message.reply_text(f"Logged {grams}g of {desc} ({gi_type} profile). Syncing with Nightscout...")

            if self.coordinator:
                # 1. Local update for immediate twin forecast
                await self.coordinator.handle_meal_input(desc, grams, gi_type)
                # 2. Nightscout sync
                if hasattr(self.coordinator.client, 'post_treatment'):
                    success = await self.coordinator.client.post_treatment(
                        event_type="Meal Bolus",
                        notes=f"Bio-Quant Logged: {desc}",
                        carbs=grams
                    )
                    if success:
                        await update.message.reply_text("✅ Nightscout sync complete.")
                    else:
                        await update.message.reply_text("⚠️ Nightscout sync failed. Local only.")

        except ValueError:
            await update.message.reply_text("Please provide grams as a number at the end.")

    @authorized_only
    async def _handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        parsed = parse_feedback_callback(query.data)
        if parsed is None:
            self.logger.warning("Malformed callback data received.")
            await query.edit_message_text(text="Unknown action.")
            return
        action, alert_type, alert_id = parsed

        # Cancel auto-review task if it exists
        message_id = query.message.message_id
        if self.coordinator and hasattr(self.coordinator, 'notifier'):
            notifier = self.coordinator.notifier
            if hasattr(notifier, 'pending_tasks') and message_id in notifier.pending_tasks:
                notifier.pending_tasks[message_id].cancel()
                notifier.pending_tasks.pop(message_id, None)

        if self.audit_logger:
            task = asyncio.create_task(
                self.audit_logger.log_feedback(
                    alert_type, action, alert_id=alert_id
                )
            )
            if self.coordinator and hasattr(self.coordinator, 'background_tasks'):
                self.coordinator.background_tasks.add(task)
                task.add_done_callback(self.coordinator.background_tasks.discard)

        if action == "confirm":
            await query.edit_message_text(text=f"✅ Alert {alert_type} acknowledged. Stay safe.")
        elif action == "neutral":
            await query.edit_message_text(text=f"⚪ Alert {alert_type} received (Neutral). No sensitivity change.")
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
