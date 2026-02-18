import os
import logging
import requests
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums.parse_mode import ParseMode
import asyncio

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN', '452163:AAGTBJKe7YvufexfRN78tFhnTdGywQyUMSX')
CRYPTO_API_URL = 'https://pay.crypt.bot/api/createInvoice'

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def create_crypto_invoice():
    """
    Создание счета в Crypto Bot
    """
    try:
        headers = {
            'Content-Type': 'application/json',
            'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
        }
        
        payload = {
            'asset': 'USDT',  # Используем USDT вместо USD
            'amount': '1',  # Сумма в USDT (эквивалент 1$)
            'description': 'Оплата доступа к боту',
            'hidden_message': 'Спасибо за оплату! Доступ активирован.',
            'paid_btn_name': 'openBot',  # Кнопка после оплаты
            'paid_btn_url': 'https://t.me/your_bot_username',  # Замените на username вашего бота
            'payload': 'test_payment'  # Уникальный идентификатор платежа
        }
        
        logger.info(f"Отправка запроса к Crypto Bot API: {payload}")
        response = requests.post(CRYPTO_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"Ответ от Crypto Bot API: {result}")
        
        if result.get('ok'):
            return result['result']
        else:
            error_msg = result.get('error', 'Неизвестная ошибка')
            logger.error(f"Ошибка Crypto Bot API: {error_msg}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Crypto Bot API: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    """
    Обработчик команды /start
    """
    user_id = message.from_user.id
    username = message.from_user.username or 'пользователь'
    
    logger.info(f"Пользователь @{username} (ID: {user_id}) запустил бота")
    
    # Создаем счет
    invoice = create_crypto_invoice()
    
    if invoice and 'pay_url' in invoice:
        # Создаем клавиатуру с кнопкой для оплаты
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить 1$", url=invoice['pay_url'])],
                [InlineKeyboardButton(text="❓ Проверить оплату", callback_data="check_payment")]
            ]
        )
        
        # Формируем сообщение
        text = (
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"💰 Для доступа к боту необходимо оплатить 1$\n"
            f"📌 Нажми на кнопку ниже, чтобы перейти к оплате через Crypto Bot\n\n"
            f"После успешной оплаты доступ будет активирован автоматически."
        )
        
        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        logger.info(f"Ссылка на оплату отправлена пользователю {user_id}")
        
    else:
        # В случае ошибки создания счета
        error_text = (
            "😔 Извините, произошла ошибка при создании счета.\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору."
        )
        await message.answer(error_text)
        logger.error(f"Не удалось создать счет для пользователя {user_id}")

@dp.callback_query(lambda c: c.data == 'check_payment')
async def process_check_payment(callback_query: types.CallbackQuery):
    """
    Обработчик проверки статуса оплаты
    """
    await callback_query.answer(
        "⚡ Функция проверки оплаты в разработке\n"
        "Обычно оплата обрабатывается автоматически в течение нескольких минут",
        show_alert=True
    )
    
    # Здесь можно добавить проверку статуса платежа через API Crypto Bot
    # Для этого потребуется отдельный endpoint для получения информации о счете

async def main():
    """
    Основная функция запуска бота
    """
    # Проверка наличия токена
    if not BOT_TOKEN:
        logger.error("Не найден BOT_TOKEN в переменных окружения")
        return
    
    logger.info("Бот запущен и готов к работе")
    
    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
