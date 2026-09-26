# ChatWell Personal AI Therapist

ChatWell is a semester project with a server-rendered FastAPI interface, a mood tracker, and a retrieval-augmented chatbot. The chatbot uses a local ChromaDB index to retrieve coping guidelines and sends the retrieved context and user input to Groq's hosted `openai/gpt-oss-120b` model for an answer. It is a prototype for supportive conversation, not a clinical service or a substitute for professional or emergency care.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py` | FastAPI backend, SQLite access, retrieval pipeline, and HTTP routes. |
| `app.ipynb` | Optional notebook launcher for the FastAPI app. |
| `.python-version`, `pyproject.toml`, and `uv.lock` | Python 3.14.2 selection, dependencies, and their uv lockfile. |
| `templates/index.html` and `static/` | Unified Jinja2 page, browser JavaScript, and static CSS. |
| `knowledge.txt` | Coping guidelines used to populate the ChromaDB index. |
| `therapist.db` | Local SQLite storage for moods and chat history. Created if absent. |
| `chroma_db/` | Local vector index. Populated on the first chat if empty. |
| `package.json` | Tailwind CSS build tooling for the unified page. |
| `Documentation/` | Original project report, presentation, and demonstration assets. |

## Run locally

Install [uv](https://docs.astral.sh/uv/) and use Python 3.14.2. Create a free [Groq API key](https://console.groq.com/keys) in your Groq account. No Hugging Face login or Meta model download is needed for answer generation. From the repository root:

```powershell
uv venv .venv --python 3.14.2
uv sync --locked
```

In VS Code, select `.venv\Scripts\python.exe` with **Python: Select Interpreter** if the editor still marks the LangChain imports in `app.py` as missing. The repository's workspace setting uses that interpreter for new selections; VS Code keeps any interpreter you previously selected for this folder.

Create `.env` from the committed [example](.env.example) if it is absent, then open it and replace the blank value with your key (`GROQ_API_KEY=gsk_...`). If `.env` already exists, edit that file. Start the web application:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
uv run --locked uvicorn app:app --host localhost --port 5000
```

The backend loads `.env` when chat starts. An existing `GROQ_API_KEY` in the shell takes precedence over the file. Keep `.env` private; only `.env.example` is meant to be committed.

`GROQ_MODEL` is optional. The default is `openai/gpt-oss-120b`; enable that model in [Groq model permissions](https://console.groq.com/docs/model-permissions). Set `GROQ_MODEL` in `.env` to override the default, then restart the server. The previous `qwen/qwen3.8-27b` model remains available as an override if your account permits it.

Keep the account on Groq's **Free** plan if you do not want charges. ChatWell uses one hosted model and has no paid fallback. Groq applies separate per-request output limits and account rate limits. Its published [Free plan limits](https://console.groq.com/docs/rate-limits) for this model include 30 requests/minute and 1,000 requests/day; check your account's exact token limits in the Groq console. ChatWell gives GPT-OSS-120B a 1,024-token completion allowance with low reasoning effort, leaving more room for the concise visible reply than the former 512-token setting. Qwen remains at 512 tokens if selected as an override. If Groq stops at the output limit, the chat displays a notice. On a 429, the chat displays the particular quota and retry time when Groq provides them. A Groq API key is separate from your approved access to Meta's model on Hugging Face.

Groq requests can occasionally time out. ChatWell waits up to 90 seconds and then shows a retry message; the unsent draft stays in the text box. Failed chat requests are not saved to the local history. The app does not automatically send another request, so you control whether to retry.

Open <http://localhost:5000/> for the unified chatbot and mood tracker. The page is rendered on the server through Jinja2; the chat form sends JSON to `POST /chat`, and the mood form submits to `POST /add_mood`. Old links to `GET /chat` redirect to the chat section of the unified page. FastAPI also provides API documentation at <http://localhost:5000/docs>.

The notebook is optional. Register its Python 3.14.2 kernel after creating `.venv`, then launch Jupyter and select **ChatWell (.venv, Python 3.14.2)**:

```powershell
uv run --locked python -m ipykernel install --prefix .venv --name chatwell-venv --display-name "ChatWell (.venv, Python 3.14.2)"
uv run --locked jupyter notebook app.ipynb
```

Execute the notebook cells in order. Its former `pip install` cell has been replaced by `uv sync --locked`; `pyproject.toml` is the dependency source of truth. The notebook uses the same project `.env` file through `app.py`. The first chat may download the small `all-MiniLM-L6-v2` embedding model to build the local index; it does not download a text-generation model. Retrieval still uses local CPU resources. The default Groq model and generation settings are in `app.py`.

The unified dark page uses Tailwind utilities from `templates/index.html` and `static/script.js`. Its background is static. The compiled stylesheet is included in the repository. After changing the page or chat styling, rebuild it in PowerShell with `npm.cmd install` (if dependencies are missing) and `npm.cmd run dev-build`. The HTML versions the stylesheet and script URLs so refreshed pages fetch updated assets. Restart the server and refresh the page if a previous version is still open.

Run the backend route tests with `uv run --locked pytest -q`.

## Data and security

The mood tracker saves entries in `therapist.db`. The chatbot saves user messages and model replies there after a successful response. The browser keeps a chat session identifier in local storage. Each new answer receives up to eight recent messages from that session so follow-up questions can refer to earlier advice. Chat input, those recent messages, the form's age/sex/duration fields, and retrieved knowledge excerpts are sent to Groq for each answer. Use synthetic examples or obtain appropriate consent before sending real mental-health information. Groq's [data controls](https://console.groq.com/docs/your-data) describe its retention and Zero Data Retention settings. There are no user accounts or access controls, so keep the app bound to localhost and do not expose it on a shared network or the public internet. Keep `GROQ_API_KEY` private and out of Git; `.env` files are ignored.

The original repository committed `therapist.db` and `chroma_db/`. They are now ignored and staged for removal from Git tracking, but the original data remains in Git history. Review that history before sharing the repository, especially if any chat records contain real personal information.

The Python dependency audit reports ChromaDB advisories involving its network server API, including [CVE-2026-45829](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c). This application uses an embedded local Chroma index and does not start Chroma's HTTP server. Do not expose a separate Chroma server; review the advisories again when ChromaDB publishes fixes.

The crisis keyword check is limited and can miss or misclassify situations. The model may return inaccurate or unsafe advice. The app has not been validated for clinical use.

## License and attribution

The source code is available under the [ISC License](LICENSE). The original project author is **Faraz Hussain**. You may use, copy, modify, and redistribute the code, including commercially, provided you retain the copyright and permission notice in copies. This attribution also applies to reused or modified versions of the original source code.
