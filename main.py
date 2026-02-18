import os
import logging
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums.parse_mode import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
ADMIN_ID = 7973988177
USDT_TO_RUB = 80

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

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
                  data TEXT)''')
    
    # Таблица покупок
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  product_id INTEGER,
                  purchase_date TEXT,
                  expiry_date TEXT,
                  status TEXT,
                  data TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (user_id),
                  FOREIGN KEY (product_id) REFERENCES products (id))''')
    
    # Таблица бесплатных ключей
    c.execute('''CREATE TABLE IF NOT EXISTS free_keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  type TEXT,
                  key TEXT,
                  instruction TEXT,
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

# Заполнение начальными товарами
def add_initial_products():
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    products = [
        ('Общие прокси (до 3 чел)', 'proxy_shared', 3, 3/80, 3, 0, 'Инструкция для общих прокси', 'proxy_data_1'),
        ('Индивидуальные прокси', 'proxy_individual', 10, 10/80, 1, 0, 'Инструкция для индивидуальных прокси', 'proxy_data_2'),
        ('VPN на 3 дня', 'vpn_3days', 3, 3/80, 3, 0, 'Инструкция для VPN 3 дня', 'vpn_data_1'),
        ('VPN на 30 дней', 'vpn_30days', 15, 15/80, 3, 0, 'Инструкция для VPN 30 дней', 'vpn_data_2')
    ]
    
    c.executemany('''INSERT OR IGNORE INTO products 
                    (name, type, price_rub, price_usdt, limit_users, current_users, instruction, data) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', products)
    
    conn.commit()
    conn.close()

# Клавиатуры
def main_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🛒 Купить прокси", callback_data="buy_proxy"))
    builder.row(InlineKeyboardButton(text="🔒 Купить VPN", callback_data="buy_vpn"))
    builder.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    builder.row(InlineKeyboardButton(text="🎁 Бесплатные proxy/vpn", callback_data="free"))
    
    # Проверяем, админ ли пользователь
    if user_id == ADMIN_ID:
        builder.row(InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin"))
    
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
        InlineKeyboardButton(text="📝 Добавить инструкцию", callback_data="admin_add_instruction"),
        InlineKeyboardButton(text="🔑 Добавить прокси данные", callback_data="admin_add_proxy_data")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
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
    
    await message.answer(
        f"🐒 Добро пожаловать в Dev Monkey, {first_name}!\n\n"
        f"Здесь вы можете приобрести качественные прокси и VPN по доступным ценам.\n"
        f"Курс: 1 USDT = {USDT_TO_RUB}₽\n\n"
        f"Выберите действие:",
        reply_markup=main_keyboard(user_id)
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_keyboard(callback.from_user.id)
    )
    await callback.answer()

# Обработчики покупок
@dp.callback_query(F.data == "buy_proxy")
async def buy_proxy(callback: CallbackQuery):
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE type LIKE 'proxy%'")
    products = c.fetchall()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    for product in products:
        status = "✅ В наличии" if product[5] < product[6] else "❌ Нет в наличии"
        builder.row(InlineKeyboardButton(
            text=f"{product[1]} - {product[3]}₽ {status}",
            callback_data=f"buy_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    
    await callback.message.edit_text(
        "🛒 Выберите тип прокси:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Получаем информацию о товаре
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    
    if not product:
        await callback.answer("Товар не найден")
        return
    
    # Проверяем наличие
    if product[5] >= product[6]:
        await callback.answer("❌ Товар закончился", show_alert=True)
        conn.close()
        return
    
    # Создаем счет в USDT
    amount_usdt = product[4]
    
    # Здесь будет интеграция с Crypto Bot API
    # Пока создаем тестовый счет
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Оплатить", callback_data=f"pay_{product_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_main"))
    
    await callback.message.edit_text(
        f"💰 Товар: {product[1]}\n"
        f"Цена: {product[3]}₽ ({amount_usdt:.4f} USDT)\n\n"
        f"Для оплаты нажмите кнопку ниже:",
        reply_markup=builder.as_markup()
    )
    
    conn.close()
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Получаем товар
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    
    if not product:
        await callback.answer("Товар не найден")
        conn.close()
        return
    
    # Обновляем количество пользователей
    new_users = product[5] + 1
    c.execute("UPDATE products SET current_users = ? WHERE id = ?", (new_users, product_id))
    
    # Определяем срок действия
    if product[2] == 'vpn_3days':
        expiry = datetime.now() + timedelta(days=3)
    elif product[2] == 'vpn_30days':
        expiry = datetime.now() + timedelta(days=30)
    else:
        expiry = datetime.now() + timedelta(days=7)
    
    # Записываем покупку
    c.execute('''INSERT INTO purchases (user_id, product_id, purchase_date, expiry_date, status, data)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, product_id, 
               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               expiry.strftime("%Y-%m-%d %H:%M:%S"),
               'active',
               product[8]))
    
    conn.commit()
    
    # Отправляем данные пользователю
    await callback.message.edit_text(
        f"✅ Оплата успешно получена!\n\n"
        f"Ваши данные:\n{product[8]}\n\n"
        f"Инструкция:\n{product[7]}\n\n"
        f"Срок действия до: {expiry.strftime('%d.%m.%Y')}",
        reply_markup=main_keyboard(user_id)
    )
    
    conn.close()
    await callback.answer("Спасибо за покупку!", show_alert=True)

# Профиль
@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Информация о пользователе
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    
    # История покупок
    c.execute('''SELECT p.name, pu.purchase_date, pu.expiry_date, pu.status 
                 FROM purchases pu
                 JOIN products p ON pu.product_id = p.id
                 WHERE pu.user_id = ?
                 ORDER BY pu.purchase_date DESC LIMIT 5''', (user_id,))
    purchases = c.fetchall()
    
    # Бесплатные ключи пользователя
    c.execute("SELECT type, key, used_date FROM free_keys WHERE used_by = ?", (user_id,))
    free_keys = c.fetchall()
    
    conn.close()
    
    profile_text = f"👤 Профиль пользователя\n\n"
    profile_text += f"ID: {user_id}\n"
    profile_text += f"Имя: {user[2]}\n"
    profile_text += f"Дата регистрации: {user[3]}\n\n"
    
    profile_text += "📊 Последние покупки:\n"
    if purchases:
        for p in purchases:
            status = "✅ Активен" if p[3] == 'active' else "❌ Истек"
            profile_text += f"• {p[0]} - {p[1]} ({status})\n"
    else:
        profile_text += "Покупок пока нет\n"
    
    profile_text += "\n🎁 Полученные бесплатные ключи:\n"
    if free_keys:
        for fk in free_keys:
            profile_text += f"• {fk[0]}: {fk[1]}\n"
    else:
        profile_text += "Бесплатных ключей пока нет\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    
    await callback.message.edit_text(profile_text, reply_markup=builder.as_markup())
    await callback.answer()

# Бесплатные ключи
@dp.callback_query(F.data == "free")
async def free_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🖧 PROXY", callback_data="free_proxy"),
        InlineKeyboardButton(text="🔒 VPN", callback_data="free_vpn")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    
    await callback.message.edit_text(
        "🎁 Выберите, что хотите получить бесплатно:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.in_(["free_proxy", "free_vpn"]))
async def get_free_key(callback: CallbackQuery):
    key_type = "proxy" if callback.data == "free_proxy" else "vpn"
    user_id = callback.from_user.id
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Ищем неиспользованный ключ
    c.execute("SELECT * FROM free_keys WHERE type = ? AND used_by IS NULL LIMIT 1", (key_type,))
    key = c.fetchone()
    
    if key:
        # Отмечаем ключ как использованный
        c.execute('''UPDATE free_keys 
                     SET used_by = ?, used_date = ? 
                     WHERE id = ?''',
                  (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), key[0]))
        conn.commit()
        
        await callback.message.edit_text(
            f"✅ Ваш бесплатный {key_type.upper()}:\n\n"
            f"Ключ/ссылка: {key[2]}\n\n"
            f"Инструкция:\n{key[3]}\n\n"
            f"Сохраните эти данные!",
            reply_markup=main_keyboard(user_id)
        )
    else:
        await callback.message.edit_text(
            f"😔 К сожалению, бесплатные {key_type.upper()} закончились.\n"
            f"Попробуйте позже или приобретите платную версию.",
            reply_markup=main_keyboard(user_id)
        )
    
    conn.close()
    await callback.answer()

# Админ панель
@dp.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ Админ панель\nВыберите действие:",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Статистика
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM purchases WHERE status = 'active'")
    active_purchases = c.fetchone()[0]
    
    c.execute("SELECT SUM(price_rub) FROM purchases pu JOIN products p ON pu.product_id = p.id")
    total_revenue = c.fetchone()[0] or 0
    
    c.execute('''SELECT p.name, COUNT(*) as count 
                 FROM purchases pu 
                 JOIN products p ON pu.product_id = p.id 
                 GROUP BY p.id''')
    products_stats = c.fetchall()
    
    conn.close()
    
    stats_text = f"📊 Статистика\n\n"
    stats_text += f"👥 Всего пользователей: {total_users}\n"
    stats_text += f"🔄 Активных покупок: {active_purchases}\n"
    stats_text += f"💰 Общий доход: {total_revenue}₽\n\n"
    
    stats_text += "📦 Продажи по товарам:\n"
    for p in products_stats:
        stats_text += f"• {p[0]}: {p[1]} шт\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "admin_newsletter")
async def admin_newsletter(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 Введите текст для рассылки всем пользователям:"
    )
    await state.set_state(AdminStates.waiting_for_newsletter)
    await callback.answer()

@dp.message(AdminStates.waiting_for_newsletter)
async def process_newsletter(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    text = message.text
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 Рассылка:\n\n{text}")
            sent += 1
            await asyncio.sleep(0.05)  # Чтобы не спамить
        except:
            failed += 1
    
    await message.answer(
        f"✅ Рассылка завершена!\n"
        f"Отправлено: {sent}\n"
        f"Не доставлено: {failed}"
    )
    await state.clear()

@dp.callback_query(F.data == "admin_prices")
async def admin_prices(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name, price_rub FROM products")
    products = c.fetchall()
    conn.close()
    
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
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    product_id = callback.data.split("_")[2]
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text(
        "Введите новую цену в рублях:"
    )
    await state.set_state(AdminStates.waiting_for_price_change)
    await callback.answer()

@dp.message(AdminStates.waiting_for_price_change)
async def process_price_change(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        new_price = float(message.text)
        data = await state.get_data()
        product_id = data['product_id']
        
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

@dp.callback_query(F.data == "admin_add_instruction")
async def add_instruction(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name FROM products")
    products = c.fetchall()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.row(InlineKeyboardButton(
            text=product[1],
            callback_data=f"inst_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Выберите товар для добавления инструкции:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("inst_"))
async def select_product_for_instruction(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = callback.data.split("_")[1]
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text(
        "Введите инструкцию для товара:"
    )
    await state.set_state(AdminStates.waiting_for_instruction)
    await callback.answer()

@dp.message(AdminStates.waiting_for_instruction)
async def process_instruction(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    instruction = message.text
    data = await state.get_data()
    product_id = data['product_id']
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("UPDATE products SET instruction = ? WHERE id = ?", (instruction, product_id))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Инструкция добавлена!")
    await state.clear()

@dp.callback_query(F.data == "admin_add_proxy_data")
async def add_proxy_data(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("SELECT id, name FROM products WHERE type LIKE 'proxy%'")
    products = c.fetchall()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.row(InlineKeyboardButton(
            text=product[1],
            callback_data=f"proxy_data_{product[0]}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    
    await callback.message.edit_text(
        "Выберите прокси для добавления данных:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("proxy_data_"))
async def add_proxy_data_input(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    product_id = callback.data.split("_")[2]
    await state.update_data(product_id=product_id)
    
    await callback.message.edit_text(
        "Введите данные прокси (формат: ip:port:login:password):"
    )
    await state.set_state(AdminStates.waiting_for_proxy_data)
    await callback.answer()

@dp.message(AdminStates.waiting_for_proxy_data)
async def process_proxy_data(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    proxy_data = message.text
    data = await state.get_data()
    product_id = data['product_id']
    
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    c.execute("UPDATE products SET data = ? WHERE id = ?", (proxy_data, product_id))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Данные прокси добавлены!")
    await state.clear()

# Запуск бота
async def main():
    # Инициализация БД
    init_db()
    add_admin()
    add_initial_products()
    
    # Добавляем тестовые бесплатные ключи
    conn = sqlite3.connect('dev_monkey.db')
    c = conn.cursor()
    
    # Проверяем, есть ли уже ключи
    c.execute("SELECT COUNT(*) FROM free_keys")
    count = c.fetchone()[0]
    
    if count == 0:
        free_keys = [
            ('proxy', 'proxy1.example.com:8080:user:pass', 'Настройте прокси в вашем браузере'),
            ('proxy', 'proxy2.example.com:8080:user:pass', 'Настройте прокси в вашем браузере'),
            ('vpn', 'vpn1.example.com', 'Скачайте приложение и введите этот адрес'),
            ('vpn', 'vpn2.example.com', 'Скачайте приложение и введите этот адрес')
        ]
        c.executemany('INSERT INTO free_keys (type, key, instruction) VALUES (?, ?, ?)', free_keys)
        conn.commit()
    
    conn.close()
    
    logger.info("Бот Dev Monkey запущен")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
