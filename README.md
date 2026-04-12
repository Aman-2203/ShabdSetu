# ShabdSetu

**ShabdSetu** (शब्दसेतु — "Bridge of Words") is a web-based document processing platform specializing in Indian-language documents. It provides OCR, AI-powered proofreading, translation, and audio transcription services for Hindi, Gujarati, and other Indic scripts — all wrapped in a modern, premium UI.

---

## Features

| Mode | Name                   | Description                                          | Billing Unit |
|------|------------------------|------------------------------------------------------|-------------|
| 1    | OCR Only               | Extract text from scanned PDF pages using Google Vision API | Per page    |
| 2    | OCR + Proofread        | OCR followed by Gemini AI proofreading               | Per page    |
| 3    | Proofread Only         | AI proofreading of existing DOCX content              | Per page    |
| 4    | OCR + Translation      | OCR followed by Gemini AI translation                 | Per page    |
| 5    | Translation Only       | AI translation of existing DOCX content               | Per page    |
| 6    | Audio Transcription    | Speech-to-text via ElevenLabs + Gemini refinement     | Per minute  |

### Additional Capabilities

- **OTP-based email authentication** — passwordless login via 6-digit OTP (Gmail SMTP)
- **Free trial system** — 3 pages (or 3 minutes for audio) per mode, per user
- **Razorpay payment integration** — pay-per-use pricing after trial exhaustion
- **Automatic email delivery** — processed documents are auto-emailed to the user
- **Auto-cleanup** — uploaded and output files are purged 30 minutes after processing
- **Real-time progress tracking** — job progress streamed to the frontend via polling

---

## Tech Stack

| Layer         | Technology                                                  |
|---------------|-------------------------------------------------------------|
| Backend       | Python 3 · Flask 3.0                                        |
| AI / ML       | Google Gemini API (proofreading, translation, refinement)    |
| OCR           | Google Cloud Vision API                                      |
| Audio         | ElevenLabs API · pydub                                       |
| Database      | MongoDB Atlas (PyMongo)                                      |
| Payments      | Razorpay                                                     |
| Email         | Gmail SMTP (OTP + document delivery)                         |
| Server        | Gunicorn (production) · Flask dev server (development)       |
| Frontend      | Jinja2 templates · Vanilla JS · Vanilla CSS                  |
| Doc Formats   | PyMuPDF (PDF reading) · python-docx (DOCX read/write)        |
| Images        | Pillow                                                       |

---

## Project Structure

