import os
import io
import re
import json
import sqlite3
import logging
import secrets
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image, ImageStat, ImageFilter
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
# Render Blueprint generates a secret. Remove characters Telegram does not allow.
_raw_webhook_secret = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_SECRET = re.sub(r"[^A-Za-z0-9_-]", "", _raw_webhook_secret) or secrets.token_urlsafe(32)
WEBHOOK_BASE_URL = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL") or "").rstrip("/")
DB_PATH = os.getenv("DB_PATH", "beautyscore.db")
MAX_IMAGE_BYTES = 12 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавь токен в Render → Environment.")

bot = Bot(TOKEN)
dp = Dispatcher()

# Articles are starter content written for this bot, not copied wholesale from BeautyScore.
GUIDES = {
    "skin": {
        "title": "Качество кожи",
        "tags": ["кожа", "прыщи", "уход", "сухость", "жирность"],
        "body": "Базовый уход обычно включает мягкое очищение, увлажнение и SPF днём. Вводи новые средства постепенно и не используй сразу много активных компонентов. По фотографии нельзя надёжно поставить диагноз или точно определить тип кожи. Если акне стойкое, болезненное или оставляет рубцы, обратись к дерматологу."
    },
    "brows": {
        "title": "Брови",
        "tags": ["брови", "форма", "уход"],
        "body": "Начни с расчёсывания бровей щёточкой и посмотри на естественную форму. Если хочешь убрать отдельные волоски, делай это постепенно и не меняй форму резко. Не наноси раздражающие средства рядом с глазами. Форма бровей индивидуальна — не существует одной правильной формы для всех."
    },
    "jaw": {
        "title": "Линия челюсти",
        "tags": ["челюсть", "подбородок", "jawline", "лицо"],
        "body": "Вид линии челюсти на фото зависит от освещения, ракурса, положения головы и индивидуальной анатомии. Один снимок не позволяет точно измерить строение костей. Не пытайся менять прикус или нагружать челюсть специальными устройствами без консультации специалиста."
    },
    "eyes": {
        "title": "Глаза и взгляд",
        "tags": ["глаза", "взгляд", "наклон", "canthal tilt"],
        "body": "На вид глаз влияют направление взгляда, наклон головы, расстояние до камеры и освещение. Автоматические измерения по фото приблизительны. Для более ровного снимка смотри прямо в камеру, держи её на уровне глаз и используй мягкий свет спереди."
    },
    "hair": {
        "title": "Волосы и причёска",
        "tags": ["волосы", "причёска", "стрижка"],
        "body": "Выбирай причёску по типу волос, привычному уходу и тому, сколько времени готов тратить на укладку. Сохрани несколько примеров, которые тебе нравятся, и обсуди с парикмахером, как адаптировать их под твои волосы."
    },
    "mewing": {
        "title": "Мьюинг",
        "tags": ["мьюинг", "язык", "челюсть"],
        "body": "Надёжных доказательств, что мьюинг заметно меняет форму челюсти, недостаточно. Не дави языком на зубы и не пытайся самостоятельно менять прикус. Если есть вопросы по дыханию, прикусу или положению зубов, обратись к стоматологу или ортодонту."
    },
    "photo": {
        "title": "Как сделать хорошее фото",
        "tags": ["фото", "снимок", "свет", "ракурс"],
        "body": "Для сравнимого снимка встань прямо, держи камеру на уровне глаз, используй мягкий свет спереди и выключи фильтры. Не приближай камеру вплотную к лицу: перспектива может искажать пропорции. Для сравнения снимайся примерно с одинакового расстояния и в похожем освещении."
    },
    "sleep": {
        "title": "Сон и привычки",
        "tags": ["сон", "режим", "привычки"],
        "body": "Регулярный сон, питание и повседневный уход важнее быстрых обещаний из интернета. Старайся придерживаться стабильного режима и не используй экстремальные диеты или опасные методы ради изменения внешности."
    }
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        summary TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS saved_guides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        guide_key TEXT NOT NULL,
        saved_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        reminders_enabled INTEGER DEFAULT 0
    )""")
    conn.commit()
    return conn

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Анализ фото", callback_data="analyze")],
        [InlineKeyboardButton(text="📚 Гайды", callback_data="guides"),
         InlineKeyboardButton(text="📊 Мои результаты", callback_data="history")],
        [InlineKeyboardButton(text="🗓 План ухода", callback_data="plan"),
         InlineKeyboardButton(text="🔎 Поиск", callback_data="search")],
        [InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites"),
         InlineKeyboardButton(text="🔐 Приватность", callback_data="privacy")]
    ])

def guides_keyboard():
    kb = InlineKeyboardBuilder()
    for key, item in GUIDES.items():
        kb.button(text=item["title"], callback_data=f"guide:{key}")
    kb.adjust(2, 2, 2, 2)
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="home"))
    return kb.as_markup()

def save_report(user_id: int, report: str):
    conn = db()
    conn.execute("INSERT INTO analyses(user_id, created_at, summary) VALUES(?,?,?)",
                 (user_id, datetime.now().strftime("%Y-%m-%d %H:%M"), report))
    conn.commit()
    conn.close()

def image_quality_report(raw: bytes) -> str:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = image.size
    stat = ImageStat.Stat(image)
    brightness = sum(stat.mean) / 3
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    sharpness = float(np.var(arr[1:, :] - arr[:-1, :])) if h > 1 else 0
    notes = []
    notes.append("• Разрешение: " + ("хорошее для предварительного анализа" if min(w, h) >= 700 else "небольшое; лучше отправить фото с большим разрешением"))
    if brightness < 65:
        notes.append("• Освещение: снимок выглядит тёмным. Попробуй мягкий свет спереди.")
    elif brightness > 205:
        notes.append("• Освещение: снимок может быть пересвечен. Попробуй менее яркий свет.")
    else:
        notes.append("• Освещение: средняя яркость выглядит приемлемо, но свет может быть неравномерным.")
    notes.append("• Резкость: " + ("возможна размытость — держи камеру неподвижно" if sharpness < 70 else "простая проверка не выявила сильной размытости"))
    notes.append("• Для сравнения используй анфас, нейтральное выражение, камеру на уровне глаз и снимай без фильтров.")
    report = f"📋 <b>Проверка снимка</b>\nРазмер: {w} × {h} px\n\n" + "\n".join(notes)

    # Optional facial landmark analysis using MediaPipe Face Mesh.
    try:
        import mediapipe as mp
        import cv2
        rgb = np.asarray(image)
        with mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1, refine_landmarks=True,
            min_detection_confidence=0.5
        ) as face_mesh:
            result = face_mesh.process(rgb)
        if result.multi_face_landmarks:
            lm = result.multi_face_landmarks[0].landmark
            def xy(i):
                return np.array([lm[i].x * w, lm[i].y * h], dtype=float)
            def dist(a, b):
                return float(np.linalg.norm(xy(a) - xy(b)))
            # Standard MediaPipe Face Mesh indices; approximate image-based measurements only.
            eye_left = (33, 133)
            eye_right = (362, 263)
            eye_w1 = dist(*eye_left)
            eye_w2 = dist(*eye_right)
            face_width = dist(234, 454)
            face_height = dist(10, 152)
            nose_width = dist(98, 327)
            mouth_width = dist(61, 291)
            report += (
                "\n\n<b>📐 Примерные измерения лица</b>\n"
                f"• Ширина лица на снимке: {face_width:.0f} px\n"
                f"• Высота лица на снимке: {face_height:.0f} px\n"
                f"• Ширина области носа: {nose_width:.0f} px\n"
                f"• Ширина рта: {mouth_width:.0f} px\n"
                f"• Ширина области левого глаза: {eye_w1:.0f} px\n"
                f"• Ширина области правого глаза: {eye_w2:.0f} px\n\n"
                "Это измерения в пикселях на конкретном фото, а не медицинские нормы и не оценка привлекательности. "
                "Ракурс, мимика и качество изображения могут заметно менять результат."
            )
        else:
            report += "\n\nЛицо не удалось уверенно обнаружить. Попробуй фото анфас при ровном освещении."
    except ImportError:
        report += "\n\n<i>Дополнительный анализ точек лица не подключён. Установи необязательные зависимости из requirements-face.txt, чтобы включить его.</i>"
    except Exception:
        logging.exception("Landmark analysis unavailable")
        report += "\n\nДополнительные измерения лица сейчас недоступны. Базовая проверка фото выполнена."
    return report

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Я <b>BeautyScore</b> — бот с проверкой снимка, измерениями лица и гайдами по уходу.\n\n"
        "Выбирай функцию кнопками ниже. Фото не сохраняются; в истории остаётся текст отчёта. "
        "Измерения по снимку приблизительны.",
        parse_mode="HTML", reply_markup=main_keyboard()
    )

@dp.message(Command("menu"))
async def menu(message: Message):
    await message.answer("Главное меню:", reply_markup=main_keyboard())

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.answer("Главное меню:", reply_markup=main_keyboard())
    await call.answer()

@dp.callback_query(F.data == "analyze")
async def analyze(call: CallbackQuery):
    await call.message.answer(
        "📸 <b>Отправь фото лица</b>\n\nРекомендации: анфас, мягкий свет, без фильтров, камера на уровне глаз. "
        "Не отправляй чужие фотографии без разрешения. Я проверю качество снимка и попробую измерить видимые ориентиры лица.",
        parse_mode="HTML"
    )
    await call.answer()

@dp.message(F.photo)
async def receive_photo(message: Message):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    stream = io.BytesIO()
    await bot.download_file(file.file_path, destination=stream)
    raw = stream.getvalue()
    if len(raw) > MAX_IMAGE_BYTES:
        await message.answer("Файл слишком большой. Отправь фото меньшего размера.")
        return
    try:
        report = image_quality_report(raw)
    except Exception:
        logging.exception("Image analysis failed")
        await message.answer("Не получилось обработать фото. Попробуй отправить JPG или PNG без фильтров.")
        return
    save_report(message.from_user.id, report)
    await message.answer(report, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Гайды", callback_data="guides"),
         InlineKeyboardButton(text="📊 Мои результаты", callback_data="history")],
        [InlineKeyboardButton(text="📸 Другое фото", callback_data="analyze"),
         InlineKeyboardButton(text="🏠 Меню", callback_data="home")]
    ]))

@dp.callback_query(F.data == "guides")
async def guides(call: CallbackQuery):
    await call.message.answer("📚 Выбери раздел:", reply_markup=guides_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("guide:"))
async def guide(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    item = GUIDES.get(key)
    if not item:
        await call.answer("Раздел не найден", show_alert=True)
        return
    await call.message.answer(
        f"<b>📚 {item['title']}</b>\n\n{item['body']}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"save:{key}")],
            [InlineKeyboardButton(text="⬅️ Все гайды", callback_data="guides"),
             InlineKeyboardButton(text="🏠 Меню", callback_data="home")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data.startswith("save:"))
async def save_guide(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    conn = db()
    conn.execute("INSERT INTO saved_guides(user_id, guide_key, saved_at) VALUES(?,?,?)",
                 (call.from_user.id, key, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    await call.answer("Добавлено в избранное ⭐", show_alert=True)

@dp.callback_query(F.data == "favorites")
async def favorites(call: CallbackQuery):
    conn = db()
    rows = conn.execute("SELECT guide_key, MAX(saved_at) FROM saved_guides WHERE user_id=? GROUP BY guide_key ORDER BY MAX(saved_at) DESC",
                        (call.from_user.id,)).fetchall()
    conn.close()
    if not rows:
        await call.message.answer("Избранное пока пусто. Открой гайд и нажми «В избранное».")
    else:
        kb = InlineKeyboardBuilder()
        for key, _ in rows:
            if key in GUIDES:
                kb.button(text="⭐ " + GUIDES[key]["title"], callback_data=f"guide:{key}")
        kb.adjust(1)
        await call.message.answer("⭐ Твои сохранённые гайды:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    conn = db()
    rows = conn.execute("SELECT created_at, summary FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT 5",
                        (call.from_user.id,)).fetchall()
    conn.close()
    if not rows:
        await call.message.answer("История пока пустая. Отправь фото через кнопку «Анализ фото».")
    else:
        for created, summary in rows:
            await call.message.answer(f"🕒 <b>{created}</b>\n\n{summary[:3500]}", parse_mode="HTML")
        await call.message.answer("Конец истории.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить историю", callback_data="delete_history")],
                             [InlineKeyboardButton(text="🏠 Меню", callback_data="home")]]))
    await call.answer()

@dp.callback_query(F.data == "delete_history")
async def delete_history(call: CallbackQuery):
    conn = db()
    conn.execute("DELETE FROM analyses WHERE user_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()
    await call.message.answer("История отчётов удалена.")
    await call.answer()

@dp.callback_query(F.data == "plan")
async def plan(call: CallbackQuery):
    await call.message.answer(
        "<b>🗓 Базовый план ухода</b>\n\n"
        "<b>Утро</b>\n1. Мягкое очищение при необходимости.\n2. Увлажняющее средство.\n3. Солнцезащита SPF.\n\n"
        "<b>Вечер</b>\n1. Мягкое очищение.\n2. Увлажнение.\n\n"
        "Добавляй новые средства постепенно. При стойких проблемах с кожей обратись к дерматологу.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧴 Гайд по коже", callback_data="guide:skin")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data == "search")
async def search_start(call: CallbackQuery):
    await call.message.answer("Напиши тему, например: кожа, брови, глаза, челюсть, волосы, фото или сон.")
    await call.answer()

@dp.message(F.text)
async def search_text(message: Message):
    query = message.text.lower().strip()
    if query.startswith("/"):
        return
    found = []
    for key, item in GUIDES.items():
        searchable = " ".join([item["title"], item["body"], *item["tags"]]).lower()
        if query and (query in searchable or any(word in searchable for word in re.findall(r"\w+", query) if len(word) > 3)):
            found.append((key, item["title"]))
    if found:
        kb = InlineKeyboardBuilder()
        for key, title in found[:8]:
            kb.button(text=title, callback_data=f"guide:{key}")
        kb.adjust(1)
        await message.answer("Нашёл подходящие разделы:", reply_markup=kb.as_markup())
    else:
        await message.answer("Точного совпадения не нашёл. Выбери раздел:", reply_markup=guides_keyboard())

@dp.callback_query(F.data == "privacy")
async def privacy(call: CallbackQuery):
    await call.message.answer(
        "🔐 <b>Приватность</b>\n\n"
        "• Фотографии обрабатываются для ответа и не сохраняются в базе этого проекта.\n"
        "• В истории сохраняется текст отчёта и дата.\n"
        "• Команда /delete удаляет сохранённые отчёты и избранное.\n"
        "• Данные базы хранятся на устройстве или сервере, где запущен бот.\n\n"
        "Перед публичным запуском укажи владельца бота и подготовь политику конфиденциальности.",
        parse_mode="HTML"
    )
    await call.answer()

@dp.message(Command("delete"))
async def delete_all(message: Message):
    conn = db()
    conn.execute("DELETE FROM analyses WHERE user_id=?", (message.from_user.id,))
    conn.execute("DELETE FROM saved_guides WHERE user_id=?", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("Удалил сохранённые отчёты и избранное.")

async def health(request: web.Request):
    return web.json_response({"ok": True, "service": "beautyscore-telegram-bot"})


async def telegram_webhook(request: web.Request):
    # Check Telegram's secret header before accepting updates.
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise web.HTTPUnauthorized(text="Invalid webhook secret")
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
    except web.HTTPException:
        raise
    except Exception:
        logging.exception("Failed to process Telegram update")
        raise web.HTTPInternalServerError(text="Update processing failed")
    return web.Response(text="ok")


async def on_startup(app: web.Application):
    if not WEBHOOK_BASE_URL:
        raise RuntimeError("Render did not provide RENDER_EXTERNAL_URL. Check that this is deployed as a Web Service.")
    db().close()
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
    )
    logging.info("Telegram webhook configured")


async def on_shutdown(app: web.Application):
    # Do not delete the webhook on shutdown; Render may be restarting the service.
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application(client_max_size=16 * 1024 * 1024)
    app.router.add_get("/", health)
    app.router.add_post(f"/webhook/{WEBHOOK_SECRET}", telegram_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
