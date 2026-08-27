# 🤖 AI Assistant

A fast, modern, ChatGPT-style AI chatbot with a stunning web UI powered by [Groq](https://console.groq.com) (free tier, no credit card needed) and a FastAPI backend.

## ✨ Features
- **Streaming responses** — text types out word-by-word with a blinking cursor
- **Multiple AI models** — switch between GPT-OSS 120B/20B, Qwen 3.8, Allam 2 from the header
- **Manual theme toggle** — switch Light / Dark / System mode (not just auto)
- **Export chat** — download as `.txt` or print to PDF (Save as PDF)
- **Copy** any message or code block, including your own messages
- **Voice input 🎤** — speak and it types your words (uses browser speech recognition)
- **Voice output 🔊** — "Speak" button reads the assistant's reply aloud (text-to-speech)
- **Stop generating** button while the AI is streaming
- **Regenerate** a response
- **Multi-chat sidebar** — new chats, delete, auto-titled, saved in the browser
- **Markdown rendering** — headings, lists, tables, links, formatted code blocks
- **"You" / "Assistant" labels** with avatars and timestamps
- **Smart scroll** — floating "scroll to bottom" button when you scroll up
- **Polished UI** — gradients, glassmorphism, dark/light mode, smooth animations
- **Correct, complete answers** with an optimized system prompt

## 🚀 Getting Started

### 1. Get a Groq API key
1. Go to https://console.groq.com and sign up (free).
2. Create an API key under **API Keys**.
3. Copy your key.

### 2. Configure
```bash
cd backend
copy .env.example .env    # Windows
# Then edit .env and set GROQ_API_KEY=your_key
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run
```bash
cd backend
uvicorn main:app --reload --port 8000
```
Open http://localhost:8000 in your browser. 🎉

## 🔧 Configuration (`.env`)
| Variable       | Default                  | Description |
|----------------|--------------------------|-------------|
| `GROQ_API_KEY` | *(required)*             | Your Groq API key |
| `MODEL`        | `llama-3.3-70b-versatile`| Groq model to use |

## 📂 Project structure
```
ai-chatbot/
├── requirements.txt
├── .env.example
├── .env                 (your config, git-ignored)
└── backend/
    ├── main.py          (FastAPI app + Groq integration)
    └── static/
        ├── index.html   (chat UI)
        ├── css/style.css
        └── js/app.js
```

## 🛠️ API
- `GET  /api/health` — health check + current model
- `POST /api/chat` — send chat messages
  ```json
  { "messages": [ { "role": "user", "content": "Hello" } ] }
  ```

## 💡 Ideas to extend
- Streaming responses (`stream=True`)
- Multiple model options in the UI
- System-prompt / personality selection
- RAG (chat over your own documents)
- Persist conversations in a database
