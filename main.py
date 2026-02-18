import os
import logging
import sqlite3
import asyncio
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardMarkup, 
    KeyboardButton, BotCommand, BotCommandScopeDefault
)
from aiogram.enums.parse_mode import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

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
CRYPTO_API_URL = 'https://pay.crypt.bot/api/'
ADMIN_ID = 7973988177
USDT_TO_RUB = 80
PAYMENT_EXPIRY_MINUTES = 30

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Хранилище для отслеживания платежей
pending_payments = {}

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_newsletter = State()
    waiting_for_price_change = State()
    waiting_for_product_name = State()
    waiting_for_product_price = State()
    waiting_for_product_type = State()
    waiting_for_product_limit = State()
    waiting_for_instruction = State()
    waiting_for_proxy_data = State()
    waiting_for_free_proxy_type = State()
    waiting_for_free_proxy_key = State()
    waiting_for_free_proxy_instruction = State()
    waiting_for_product_data = State()
    waiting_for_product_id_for_data = State()
    waiting_for_product_id_for_instruction = State()
    waiting_for_price_product_id = State()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  joined_date TEXT,
                  balance REAL DEFAULT 0,
                  is_admin INTEGER DEFAULT 0)''')
    
    # Таблица товаров
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  type TEXT,
                  price_rub REAL,
                  price_usdt REAL,
                  limit_users INTEGER,
                  current_users INTEGER DEFAULT 0,
                  instruction TEXT,
                  data TEXT,
                  is_active INTEGER DEFAULT 1)''')
    
    # Таблица прокси-данных
    c.execute('''CREATE TABLE IF NOT EXISTS proxy_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_id INTEGER,
                  proxy_data TEXT,
                  is_available INTEGER DEFAULT 1,
                  used_by INTEGER,
                  used_date TEXT,
                  FOREIGN KEY (product_id) REFERENCES products (id))''')
    
    # Таблица VPN данных
    c.execute('''CREATE TABLE IF NOT EXISTS vpn_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_id INTEGER,
                  vpn_data TEXT,
                  is_available INTEGER DEFAULT 1,
                  used_by INTEGER,
                  used_date TEXT,
                  FOREIGN KEY (product_id) REFERENCES products (id))''')
    
    # Таблица покупок
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  product_id INTEGER,
                  proxy_item_id INTEGER,
                  invoice_id TEXT,
                  purchase_date TEXT,
                  expiry_date TEXT,
                  status TEXT,
                  data TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (user_id),
                  FOREIGN KEY (product_id) REFERENCES products (id),
                  FOREIGN KEY (proxy_item_id) REFERENCES proxy_items (id))''')
    
    # Таблица бесплатных ключей
    c.execute('''CREATE TABLE IF NOT EXISTS free_keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  type TEXT,
                  key TEXT,
                  instruction TEXT,
                  is_available INTEGER DEFAULT 1,
                  used_by INTEGER,
                  used_date TEXT)''')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# Добавление админа
def add_admin():
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, is_admin) VALUES (?, ?, ?)",
              (ADMIN_ID, 'admin', 1))
    conn.commit()
    conn.close()

# Добавление начальных товаров
def add_initial_products():
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Проверяем, есть ли уже товары
    c.execute("SELECT COUNT(*) FROM products")
    count = c.fetchone()[0]
    
    if count == 0:
        products = [
            ('Общие прокси (до 3 чел)', 'proxy_shared', 3, 3/USDT_TO_RUB, 3, 0, 'Настройте прокси в вашем браузере или приложении', '', 1),
            ('Индивидуальные прокси', 'proxy_individual', 10, 10/USDT_TO_RUB, 1, 0, 'Настройте прокси в вашем браузере или приложении', '', 1),
            ('VPN на 3 дня', 'vpn_3days', 3, 3/USDT_TO_RUB, 3, 0, 'Скачайте приложение и введите полученные данные', '', 1),
            ('VPN на 30 дней', 'vpn_30days', 30, 30/USDT_TO_RUB, 3, 0, 'Скачайте приложение и введите полученные данные', '', 1)
        ]
        c.executemany('''INSERT INTO products 
                        (name, type, price_rub, price_usdt, limit_users, current_users, instruction, data, is_active) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', products)
        conn.commit()
        logger.info("Начальные товары добавлены")
    
    conn.close()