```
ShabdSetu/
├── app.py                  # Flask application factory (create_app)
├── wsgi.py                 # WSGI entry point for Gunicorn
├── app.dev.py              # Development entry point (Flask debug server)
├── config.py               # App config, folders, progress_tracker dict
├── db_config.py            # MongoDB connection & collection helpers
├── auth.py                 # OTP generation, email, verification, decorators
├── utils.py                # File validation, page/char counting, email delivery
├── document_handler.py     # DOCX read/write with Indic font formatting
├── process_document.py     # Background document processing orchestrator
├── payment_handler.py      # Razorpay order/verify/record logic
│
├── processors/             # AI processing modules
│   ├── __init__.py
│   ├── base_processor.py           # Base class: chunking, rate-limiting, parallel exec
│   ├── ocr_processor.py            # Google Vision OCR with batched PDF processing
│   ├── proofreading_processor.py   # Gemini-powered proofreading
│   ├── translation_processor.py    # Gemini-powered translation
│   └── audio_processor.py          # ElevenLabs STT + Gemini refinement
│
├── routes/                 # Flask Blueprints
│   ├── __init__.py                 # Blueprint registration
│   ├── auth_routes.py              # /login, /send-otp, /verify-otp, /logout, /check-trial
│   ├── page_routes.py              # /, /features, /pricing, /tool, /mode/<n>, /health
│   ├── document_routes.py          # /process, /progress/<id>, /download/<file>, /send-document/<id>
│   └── payment_routes.py           # /create-payment, /verify-payment
│
├── templates/              # Jinja2 HTML templates
│   ├── base.html                   # Base layout (navbar, fonts, shared CSS/JS)
│   ├── index.html                  # Main tool page (mode selection + upload)
│   ├── feature.html                # Features / landing page
│   ├── pricing.html                # Pricing & plans
│   ├── login.html                  # OTP login form
│   ├── contactus.html              # Contact form
│   └── tc.html                     # Terms & conditions
│
├── static/
│   ├── css/                        # Per-page stylesheets (base, index, feature, etc.)
│   ├── js/                         # Per-page JavaScript (login, index, feature, etc.)
│   ├── favicon.svg
│   └── trial-helper.js             # Shared trial-limit UI helper
│
├── assets/                 # Static assets (favicon)
├── uploads/                # Temporary uploaded files (gitignored, auto-cleaned)
├── outputs/                # Temporary output files (gitignored, auto-cleaned)
│
├── requirements.txt        # Python dependencies
├── gunicorn.conf.py        # Production Gunicorn config (Unix socket)
├── gunicorn.dev.conf.py    # Development Gunicorn config (port 8000)
└── .gitignore
```

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **MongoDB Atlas** cluster (or a local MongoDB instance)
- API keys for:
  - [Google Gemini](https://ai.google.dev/)
  - [Google Cloud Vision](https://cloud.google.com/vision)
  - [Razorpay](https://razorpay.com/) (test or live)
  - [ElevenLabs](https://elevenlabs.io/) (only for Mode 6 — audio transcription)
- A **Gmail account** with an [App Password](https://support.google.com/accounts/answer/185833) for SMTP

### 1. Clone the Repository

```bash
git clone https://github.com/Aman-2203/ShabdSetu.git
cd ShabdSetu
```

### 2. Create a Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Google AI
GEMINI_API_KEY=your_gemini_api_key
GOOGLE_VISION_API_KEY=your_vision_api_key

# Email (Gmail SMTP)
SENDER_EMAIL=your_email@gmail.com
SENDER_PASSWORD=your_gmail_app_password

# MongoDB
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0
MONGO_DB=Cluster0

# Razorpay
RAZORPAY_KEY_ID=rzp_test_xxxxx
RAZORPAY_KEY_SECRET=your_razorpay_secret

# ElevenLabs (required only for Mode 6)
ELEVENLABS_API_KEY=your_elevenlabs_key

# Environment: "development" or "production"
ENV=development
```

> **Note:** In `development` mode, authentication and payment flows are bypassed with test stubs so you can work on the app without needing real credentials for every service.

### 5. Run the Development Server

```bash
# Option A — Flask dev server (simplest)
python app.dev.py
# → http://localhost:8080

# Option B — Gunicorn (closer to production)
gunicorn -c gunicorn.dev.conf.py wsgi:app
# → http://localhost:8000
```

---

## API Reference

### Authentication

| Method | Endpoint         | Body                        | Description              |
|--------|------------------|-----------------------------|--------------------------|
| GET    | `/login`         | —                           | Render login page        |
| POST   | `/send-otp`      | `{ "email": "..." }`       | Send OTP to email        |
| POST   | `/verify-otp`    | `{ "email": "...", "otp": "..." }` | Verify OTP, create session |
| GET    | `/logout`        | —                           | Clear session            |
| POST   | `/check-trial`   | `{ "mode": 1 }`            | Check trial pages left   |

### Document Processing

| Method | Endpoint                  | Body / Params                                                  | Description                     |
|--------|---------------------------|----------------------------------------------------------------|---------------------------------|
| POST   | `/process`                | `multipart/form-data` — `file`, `mode`, `language`, `source_lang`, `target_lang`, `payment_id` (optional) | Upload & start processing |
| GET    | `/progress/<job_id>`      | —                                                              | Poll job progress (JSON)        |
| GET    | `/download/<filename>`    | —                                                              | Download processed DOCX         |
| POST   | `/send-document/<job_id>` | —                                                              | Email document to logged-in user |

### Payments

| Method | Endpoint           | Body                                      | Description                    |
|--------|--------------------|--------------------------------------------|--------------------------------|
| POST   | `/create-payment`  | `{ "mode": 2, "pages": 5 }`              | Create Razorpay order          |
| POST   | `/verify-payment`  | `{ "razorpay_order_id", "razorpay_payment_id", "razorpay_signature", "mode", "pages", "amount" }` | Verify signature & store record |

### Utility

| Method | Endpoint   | Description       |
|--------|------------|-------------------|
| GET    | `/health`  | Health check (`200 ok`) |

---

## Architecture Overview

```
┌──────────────┐      ┌──────────────┐      ┌──────────────────────┐
│   Browser    │─────▶│  Flask App   │─────▶│  Background Thread   │
│  (HTML CSS JS)│◀─────│  (Blueprints)│◀─────│  process_document.py │
└──────────────┘      └──────┬───────┘      └──────────┬───────────┘
     polling                 │                         │
     /progress/<id>          │                         ▼
                             │              ┌─────────────────────┐
                             │              │    Processors        │
                             │              │  ┌───────────────┐  │
                             │              │  │ OCRProcessor   │──┼──▶ Google Vision API
                             │              │  ├───────────────┤  │
                             │              │  │ ProofreadProc  │──┼──▶ Google Gemini API
                             │              │  ├───────────────┤  │
                             │              │  │ TranslationProc│──┼──▶ Google Gemini API
                             │              │  ├───────────────┤  │
                             │              │  │ AudioProcessor │──┼──▶ ElevenLabs + Gemini
                             │              │  └───────────────┘  │
                             │              └─────────────────────┘
                             │
                             ▼
                     ┌───────────────┐     ┌────────────────┐
                     │  MongoDB Atlas│     │  Gmail SMTP    │
                     │  (users,      │     │  (OTP + docs)  │
                     │   payments,   │     └────────────────┘
                     │   trial_usage)│
                     └───────────────┘
```

### Key Design Decisions

1. **Global Thread Pool** — A single `ThreadPoolExecutor(max_workers=10)` is shared across all users for Gemini API calls, preventing rate-limit exhaustion.
2. **In-Memory Progress Tracking** — `progress_tracker` (a dict in `config.py`) is polled by the frontend. This is stateless per-worker so it works with a single Gunicorn worker.
3. **Batched OCR** — PDF pages are processed in batches of 5 to avoid OOM on large documents. Each batch is garbage-collected before the next starts.
4. **Automatic File Cleanup** — A `threading.Timer` deletes both uploaded and output files 30 minutes after job completion.
5. **Dev Mode Bypasses** — When `ENV=development`, the `@login_required` and `@trial_required` decorators stub out authentication, and payment routes return fake order/payment IDs.

---

## Pricing (Default Configuration)

| Mode | Service                | Rate         |
|------|------------------------|-------------|
| 1    | OCR Only               | ₹3 / page   |
| 2    | OCR + Proofread        | ₹9 / page   |
| 3    | Proofread Only         | ₹6 / page   |
| 4    | OCR + Translation      | ₹9 / page   |
| 5    | Translation Only       | ₹6 / page   |
| 6    | Audio Transcription    | ₹10 / minute |

Pricing is defined in `routes/payment_routes.py` → `PRICING` dict.

---

## Development Notes

- **Font Support** — Output DOCX files use `Noto Serif Devanagari` (Hindi) and `Noto Serif Gujarati` (Gujarati). These must be installed on the server for proper rendering.
- **Max File Size** — 50 MB (set in `config.py` → `MAX_CONTENT_LENGTH`).
- **Max PDF Pages** — 200 pages (enforced in `utils.py`).
- **Trial Limits** — 3 pages per mode (document modes) or 3 minutes (audio mode), with ~3,333 characters per page equivalent for DOCX files.
- **Session Lifetime** — 24 hours, cookie is `HttpOnly` with `SameSite=Lax`.
- **Supported Inputs:**
  - Modes 1, 2, 4: PDF files
  - Modes 3, 5: DOCX files
  - Mode 6: MP3 / WAV audio files

---

## Deployment (Production)

The production Gunicorn config (`gunicorn.conf.py`) binds to a Unix socket:

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

Pair with **Nginx** as a reverse proxy:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://unix:/run/gunicorn/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
```

> Make sure the socket directory (`/run/gunicorn/`) exists and has proper permissions.


## License

This project is proprietary. All rights reserved.
