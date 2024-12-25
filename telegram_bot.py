import logging
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey
from solana.transaction import Transaction

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

MY_WALLET_ADDRESS = "3CY3K5tq9vLBiQCGa5gaAtrejRkKcxcv2QmhkEF9sKxc"

PAYMENT_RATES = {
    10: 0.01,
    25: 0.025,
    50: 0.05,
    75: 0.075,
    100: 0.1,
    250: 0.25,
    500: 0.5,
    750: 0.75,
    1000: 1.0,
}

SOLANA_ADDRESS_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{44}$"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Start Sending Messages", callback_data='start_process')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        """
        🎉 Welcome to the PumpFunReplyBot! 🎉
        
        This bot allows you to interact and perform actions on pump.fun. Please use it responsibly and have fun!

        Click the button below to start.
        """,
        reply_markup=reply_markup
    )

async def start_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please provide your token address in the format: Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump")
    context.user_data['awaiting_token'] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_token'):
        token_address = update.message.text

        if re.match(SOLANA_ADDRESS_PATTERN, token_address):
            context.user_data['token_address'] = token_address
            context.user_data['awaiting_token'] = False

            message = (
                "💰 Select the number of messages you want to send and the associated payment plan:\n\n"
                "1️⃣ 10 messages for 0.01 SOL – Starter Plan 🔰\n"
                "2️⃣ 25 messages for 0.025 SOL – Growth Plan ⚡\n"
                "3️⃣ 50 messages for 0.05 SOL – Power Plan 💪\n"
                "4️⃣ 75 messages for 0.075 SOL – Momentum Plan 🔥 🔥\n"
                "5️⃣ 100 messages for 0.1 SOL – Mastery Plan 💥\n"
                "6️⃣ 250 messages for 0.25 SOL – Champion Plan 🚀\n"
                "7️⃣ 500 messages for 0.5 SOL – Prodigy Plan 🌟\n"
                "8️⃣ 750 messages for 0.75 SOL – Elite Plan 🎯\n"
                "9️⃣ 1000 messages for 1.0 SOL – Ultimate Plan 💣\n"
                "\nSelect the amount of messages you want to send:"
            )
            keyboard = [
                [InlineKeyboardButton(str(x), callback_data=f'msg_count_{x}') for x in [10, 25, 50]],
                [InlineKeyboardButton(str(x), callback_data=f'msg_count_{x}') for x in [75, 100, 250]],
                [InlineKeyboardButton(str(x), callback_data=f'msg_count_{x}') for x in [500, 750, 1000]]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text("❗ Invalid token address. Please provide a valid Solana address.")

async def select_message_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith('msg_count_'):
        message_count = int(query.data.split('_')[2])
        context.user_data['message_count'] = message_count
        payment_amount = PAYMENT_RATES.get(message_count)

        await query.edit_message_text(f"✅ Token Address: {context.user_data['token_address']}\n"
                                      f"📨 Messages: {message_count}\n\n"
                                      f"💰 Please send {payment_amount} SOL to my wallet address: {MY_WALLET_ADDRESS}\n"
                                      f"Then provide your wallet address for payment verification.")

        context.user_data['awaiting_payment'] = True

        asyncio.create_task(payment_timeout(update.effective_chat.id, context))

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_payment'):
        wallet_address = update.message.text
        payment_amount = PAYMENT_RATES.get(context.user_data['message_count'])

        if await verify_payment(wallet_address, payment_amount):
            context.user_data['awaiting_payment'] = False
            await update.message.reply_text("🎉 Payment verified! Your spamming has now started...")

            message_count = context.user_data['message_count']
            await start_spamming(update.effective_chat.id, message_count)
        else:
            await update.message.reply_text(f"❌ Payment verification failed. Please ensure you've sent {payment_amount} SOL to {MY_WALLET_ADDRESS} and try again.")

async def payment_timeout(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(600)  # Wait for 10 minutes
    if context.user_data.get('awaiting_payment'):
        await context.bot.send_message(chat_id, f"⏳ No payment detected. Please send the required amount of SOL to the following address: {MY_WALLET_ADDRESS} and try again.")
        context.user_data['awaiting_payment'] = False

async def verify_payment(wallet_address: str, amount: float, retries: int = 3):
    logger.info(f"Verifying payment from {wallet_address} for {amount} SOL...")

    async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
        try:
            public_key = PublicKey(wallet_address)
            for _ in range(retries):  # Retry mechanism
                transactions = await client.get_confirmed_signature_for_address2(public_key, limit=10)

                for transaction in transactions['result']:
                    tx_signature = transaction['signature']
                    tx_details = await client.get_confirmed_transaction(tx_signature)

                    if tx_details and tx_details['result']:
                        post_balance = tx_details['result']['meta']['postBalances'][0] / 1e9  # Convert lamports to SOL
                        pre_balance = tx_details['result']['meta']['preBalances'][0] / 1e9
                        amount_transferred = pre_balance - post_balance

                        if amount_transferred == amount and tx_details['result']['transaction']['message']['accountKeys'][1] == MY_WALLET_ADDRESS:
                            logger.info("Payment verified successfully.")
                            return True

                logger.info("Payment not verified, retrying...")

        except Exception as e:
            logger.error(f"Error verifying payment: {e}")

    logger.info("Payment verification failed.")
    return False

async def start_spamming(chat_id: int, message_count: int):
    # Simulate spamming: send multiple messages
    for i in range(message_count):
        await asyncio.sleep(2)  # Simulate delay between messages
        await application.bot.send_message(chat_id, f"🗣 Message {i + 1} of {message_count} sent!")
    await application.bot.send_message(chat_id, "🎉 Spamming completed successfully! All messages have been sent.")

def main():
    global application
    application = ApplicationBuilder().token("7230925036:AAHKMMdMwzxtPLaZByUF1BiDbwoO8EMz76M").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start_process, pattern='start_process'))
    application.add_handler(CallbackQueryHandler(select_message_count, pattern='msg_count_\\d+'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment))

    application.run_polling()

if __name__ == "__main__":
    main()
