import os
import asyncio
import json
import time
import logging
import random
import csv
import pandas as pd
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, PollAnswer, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
BOT_TOKEN = "BOTTOKEN"
ADMIN_IDS = 000000000
DB_PATH = "base.db"

logging.basicConfig(level=logging.INFO)

# Initialize Dispatcher and Global memory for polls
dp = Dispatcher()
active_polls = {}
group_readies = {}  # {chat_id_quiz_id: set([user_id])}
stop_flags = {}  # {chat_id: boolean}

# ==========================================
# 2. DATABASE FUNCTIONS
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT
            );
            
            CREATE TABLE IF NOT EXISTS quizzes (
                quiz_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                category TEXT,
                difficulty TEXT,
                time_limit INTEGER DEFAULT 15,
                rand_q BOOLEAN DEFAULT 0,
                rand_a BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id INTEGER,
                question_text TEXT,
                options TEXT,
                correct_index INTEGER,
                explanation TEXT,
                FOREIGN KEY(quiz_id) REFERENCES quizzes(quiz_id) ON DELETE CASCADE
            );
            
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id INTEGER,
                chat_id INTEGER,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS answers (
                answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER,
                user_id INTEGER,
                question_id INTEGER,
                is_correct BOOLEAN,
                time_taken REAL
            );
        ''')
        try:
            await db.execute("ALTER TABLE quizzes ADD COLUMN time_limit INTEGER DEFAULT 15")
        except: pass
        try:
            await db.execute("ALTER TABLE quizzes ADD COLUMN rand_q BOOLEAN DEFAULT 0")
        except: pass
        try:
            await db.execute("ALTER TABLE quizzes ADD COLUMN rand_a BOOLEAN DEFAULT 0")
        except: pass
        await db.commit()

async def execute_query(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cursor:
            await db.commit()
            return cursor.lastrowid

async def execute_many(query: str, params_list: list):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(query, params_list)
        await db.commit()

async def fetch_query(query: str, params: tuple = (), fetchall=True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall() if fetchall else await cursor.fetchone()

# ==========================================
# 3. CSV PARSER SERVICE
# ==========================================
def parse_quiz_csv(file_path: str) -> dict:
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
        required_cols = ['question', 'option1', 'option2', 'option3', 'option4', 'correct_option', 'explanation']
        
        if not all(col in df.columns for col in required_cols):
            return {"status": "error", "message": f"Missing required columns. Expected: {required_cols}"}

        success, failed, parsed_questions = 0, 0, []

        for _, row in df.iterrows():
            try:
                correct_idx = int(row['correct_option']) - 1
                if not 0 <= correct_idx <= 3:
                    raise ValueError("Correct option must be between 1 and 4")
                
                options = [str(row['option1']), str(row['option2']), str(row['option3']), str(row['option4'])]
                
                parsed_questions.append({
                    "question": str(row['question']),
                    "options": json.dumps(options),
                    "correct_index": correct_idx,
                    "explanation": str(row['explanation'])
                })
                success += 1
            except Exception:
                failed += 1
                
        return {
            "status": "success",
            "total": len(df),
            "success": success,
            "failed": failed,
            "questions": parsed_questions
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================================
# 4. QUIZ ENGINE SERVICE
# ==========================================
async def start_quiz_session(bot: Bot, chat_id: int, quiz_id: int):
    quiz = await fetch_query("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,), fetchall=False)
    questions = list(await fetch_query("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,)))
    
    if not questions:
        await bot.send_message(chat_id, "⚠️ This quiz has no questions.")
        return

    time_limit = quiz['time_limit'] if quiz['time_limit'] is not None else 15
    rand_q = quiz['rand_q']
    rand_a = quiz['rand_a']

    if rand_q:
        random.shuffle(questions)

    attempt_id = await execute_query("INSERT INTO quiz_attempts (quiz_id, chat_id) VALUES (?, ?)", (quiz_id, chat_id))
    
    await bot.send_message(chat_id, f"🏆 <b>Starting Quiz:</b> {quiz['title']}\n"
                                    f"📊 <b>Questions:</b> {len(questions)}\n"
                                    f"⏱ <b>Time per question:</b> {time_limit}s\n\n"
                                    f"Get ready! 🚀", parse_mode="HTML")
    await asyncio.sleep(2)

    start_time = time.time()
    poll_msgs = []
    stop_flags[chat_id] = False

    for idx, q in enumerate(questions, 1):
        if stop_flags.get(chat_id):
            break
            
        options = json.loads(q['options'])
        correct_idx = q['correct_index']
        
        if rand_a:
            paired = list(enumerate(options))
            random.shuffle(paired)
            options = [p[1] for p in paired]
            correct_idx = next(i for i, p in enumerate(paired) if p[0] == correct_idx)
        
        poll_msg = await bot.send_poll(
            chat_id=chat_id,
            question=f"[{idx}/{len(questions)}] {q['question_text']}",
            options=options,
            type="quiz",
            correct_option_id=correct_idx,
            explanation=q['explanation'],
            open_period=time_limit,
            is_anonymous=False
        )
        poll_msgs.append(poll_msg.message_id)
        
        active_polls[poll_msg.poll.id] = {
            "attempt_id": attempt_id,
            "question_id": q['question_id'],
            "correct_index": correct_idx,
            "start_time": time.time()
        }
        
        await asyncio.sleep(time_limit + 1)
        active_polls.pop(poll_msg.poll.id, None)

    stop_flags.pop(chat_id, None)

    for mid in poll_msgs:
        try:
            await bot.delete_message(chat_id, mid)
        except:
            pass

    await send_quiz_results(bot, chat_id, attempt_id, len(questions), quiz['title'])

async def send_quiz_results(bot: Bot, chat_id: int, attempt_id: int, total_q: int, quiz_title: str):
    all_results = await fetch_query('''
        SELECT u.user_id, u.username, u.full_name, SUM(a.is_correct) as correct_count, SUM(a.time_taken) as total_time
        FROM answers a
        JOIN users u ON a.user_id = u.user_id
        WHERE a.attempt_id = ?
        GROUP BY u.user_id
        ORDER BY correct_count DESC, total_time ASC
    ''', (attempt_id,))

    if not all_results:
        await bot.send_message(chat_id, "Quiz ended! No one answered any questions. 😴")
        return

    report_filename = f"report_{quiz_title}.csv"
    try:
        with open(report_filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Username", "Correct Answers", "Percentage"])
            for res in all_results:
                username_val = f"@{res['username']}" if res['username'] else "N/A"
                pct = (res['correct_count'] / total_q) * 100
                writer.writerow([res['full_name'], username_val, res['correct_count'], f"{pct:.0f}%"])
        report_file = FSInputFile(report_filename)
        await bot.send_document(ADMIN_IDS, report_file, caption=f"📊 Report for test: {quiz_title}")
    except Exception as e:
        logging.error(f"Failed to send report: {e}")
    finally:
        if os.path.exists(report_filename):
            os.remove(report_filename)

    top_5 = all_results[:5]
    text = f"<b>🏆 Leaderboard - {quiz_title}</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    for rank, res in enumerate(top_5, 1):
        acc = (res['correct_count'] / total_q) * 100
        medal = medals.get(rank, str(rank))
        text += f"{medal} {res['full_name']}: {res['correct_count']}/{total_q} ({acc:.0f}%) in {int(res['total_time'])} sec\n"

    text += "\n<i>💡 Feedback, bug reports, and new ideas are always welcome - @uckix</i>"
    await bot.send_message(chat_id, text, parse_mode="HTML")

    failed_q_results = await fetch_query('''
        SELECT q.question_text, q.options, q.correct_index, COUNT(a.answer_id) as fail_count
        FROM answers a
        JOIN questions q ON a.question_id = q.question_id
        WHERE a.attempt_id = ? AND a.is_correct = 0
        GROUP BY q.question_id
        ORDER BY fail_count DESC
        LIMIT 3
    ''', (attempt_id,))
    
    if failed_q_results:
        failed_text = "<b>📉 Top 3 Most Failed Questions:</b>\n"
        for idx, res in enumerate(failed_q_results, 1):
            q_text = res['question_text']
            options = json.loads(res['options'])
            correct_ans = options[res['correct_index']]
            fail_c = res['fail_count']
            failed_text += f"\n{idx}. {q_text}\n❌ Failed by {fail_c} users\n✅ Correct answer: {correct_ans}\n"
        await bot.send_message(chat_id, failed_text, parse_mode="HTML")

async def countdown_and_start(bot: Bot, chat_id: int, quiz_id: int):
    msg = await bot.send_message(chat_id, "4")
    for i in range(3, -1, -1):
        await asyncio.sleep(1)
        if i > 0:
            await msg.edit_text(str(i))
        else:
            await msg.edit_text("Go!")
    
    await asyncio.sleep(1)
    await msg.delete()
    await start_quiz_session(bot, chat_id, quiz_id)

# ==========================================
# 5. HANDLERS (ADMIN & GAMEPLAY)
# ==========================================
class AdminAddState(StatesGroup):
    title = State()
    csv_file = State()
    timer = State()
    rand_q = State()
    rand_a = State()

class AdminEditTimerState(StatesGroup):
    timer = State()

class FeedbackState(StatesGroup):
    waiting_for_text = State()

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await execute_query('''
        INSERT OR IGNORE INTO users (user_id, username, full_name) 
        VALUES (?, ?, ?)
    ''', (message.from_user.id, message.from_user.username, message.from_user.full_name))

    if message.from_user.id == ADMIN_IDS and message.chat.type == "private":
        keyboard = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="➕ Add New")],
            [KeyboardButton(text="🏢 Basement")]
        ], resize_keyboard=True)
        await message.answer("Admin Panel:", reply_markup=keyboard)
        return

    if command.args and command.args.startswith("quiz_"):
        if message.from_user.id != ADMIN_IDS:
            return
            
        quiz_id = int(command.args.split("_")[1])
        quiz = await fetch_query("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,), fetchall=False)
        if quiz:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="I'm ready", callback_data=f"im_ready_{quiz_id}")]
            ])
            await message.answer(f"Test '{quiz['title']}' is ready! Click 'I'm ready' to join. (Need at least 2 users)", reply_markup=keyboard)
        return

    if message.chat.type == "private":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Send Feedback", callback_data="send_feedback")]
        ])
        await message.answer("👋 Hello! I am the Advanced Quiz Bot.\nIf you have any feedback or ideas, please let us know!", reply_markup=keyboard)

@dp.callback_query(F.data == "send_feedback")
async def send_feedback_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Please type your feedback below:")
    await state.set_state(FeedbackState.waiting_for_text)

@dp.message(FeedbackState.waiting_for_text)
async def process_feedback(message: Message, state: FSMContext, bot: Bot):
    username = f"@{message.from_user.username}" if message.from_user.username else f"User {message.from_user.id}"
    await bot.send_message(ADMIN_IDS, f"📩 <b>New Feedback</b> from {username}:\n\n{message.text}", parse_mode="HTML")
    await message.answer("✅ Thank you! Your feedback has been sent to the admin.")
    await state.clear()

@dp.callback_query(F.data == "admin_home", F.from_user.id == ADMIN_IDS)
async def admin_home(callback: CallbackQuery):
    await callback.message.delete()

@dp.message(F.text == "➕ Add New", F.from_user.id == ADMIN_IDS)
async def admin_add_new_handler(message: Message, state: FSMContext):
    await message.answer("Name of test:")
    await state.set_state(AdminAddState.title)

@dp.message(AdminAddState.title, F.from_user.id == ADMIN_IDS)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Send .csv file:")
    await state.set_state(AdminAddState.csv_file)

@dp.message(AdminAddState.csv_file, F.document, F.from_user.id == ADMIN_IDS)
async def process_csv(message: Message, state: FSMContext, bot: Bot):
    document = message.document
    if not document.file_name.endswith('.csv'):
        await message.answer("⚠️ Please upload a valid .csv file.")
        return
    file = await bot.get_file(document.file_id)
    file_path = f"temp_{document.file_name}"
    await bot.download_file(file.file_path, file_path)
    
    result = await asyncio.to_thread(parse_quiz_csv, file_path)
    os.remove(file_path)
    if result['status'] == 'error':
         await message.answer(f"❌ Error parsing CSV: {result['message']}")
         await state.clear()
         return
         
    await state.update_data(questions=result['questions'], stats=result)
    await message.answer(f"✅ CSV parsed successfully!\n"
                         f"📊 Questions added: {result['success']}\n"
                         f"❌ Failed to parse: {result['failed']}\n\n"
                         f"Timer for this test (in seconds, e.g. 15):")
    await state.set_state(AdminAddState.timer)

@dp.message(AdminAddState.timer, F.text.regexp(r'^\d+$'), F.from_user.id == ADMIN_IDS)
async def process_timer(message: Message, state: FSMContext):
    await state.update_data(timer=int(message.text))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="yess", callback_data="rq_1"), InlineKeyboardButton(text="naah", callback_data="rq_0")]
    ])
    await message.answer("randomize the qustions order, shepim?", reply_markup=keyboard)
    await state.set_state(AdminAddState.rand_q)

@dp.callback_query(AdminAddState.rand_q, F.data.startswith("rq_"), F.from_user.id == ADMIN_IDS)
async def process_rand_q(callback: CallbackQuery, state: FSMContext):
    await state.update_data(rand_q=callback.data.split("_")[1] == "1")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="yeah", callback_data="ra_1"), InlineKeyboardButton(text="nope", callback_data="ra_0")]
    ])
    await callback.message.edit_text("randomize answer order?", reply_markup=keyboard)
    await state.set_state(AdminAddState.rand_a)

@dp.callback_query(AdminAddState.rand_a, F.data.startswith("ra_"), F.from_user.id == ADMIN_IDS)
async def process_rand_a(callback: CallbackQuery, state: FSMContext):
    rand_a = (callback.data.split("_")[1] == "1")
    data = await state.get_data()
    title = data['title']
    questions = data['questions']
    timer = data['timer']
    rand_q = data['rand_q']
    stats = data.get('stats', {'success': len(questions), 'failed': 0})
    
    quiz_id = await execute_query(
        "INSERT INTO quizzes (title, category, difficulty, time_limit, rand_q, rand_a) VALUES (?, ?, ?, ?, ?, ?)", 
        (title, 'General', 'Medium', timer, rand_q, rand_a)
    )
    
    params_list = [
        (quiz_id, q['question'], q['options'], q['correct_index'], q['explanation'])
        for q in questions
    ]
    await execute_many('''
        INSERT INTO questions (quiz_id, question_text, options, correct_index, explanation)
        VALUES (?, ?, ?, ?, ?)
    ''', params_list)
        
    await callback.message.edit_text(f"✅ Done, saved to basement.\n\n"
                                     f"📊 Test includes {stats['success']} questions.\n"
                                     f"({stats['failed']} failed).")
    await state.clear()

@dp.message(F.text == "🏢 Basement", F.from_user.id == ADMIN_IDS)
async def admin_basement_handler(message: Message):
    quizzes = await fetch_query("SELECT * FROM quizzes ORDER BY created_at DESC LIMIT 10")
    if not quizzes:
        await message.answer("No quizzes available.")
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=q['title'], callback_data=f"basement_quiz_{q['quiz_id']}")] for q in quizzes
    ])
    await message.answer("Basement:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("basement_quiz_"), F.from_user.id == ADMIN_IDS)
async def basement_quiz_info(callback: CallbackQuery, bot: Bot):
    quiz_id = int(callback.data.split("_")[2])
    quiz = await fetch_query("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,), fetchall=False)
    q_count = (await fetch_query("SELECT COUNT(*) as c FROM questions WHERE quiz_id = ?", (quiz_id,), fetchall=False))['c']
    
    bot_info = await bot.me()
    start_url = f"https://t.me/{bot_info.username}?startgroup=quiz_{quiz_id}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="start in group", url=start_url)],
        [InlineKeyboardButton(text="edit timer", callback_data=f"admin_edittimer_{quiz_id}")],
        [InlineKeyboardButton(text="remove", callback_data=f"admin_delquiz_{quiz_id}")]
    ])
    text = f"Name of test: {quiz['title']}\nQuantity of questions: {q_count}\nTest id: {quiz_id}"
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_delquiz_"), F.from_user.id == ADMIN_IDS)
async def admin_delquiz_callback(callback: CallbackQuery):
    quiz_id = int(callback.data.split("_")[2])
    await execute_query("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
    await execute_query("DELETE FROM quizzes WHERE quiz_id = ?", (quiz_id,))
    await callback.answer("Quiz deleted!")
    await callback.message.delete()

@dp.callback_query(F.data.startswith("admin_edittimer_"), F.from_user.id == ADMIN_IDS)
async def admin_edittimer_callback(callback: CallbackQuery, state: FSMContext):
    quiz_id = int(callback.data.split("_")[2])
    await state.update_data(edit_quiz_id=quiz_id)
    await callback.message.edit_text("Enter new timer (in seconds):")
    await state.set_state(AdminEditTimerState.timer)

@dp.message(AdminEditTimerState.timer, F.text.regexp(r'^\d+$'), F.from_user.id == ADMIN_IDS)
async def process_edit_timer(message: Message, state: FSMContext):
    new_timer = int(message.text)
    data = await state.get_data()
    quiz_id = data['edit_quiz_id']
    await execute_query("UPDATE quizzes SET time_limit = ? WHERE quiz_id = ?", (new_timer, quiz_id))
    await message.answer(f"✅ Timer updated to {new_timer}s!")
    await state.clear()

@dp.callback_query(F.data.startswith("im_ready_"))
async def im_ready_callback(callback: CallbackQuery, bot: Bot):
    quiz_id = int(callback.data.split("_")[2])
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    key = f"{chat_id}_{quiz_id}"
    if key not in group_readies:
        group_readies[key] = set()
        
    group_readies[key].add(user_id)
    count = len(group_readies[key])
    
    await callback.answer(f"You are ready! ({count}/2)")
    
    if count >= 2:
        await callback.message.edit_text("Starting test...")
        del group_readies[key]
        asyncio.create_task(countdown_and_start(bot, chat_id, quiz_id))



@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    if message.from_user.id != ADMIN_IDS:
        return
    stop_flags[message.chat.id] = True
    await message.answer("🛑 Test stopped by admin.")

@dp.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer):
    poll_id = poll_answer.poll_id
    if poll_id not in active_polls:
        return
        
    poll_data = active_polls[poll_id]
    user_id = poll_answer.user.id
    user_choice = poll_answer.option_ids[0] if poll_answer.option_ids else -1
    
    is_correct = (user_choice == poll_data['correct_index'])
    time_taken = time.time() - poll_data['start_time']

    await execute_query('''
        INSERT OR IGNORE INTO users (user_id, username, full_name) 
        VALUES (?, ?, ?)
    ''', (user_id, poll_answer.user.username, poll_answer.user.full_name))

    await execute_query('''
        INSERT INTO answers (attempt_id, user_id, question_id, is_correct, time_taken)
        VALUES (?, ?, ?, ?, ?)
    ''', (poll_data['attempt_id'], user_id, poll_data['question_id'], is_correct, time_taken))

# ==========================================
# 6. APPLICATION ENTRY POINT
# ==========================================
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    
    logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logging.error("No BOT_TOKEN provided.")
    else:
        asyncio.run(main())