# Функции для работы с Crypto Bot API
def create_crypto_invoice(amount_usdt, description, payload):
    """
    Создание счета в Crypto Bot
    """
    try:
        headers = {
            'Content-Type': 'application/json',
            'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
        }
        
        data = {
            'asset': 'USDT',
            'amount': str(amount_usdt),
            'description': description,
            'hidden_message': 'Спасибо за покупку! Товар будет выдан автоматически.',
            'payload': payload,
            'expires_in': PAYMENT_EXPIRY_MINUTES * 60
        }
        
        logger.info(f"Создание счета: {data}")
        response = requests.post(
            f"{CRYPTO_API_URL}createInvoice", 
            headers=headers, 
            json=data, 
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        
        if result.get('ok'):
            return result['result']
        else:
            logger.error(f"Ошибка Crypto Bot API: {result.get('error')}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при создании счета: {e}")
        return None

def check_invoice_status(invoice_id):
    """
    Проверка статуса счета
    """
    try:
        headers = {
            'Content-Type': 'application/json',
            'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
        }
        
        params = {
            'invoice_ids': invoice_id
        }
        
        response = requests.get(
            f"{CRYPTO_API_URL}getInvoices",
            headers=headers,
            params=params,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        
        if result.get('ok') and result.get('result', {}).get('items'):
            invoice = result['result']['items'][0]
            return invoice.get('status')
        else:
            logger.error(f"Не удалось получить статус счета {invoice_id}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса: {e}")
        return None

# Фоновая проверка платежей
async def payment_checker():
    """
    Фоновая задача для проверки статусов платежей
    """
    while True:
        try:
            for user_id, payment_data in list(pending_payments.items()):
                if payment_data['status'] == 'pending':
                    # Проверяем не истекло ли время
                    if datetime.now() > payment_data['expires_at']:
                        payment_data['status'] = 'expired'
                        logger.info(f"Платеж для пользователя {user_id} истек")
                        continue
                    
                    # Проверяем статус в API
                    status = check_invoice_status(payment_data['invoice_id'])
                    
                    if status == 'paid':
                        payment_data['status'] = 'paid'
                        
                        # Выдаем товар
                        await deliver_product(user_id, payment_data['product_id'])
                        
                    elif status in ['expired', 'cancelled']:
                        payment_data['status'] = status
            
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"Ошибка в payment_checker: {e}")
            await asyncio.sleep(30)

# Выдача товара после оплаты
async def deliver_product(user_id, product_id):
    """
    Выдача товара пользователю после успешной оплаты
    """
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Получаем информацию о товаре
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    
    if not product:
        logger.error(f"Товар {product_id} не найден")
        conn.close()
        return
    
    # Определяем тип товара и выдаем соответствующие данные
    if 'proxy' in product[2]:
        # Выдаем прокси
        c.execute('''SELECT id, proxy_data FROM proxy_items 
                     WHERE product_id = ? AND is_available = 1 
                     LIMIT 1''', (product_id,))
        item = c.fetchone()
        
        if item:
            # Помечаем как использованное
            c.execute('''UPDATE proxy_items 
                         SET is_available = 0, used_by = ?, used_date = ? 
                         WHERE id = ?''',
                      (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item[0]))
            
            # Записываем покупку
            c.execute('''INSERT INTO purchases 
                         (user_id, product_id, proxy_item_id, purchase_date, status, data)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user_id, product_id, item[0],
                       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       'active', item[1]))
            
            data_to_send = item[1]
            product_type = "proxy"
            
    else:  # VPN
        # Выдаем VPN
        c.execute('''SELECT id, vpn_data FROM vpn_items 
                     WHERE product_id = ? AND is_available = 1 
                     LIMIT 1''', (product_id,))
        item = c.fetchone()
        
        if item:
            # Определяем срок действия
            if product[2] == 'vpn_3days':
                expiry = datetime.now() + timedelta(days=3)
            else:
                expiry = datetime.now() + timedelta(days=30)
            
            # Помечаем как использованное
            c.execute('''UPDATE vpn_items 
                         SET is_available = 0, used_by = ?, used_date = ? 
                         WHERE id = ?''',
                      (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), item[0]))
            
            # Записываем покупку
            c.execute('''INSERT INTO purchases 
                         (user_id, product_id, purchase_date, expiry_date, status, data)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user_id, product_id,
                       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       expiry.strftime("%Y-%m-%d %H:%M:%S"),
                       'active', item[1]))
            
            data_to_send = item[1]
            product_type = "vpn"
            expiry_text = f"\n📅 Срок действия до: {expiry.strftime('%d.%m.%Y')}"
    
    conn.commit()
    conn.close()
    
    if item:
        # Отправляем уведомление пользователю
        try:
            text = (
                f"✅ <b>Оплата получена!</b>\n\n"
                f"📦 <b>Товар:</b> {product[1]}\n\n"
                f"🔑 <b>Ваши данные:</b>\n<code>{data_to_send}</code>\n\n"
                f"📝 <b>Инструкция:</b>\n{product[7] or 'Инструкция отсутствует'}"
            )
            
            if product_type == "vpn":
                text += expiry_text
            
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            logger.info(f"Товар выдан пользователю {user_id}")
            
        except Exception as e:
            logger.error(f"Не удалось отправить товар пользователю {user_id}: {e}")
    else:
        logger.error(f"Нет доступных товаров для продукта {product_id}")
        await bot.send_message(user_id, "❌ Произошла ошибка при выдаче товара. Обратитесь к администратору.")

