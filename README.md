# 🚀 NexQuiz - Advanced Telegram Quiz Bot

NexQuiz is a powerful, feature-rich Telegram bot built with **Aiogram 3** and **SQLite**, designed for group-based quiz competitions. It allows admins to easily import quizzes from CSV files, manage timing, and view detailed performance reports.

---

## ✨ Features

- 📂 **CSV Import:** Easily upload quizzes with multiple-choice questions.
- 👥 **Group Play:** Multiplayer mode requiring a minimum number of users to start.
- ⏱️ **Configurable Timer:** Set custom time limits for each question.
- 🔀 **Randomization:** Randomize both question order and answer options.
- 🏆 **Live Leaderboards:** Real-time ranking displayed after each session.
- 📊 **Detailed Reporting:** Generates CSV reports for admins after every quiz.
- 📉 **Analytics:** Highlights the top 3 most failed questions to identify learning gaps.
- 📩 **Feedback System:** Users can send feedback directly to the admin.
- 🛠️ **Admin Panel:** Intuitive interface for managing quizzes (Add, Edit, Remove).

---

## 🛠️ Tech Stack

- **Language:** Python 3.10+
- **Framework:** [Aiogram 3.x](https://docs.aiogram.dev/)
- **Database:** SQLite (via `aiosqlite`)
- **Data Processing:** Pandas
- **Asynchronous:** Fully `asyncio` based

---

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/uckix/nexquiz.git
cd nexquiz
```

### 2. Set up a Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuration
Open `main.py` and update the following variables:
- `BOT_TOKEN`: Your Telegram Bot Token from [@BotFather](https://t.me/BotFather).
- `ADMIN_IDS`: Your Telegram User ID.

> [!TIP]
> For security, it is recommended to move these to environment variables in production.

### 5. Run the Bot
```bash
python main.py
```

---

## 📂 CSV Format Specification

To import a quiz, upload a `.csv` file with the following columns:

| Column | Description |
| :--- | :--- |
| `question` | The text of the question. |
| `option1` | First answer option. |
| `option2` | Second answer option. |
| `option3` | Third answer option. |
| `option4` | Fourth answer option. |
| `correct_option` | The index of the correct answer (1-4). |
| `explanation` | Text shown after the user answers (or time runs out). |

> [!NOTE]
> You can find a reference file named `template.csv` in the root directory to use as a starting point.

---

## 🎮 How to Use

### For Admins:
1. Send `/start` to the bot in a private message.
2. Use the **"➕ Add New"** button to create a quiz.
3. Upload your CSV and set the timer/randomization settings.
4. Access the **"🏢 Basement"** to view, start, or delete existing quizzes.
5. When starting in a group, the bot provides a direct link to initiate the quiz in any group.

### For Users:
1. Join the group where the quiz is started.
2. Click **"I'm ready"** to join the session.
3. Answer questions as they appear.
4. View your ranking in the final leaderboard!

---

## 🤝 Contributing

Contributions are welcome! If you have ideas for new features or find any bugs, please open an issue or submit a pull request.

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

---

*Developed with ❤️ by [uckix](https://t.me/uckix)*