# Главное меню
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🛒 Купить прокси"))
    builder.add(KeyboardButton(text="🔒 Купить VPN"))
    builder.add(KeyboardButton(text="👤 Профиль"))
    builder.add(KeyboardButton(text="🎁 Бесплатные"))
    builder.add(KeyboardButton(text="⚙️ Админ панель"))
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

# Инлайн клавиатуры
def back_button(callback_data="back_to_main"):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=callback_data))
    return builder.as_markup()

def admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_newsletter")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Изменить цены", callback_data="admin_prices"),
        InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product")
    )
    builder.row(
        InlineKeyboardButton(text="📝 Инструкции", callback_data="admin_instructions"),
        InlineKeyboardButton(text="🔑 Добавить данные", callback_data="admin_add_data")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Бесплатные ключи", callback_data="admin_free_keys"),
        InlineKeyboardButton(text="📦 Управление товарами", callback_data="admin_manage_products")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

# Проверка админа
def is_admin(user_id):
    return user_id == ADMIN_ID

# Получить количество доступных прокси
def get_available_proxy_count(product_id):
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM proxy_items WHERE product_id = ? AND is_available = 1", (product_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

# Получить количество доступных VPN
def get_available_vpn_count(product_id):
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM vpn_items WHERE product_id = ? AND is_available = 1", (product_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    first_name = message.from_user.first_name
    
    # Добавляем пользователя в БД
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date) 
                 VALUES (?, ?, ?, ?)''',
              (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    welcome_text = (
        f"🐒 Добро пожаловать в Dev Monkey, {first_name}!\n\n"
        f"🔹 Здесь вы можете приобрести качественные прокси и VPN\n"
        f"🔹 Курс: 1 USDT = {USDT_TO_RUB}₽\n"
        f"🔹 Оплата через Crypto Bot\n"
        f"🔹 Все товары выдаются автоматически после оплаты\n\n"
        f"Используйте кнопки ниже для навигации:"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# Обработчики текстовых сообщений
@dp.message(F.text == "🛒 Купить прокси")
async def menu_buy_proxy(message: Message):
    await show_proxy_products(message)

@dp.message(F.text == "🔒 Купить VPN")
async def menu_buy_vpn(message: Message):
    await show_vpn_products(message)

@dp.message(F.text == "👤 Профиль")
async def menu_profile(message: Message):
    await show_profile(message)

@dp.message(F.text == "🎁 Бесплатные")
async def menu_free(message: Message):
    await show_free_menu(message)

@dp.message(F.text == "⚙️ Админ панель")
async def menu_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ панели")
        return
    
    await message.answer(
        "⚙️ Админ панель\nВыберите действие:",
        reply_markup=admin_keyboard()
    )

# Показать прокси товары
async def show_proxy_products(message: Message):
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE type LIKE 'proxy%' AND is_active=1")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await message.answer("😔 Прокси временно отсутствуют")
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        available_count = get_available_proxy_count(product[0])
        status = f"✅ {available_count} шт" if available_count > 0 else "❌ Нет в наличии"
        
        builder.row(InlineKeyboardButton(
            text=f"📦 {product[1]} - {product[3]}₽ ({status})",
            callback_data=f"view_proxy_{product[0]}"
        ))
    
    await message.answer(
        "🛒 Доступные прокси:",
        reply_markup=builder.as_markup()
    )

# Показать VPN товары
async def show_vpn_products(message: Message):
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE type LIKE 'vpn%' AND is_active=1")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await message.answer("😔 VPN временно отсутствуют")
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        available_count = get_available_vpn_count(product[0])
        status = f"✅ {available_count} шт" if available_count > 0 else "❌ Нет в наличии"
        
        builder.row(InlineKeyboardButton(
            text=f"🔒 {product[1]} - {product[3]}₽ ({status})",
            callback_data=f"view_vpn_{product[0]}"
        ))
    
    await message.answer(
        "🔒 Доступные VPN:",
        reply_markup=builder.as_markup()
    )

# Просмотр прокси товара
@dp.callback_query(F.data.startswith("view_proxy_"))
async def view_proxy_product(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()
    
    if not product:
        await callback.answer("Товар не найден")
        return
    
    available_count = get_available_proxy_count(product_id)
    
    text = (
        f"📦 <b>{product[1]}</b>\n\n"
        f"💰 Цена: {product[3]}₽ ({product[4]:.4f} USDT)\n"
        f"📊 В наличии: {available_count} шт\n"
        f"👥 Лимит на один прокси: {product[5]} чел\n\n"
        f"{product[7] or 'Инструкция отсутствует'}"
    )
    
    builder = InlineKeyboardBuilder()
    if available_count > 0:
        builder.row(InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_proxy_{product_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_proxy"))
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()

# Просмотр VPN товара
@dp.callback_query(F.data.startswith("view_vpn_"))
async def view_vpn_product(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()
    
    if not product:
        await callback.answer("Товар не найден")
        return
    
    available_count = get_available_vpn_count(product_id)
    
    text = (
        f"🔒 <b>{product[1]}</b>\n\n"
        f"💰 Цена: {product[3]}₽ ({product[4]:.4f} USDT)\n"
        f"📊 В наличии: {available_count} шт\n"
        f"👥 Лимит на один VPN: {product[5]} чел\n\n"
        f"{product[7] or 'Инструкция отсутствует'}"
    )
    
    builder = InlineKeyboardBuilder()
    if available_count > 0:
        builder.row(InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_vpn_{product_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_vpn"))
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()

# Покупка прокси (создание счета)
@dp.callback_query(F.data.startswith("buy_proxy_"))
async def buy_proxy(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    # Проверяем наличие
    available_count = get_available_proxy_count(product_id)
    if available_count == 0:
        await callback.answer("❌ Товар закончился", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()
    
    # Создаем счет в Crypto Bot
    payload = f"proxy_{product_id}_{user_id}_{datetime.now().timestamp()}"
    invoice = create_crypto_invoice(
        amount_usdt=product[4],
        description=f"Покупка: {product[1]}",
        payload=payload
    )
    
    if invoice:
        # Сохраняем информацию о платеже
        pending_payments[user_id] = {
            'invoice_id': invoice['invoice_id'],
            'product_id': product_id,
            'status': 'pending',
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(minutes=PAYMENT_EXPIRY_MINUTES),
            'pay_url': invoice['pay_url']
        }
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url']))
        builder.row(InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{product_id}"))
        builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_proxy"))
        
        await callback.message.edit_text(
            f"🧾 <b>Счет на оплату</b>\n\n"
            f"Товар: {product[1]}\n"
            f"Сумма: {product[3]}₽ ({product[4]:.4f} USDT)\n\n"
            f"⏳ Счет действителен {PAYMENT_EXPIRY_MINUTES} минут\n\n"
            f"После оплаты нажмите кнопку 'Проверить оплату'",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.edit_text(
            "❌ Ошибка при создании счета. Попробуйте позже.",
            reply_markup=back_button("back_to_proxy")
        )
    
    await callback.answer()

# Покупка VPN (создание счета)
@dp.callback_query(F.data.startswith("buy_vpn_"))
async def buy_vpn(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    # Проверяем наличие
    available_count = get_available_vpn_count(product_id)
    if available_count == 0:
        await callback.answer("❌ Товар закончился", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()
    
    # Создаем счет в Crypto Bot
    payload = f"vpn_{product_id}_{user_id}_{datetime.now().timestamp()}"
    invoice = create_crypto_invoice(
        amount_usdt=product[4],
        description=f"Покупка: {product[1]}",
        payload=payload
    )
    
    if invoice:
        # Сохраняем информацию о платеже
        pending_payments[user_id] = {
            'invoice_id': invoice['invoice_id'],
            'product_id': product_id,
            'status': 'pending',
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(minutes=PAYMENT_EXPIRY_MINUTES),
            'pay_url': invoice['pay_url']
        }
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url']))
        builder.row(InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{product_id}"))
        builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_vpn"))
        
        await callback.message.edit_text(
            f"🧾 <b>Счет на оплату</b>\n\n"
            f"Товар: {product[1]}\n"
            f"Сумма: {product[3]}₽ ({product[4]:.4f} USDT)\n\n"
            f"⏳ Счет действителен {PAYMENT_EXPIRY_MINUTES} минут\n\n"
            f"После оплаты нажмите кнопку 'Проверить оплату'",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.edit_text(
            "❌ Ошибка при создании счета. Попробуйте позже.",
            reply_markup=back_button("back_to_vpn")
        )
    
    await callback.answer()

# Проверка оплаты
@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if user_id not in pending_payments:
        await callback.answer("❌ Активный платеж не найден", show_alert=True)
        return
    
    payment_data = pending_payments[user_id]
    
    if payment_data['status'] == 'paid':
        await callback.answer("✅ Платеж уже обработан", show_alert=True)
        return
    
    if payment_data['status'] == 'expired':
        await callback.message.edit_text(
            "⌛ Срок действия счета истек.\n"
            "Создайте новый заказ.",
            reply_markup=back_button("back_to_main")
        )
        await callback.answer()
        return
    
    # Проверяем статус в API
    status = check_invoice_status(payment_data['invoice_id'])
    
    if status == 'paid':
        payment_data['status'] = 'paid'
        
        # Выдаем товар
        await deliver_product(user_id, product_id)
        
        await callback.message.edit_text(
            "✅ <b>Оплата успешно получена!</b>\n\n"
            "Товар был отправлен в личные сообщения.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_button("back_to_main")
        )
        
    elif status == 'pending':
        time_left = payment_data['expires_at'] - datetime.now()
        minutes_left = int(time_left.total_seconds() / 60)
        
        await callback.answer(
            f"⏳ Платеж еще не получен.\n"
            f"Осталось времени: {minutes_left} мин.",
            show_alert=True
        )
    else:
        await callback.answer(
            "❌ Платеж не найден или истек.\n"
            "Создайте новый заказ.",
            show_alert=True
        )

# Профиль
async def show_profile(message: Message):
    user_id = message.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Информация о пользователе
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    
    # История покупок
    c.execute('''SELECT p.name, pu.purchase_date, pu.expiry_date, pu.status, pu.data 
                 FROM purchases pu
                 JOIN products p ON pu.product_id = p.id
                 WHERE pu.user_id = ?
                 ORDER BY pu.purchase_date DESC''', (user_id,))
    purchases = c.fetchall()
    
    # Бесплатные ключи
    c.execute("SELECT type, key, used_date FROM free_keys WHERE used_by = ?", (user_id,))
    free_keys = c.fetchall()
    
    conn.close()
    
    profile_text = f"👤 <b>Профиль пользователя</b>\n\n"
    profile_text += f"🆔 ID: <code>{user_id}</code>\n"
    profile_text += f"📅 Дата регистрации: {user[3]}\n\n"
    
    profile_text += "📊 <b>Последние покупки:</b>\n"
    if purchases:
        for p in purchases[:5]:
            status_emoji = "✅" if p[3] == 'active' else "❌"
            profile_text += f"{status_emoji} {p[0]} - {p[1]}\n"
            profile_text += f"   Данные: <code>{p[4]}</code>\n"
    else:
        profile_text += "Покупок пока нет\n"
    
    profile_text += "\n🎁 <b>Полученные бесплатные ключи:</b>\n"
    if free_keys:
        for fk in free_keys:
            profile_text += f"• {fk[0]}: <code>{fk[1]}</code>\n"
    else:
        profile_text += "Бесплатных ключей пока нет\n"
    
    await message.answer(profile_text, parse_mode=ParseMode.HTML)

# Бесплатные ключи
async def show_free_menu(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🖧 Бесплатный PROXY", callback_data="free_proxy"),
        InlineKeyboardButton(text="🔒 Бесплатный VPN", callback_data="free_vpn")
    )
    
    await message.answer(
        "🎁 Выберите, что хотите получить бесплатно:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.in_(["free_proxy", "free_vpn"]))
async def get_free_key(callback: CallbackQuery):
    key_type = "proxy" if callback.data == "free_proxy" else "vpn"
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Ищем неиспользованный ключ
    c.execute('''SELECT * FROM free_keys 
                 WHERE type = ? AND is_available = 1 
                 LIMIT 1''', (key_type,))
    key = c.fetchone()
    
    if key:
        # Отмечаем ключ как использованный
        c.execute('''UPDATE free_keys 
                     SET is_available = 0, used_by = ?, used_date = ? 
                     WHERE id = ?''',
                  (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), key[0]))
        conn.commit()
        
        await callback.message.edit_text(
            f"✅ Ваш бесплатный {key_type.upper()}:\n\n"
            f"🔑 <b>Ключ/ссылка:</b>\n<code>{key[2]}</code>\n\n"
            f"📝 <b>Инструкция:</b>\n{key[3]}\n\n"
            f"Сохраните эти данные!",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            f"😔 К сожалению, бесплатные {key_type.upper()} закончились.\n"
            f"Попробуйте позже или приобретите платную версию."
        )
    
    conn.close()
    await callback.answer()

# ============= АДМИН ПАНЕЛЬ =============

# Статистика
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Общая статистика
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users WHERE joined_date >= date('now', '-1 day')")
    new_users_today = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM purchases WHERE status = 'active'")
    active_purchases = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM purchases WHERE date(purchase_date) = date('now')")
    purchases_today = c.fetchone()[0]
    
    c.execute('''SELECT SUM(p.price_rub) FROM purchases pu 
                 JOIN products p ON pu.product_id = p.id
                 WHERE date(pu.purchase_date) = date('now')''')
    revenue_today = c.fetchone()[0] or 0
    
    c.execute('''SELECT SUM(p.price_rub) FROM purchases pu 
                 JOIN products p ON pu.product_id = p.id''')
    total_revenue = c.fetchone()[0] or 0
    
    # Статистика по товарам
    c.execute('''SELECT p.name, COUNT(pu.id), p.price_rub
                 FROM products p
                 LEFT JOIN purchases pu ON p.id = pu.product_id
                 GROUP BY p.id''')
    products_stats = c.fetchall()
    
    # Статистика по наличию
    c.execute("SELECT COUNT(*) FROM proxy_items WHERE is_available = 1")
    available_proxy = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM vpn_items WHERE is_available = 1")
    available_vpn = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM free_keys WHERE is_available = 1")
    available_free = c.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"• Всего: {total_users}\n"
        f"• Новых сегодня: {new_users_today}\n\n"
        
        f"💰 <b>Финансы:</b>\n"
        f"• Сегодня: {revenue_today}₽\n"
        f"• Всего: {total_revenue}₽\n\n"
        
        f"📦 <b>Покупки:</b>\n"
        f"• Сегодня: {purchases_today}\n"
        f"• Активных: {active_purchases}\n\n"
        
        f"📊 <b>Наличие:</b>\n"
        f"• Прокси: {available_proxy} шт\n"
        f"• VPN: {available_vpn} шт\n"
        f"• Бесплатных: {available_free} шт\n\n"
        
        f"📋 <b>Продажи по товарам:</b>\n"
    )
    
    for p in products_stats:
        if p[1] > 0:
            stats_text += f"• {p[0]}: {p[1]} шт (на {p[1]*p[2]}₽)\n"
    
    await callback.message.edit_text(stats_text, parse_mode=ParseMode.HTML, reply_markup=back_button("admin"))
    await callback.answer()

# Рассылка
@dp.callback_query(F.data == "admin_newsletter")
async def admin_newsletter(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 Введите текст для рассылки всем пользователям\n"
        "(можно использовать HTML разметку):"
    )
    await state.set_state(AdminStates.waiting_for_newsletter)
    await callback.answer()

@dp.message(AdminStates.waiting_for_newsletter)
async def process_newsletter(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    text = message.text
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    status_msg = await message.answer(f"📢 Начинаю рассылку {len(users)} пользователям...")
    
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 <b>Рассылка:</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка отправки пользователю {user[0]}: {e}")
    
    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n"
        f"✓ Отправлено: {sent}\n"
        f"✗ Не доставлено: {failed}"
    )
    await state.clear()

# Изменение цен
@dp.callback_query(F.data == "admin_prices")
async def admin_prices(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name, price_rub FROM products WHERE is_active=1")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await callback.message.edit_text("Нет активных товаров", reply_markup=back_button("admin"))
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.row(InlineKeyboardButton(
            text=f"{product[1]} - {product[2]}₽",
            callback_data=f"edit_price_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "💰 Выберите товар для изменения цены:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_price_"))
async def edit_price(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    await state.update_data(price_product_id=product_id)
    
    await callback.message.edit_text(
        "Введите новую цену в рублях:"
    )
    await state.set_state(AdminStates.waiting_for_price_change)
    await callback.answer()

@dp.message(AdminStates.waiting_for_price_change)
async def process_price_change(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        new_price = float(message.text)
        data = await state.get_data()
        product_id = data['price_product_id']
        
        conn = sqlite3.connect('dev_monkey.db')
        c = conn.cursor()
        c.execute('''UPDATE products 
                     SET price_rub = ?, price_usdt = ? 
                     WHERE id = ?''',
                  (new_price, new_price/USDT_TO_RUB, product_id))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Цена успешно изменена!")
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число")

# Добавление товара
@dp.callback_query(F.data == "admin_add_product")
async def admin_add_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🖧 Прокси", callback_data="add_proxy_type"),
        InlineKeyboardButton(text="🔒 VPN", callback_data="add_vpn_type")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Выберите тип товара:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "add_proxy_type")
async def add_proxy_type(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_type="proxy")
    await callback.message.edit_text("Введите название товара:")
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.answer()

@dp.callback_query(F.data == "add_vpn_type")
async def add_vpn_type(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_type="vpn")
    await callback.message.edit_text("Введите название товара:")
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_product_name)
async def process_product_name(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text)
    await message.answer("Введите цену в рублях:")
    await state.set_state(AdminStates.waiting_for_product_price)

@dp.message(AdminStates.waiting_for_product_price)
async def process_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(price_rub=price, price_usdt=price/USDT_TO_RUB)
        await message.answer("Введите лимит пользователей на один товар (число):")
        await state.set_state(AdminStates.waiting_for_product_limit)
    except ValueError:
        await message.answer("❌ Введите корректное число")

@dp.message(AdminStates.waiting_for_product_limit)
async def process_product_limit(message: Message, state: FSMContext):
    try:
        limit = int(message.text)
        data = await state.get_data()
        
        conn = sqlite3.connect('dev_monkey.db')
        c = conn.cursor()
        c.execute('''INSERT INTO products 
                     (name, type, price_rub, price_usdt, limit_users, instruction, is_active)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (data['product_name'], data['product_type'], 
                   data['price_rub'], data['price_usdt'], limit, 
                   "Инструкция будет добавлена позже", 1))
        product_id = c.lastrowid
        conn.commit()
        conn.close()
        
        await message.answer(
            f"✅ Товар успешно добавлен! (ID: {product_id})\n\n"
            f"Теперь добавьте данные для товара через меню '🔑 Добавить данные'"
        )
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число")

# Добавление данных к товару
@dp.callback_query(F.data == "admin_add_data")
async def admin_add_data(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name, type FROM products WHERE is_active=1")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await callback.message.edit_text("Нет активных товаров", reply_markup=back_button("admin"))
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        emoji = "🖧" if product[2] == "proxy" else "🔒"
        builder.row(InlineKeyboardButton(
            text=f"{emoji} {product[1]}",
            callback_data=f"add_data_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Выберите товар для добавления данных:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("add_data_"))
async def add_data_to_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT type, name FROM products WHERE id = ?", (product_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await callback.answer("Товар не найден")
        return
    
    product_type, product_name = result
    await state.update_data(product_id=product_id, product_type=product_type)
    
    type_text = "прокси" if product_type == "proxy" else "VPN"
    
    await callback.message.edit_text(
        f"Добавление данных для товара: {product_name}\n\n"
        f"Введите данные (каждую новую позицию с новой строки):\n\n"
        f"Для {type_text} формат:\n"
        f"{'ip:port:login:password' if product_type == 'proxy' else 'сервер или ключ'}\n\n"
        f"Пример:\n"
        f"{'192.168.1.1:8080:user:pass' if product_type == 'proxy' else 'vpn-server.com'}"
    )
    await state.set_state(AdminStates.waiting_for_product_data)
    await callback.answer()

@dp.message(AdminStates.waiting_for_product_data)
async def process_product_data(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data['product_id']
    product_type = data['product_type']
    
    lines = message.text.strip().split('\n')
    added = 0
    errors = 0
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    for line in lines:
        line = line.strip()
        if line:
            try:
                if product_type == 'proxy':
                    c.execute('''INSERT INTO proxy_items (product_id, proxy_data) 
                                 VALUES (?, ?)''', (product_id, line))
                else:
                    c.execute('''INSERT INTO vpn_items (product_id, vpn_data) 
                                 VALUES (?, ?)''', (product_id, line))
                added += 1
            except Exception as e:
                errors += 1
                logger.error(f"Ошибка при добавлении данных: {e}")
    
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Добавлено: {added} позиций\n❌ Ошибок: {errors}")
    await state.clear()

# Управление инструкциями
@dp.callback_query(F.data == "admin_instructions")
async def admin_instructions(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name FROM products")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await callback.message.edit_text("Нет товаров", reply_markup=back_button("admin"))
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.row(InlineKeyboardButton(
            text=product[1],
            callback_data=f"edit_inst_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Выберите товар для редактирования инструкции:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_inst_"))
async def edit_instruction(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text("Введите новую инструкцию:")
    await state.set_state(AdminStates.waiting_for_instruction)
    await callback.answer()

@dp.message(AdminStates.waiting_for_instruction)
async def process_instruction(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    product_id = data['product_id']
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("UPDATE products SET instruction = ? WHERE id = ?", (message.text, product_id))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Инструкция обновлена!")
    await state.clear()

# Управление бесплатными ключами
@dp.callback_query(F.data == "admin_free_keys")
async def admin_free_keys(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить PROXY", callback_data="add_free_proxy"),
        InlineKeyboardButton(text="➕ Добавить VPN", callback_data="add_free_vpn")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Список ключей", callback_data="list_free_keys")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Управление бесплатными ключами:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("add_free_"))
async def add_free_key(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    key_type = callback.data.split("_")[2]  # proxy или vpn
    await state.update_data(free_type=key_type)
    
    await callback.message.edit_text(f"Введите {key_type.upper()} ключ/ссылку:")
    await state.set_state(AdminStates.waiting_for_free_proxy_key)
    await callback.answer()

@dp.message(AdminStates.waiting_for_free_proxy_key)
async def process_free_key(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await state.update_data(free_key=message.text)
    await message.answer("Введите инструкцию для использования:")
    await state.set_state(AdminStates.waiting_for_free_proxy_instruction)

@dp.message(AdminStates.waiting_for_free_proxy_instruction)
async def process_free_instruction(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute('''INSERT INTO free_keys (type, key, instruction) 
                 VALUES (?, ?, ?)''',
              (data['free_type'], data['free_key'], message.text))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Бесплатный ключ добавлен!")
    await state.clear()

@dp.callback_query(F.data == "list_free_keys")
async def list_free_keys(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute('''SELECT id, type, key, is_available, used_by, used_date 
                 FROM free_keys ORDER BY id DESC''')
    keys = c.fetchall()
    conn.close()
    
    if not keys:
        await callback.message.edit_text("Нет бесплатных ключей", reply_markup=back_button("admin_free_keys"))
        await callback.answer()
        return
    
    text = "📋 <b>Бесплатные ключи:</b>\n\n"
    for k in keys:
        status = "✅ Доступен" if k[3] == 1 else f"❌ Использован (ID: {k[4]})"
        text += f"ID {k[0]} | {k[1].upper()}\n"
        text += f"Ключ: <code>{k[2]}</code>\n"
        text += f"Статус: {status}\n"
        if k[5]:
            text += f"Дата: {k[5]}\n"
        text += "─" * 20 + "\n"
    
    # Разбиваем на части если текст слишком длинный
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            if i == 0:
                await callback.message.edit_text(part, parse_mode=ParseMode.HTML, reply_markup=back_button("admin_free_keys"))
            else:
                await callback.message.answer(part, parse_mode=ParseMode.HTML)
    else:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_button("admin_free_keys"))
    
    await callback.answer()

# Управление товарами (включение/отключение)
@dp.callback_query(F.data == "admin_manage_products")
async def admin_manage_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name, price_rub, current_users, limit_users, is_active FROM products")
    products = c.fetchall()
    conn.close()
    
    if not products:
        await callback.message.edit_text("Нет товаров", reply_markup=back_button("admin"))
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for product in products:
        status = "✅" if product[5] == 1 else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status} {product[1]} - {product[2]}₽ ({product[3]}/{product[4]})",
            callback_data=f"toggle_product_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Управление товарами (нажмите для включения/отключения):",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_product_"))
async def toggle_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT is_active FROM products WHERE id = ?", (product_id,))
    current = c.fetchone()[0]
    
    new_status = 0 if current == 1 else 1
    c.execute("UPDATE products SET is_active = ? WHERE id = ?", (new_status, product_id))
    conn.commit()
    conn.close()
    
    await callback.answer(f"Товар {'включен' if new_status == 1 else 'отключен'}")
    
    # Обновляем список товаров
    await admin_manage_products(callback)

# Навигация
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_proxy")
async def back_to_proxy(callback: CallbackQuery):
    await show_proxy_products(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "back_to_vpn")
async def back_to_vpn(callback: CallbackQuery):
    await show_vpn_products(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "admin")
async def back_to_admin(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ Админ панель\nВыберите действие:",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

# Команда помощи
@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "🐒 <b>Dev Monkey - Помощь</b>\n\n"
        "🔹 <b>Купить прокси</b> - приобрести прокси для любых задач\n"
        "🔹 <b>Купить VPN</b> - безопасный доступ в интернет\n"
        "🔹 <b>Профиль</b> - история покупок и полученные ключи\n"
        "🔹 <b>Бесплатные</b> - получить бесплатный прокси или VPN\n\n"
        "По всем вопросам обращайтесь к администратору."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)

# Обработчик всех остальных сообщений
@dp.message()
async def handle_unknown(message: Message):
    if message.text not in ["🛒 Купить прокси", "🔒 Купить VPN", "👤 Профиль", "🎁 Бесплатные", "⚙️ Админ панель"]:
        await message.answer(
            "Используйте кнопки меню для навигации",
            reply_markup=get_main_keyboard()
        )

# Запуск бота
async def main():
    # Инициализация БД
    init_db()
    add_admin()
    add_initial_products()
    
    # Запускаем фоновую проверку платежей
    asyncio.create_task(payment_checker())
    
    logger.info("Бот Dev Monkey запущен")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
