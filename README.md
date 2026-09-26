# ChatWell: RAG Mental Health Support Prototype

I built ChatWell as a semester project to explore retrieval-augmented generation (RAG). I used a server-rendered FastAPI page for a support chatbot and mood tracker. For each chat reply, coping guidance is retrieved from a local ChromaDB index and sent with the conversation context to Groq's hosted `openai/gpt-oss-120b` model. ChatWell is a support prototype. I have not validated it for clinical use or emergency care.

## How I built it

1. Coping guidance has been kept in `knowledge.txt`. On the first chat, `app.py` builds a local ChromaDB index using the public `all-MiniLM-L6-v2` embedding model if the index is empty.
2. Three relevant excerpts are retrieved for each message. Those excerpts along with the current message and up to eight recent messages are sent from the same browser session to Groq for an answer.
3. Successful user messages and model replies, plus mood entries are saved in a local SQLite database named `therapist.db`. Browser-stored session IDs are used to keep conversations separate.
4. A unified webpage containing both the chatbot and mood tracker interfaces is rendered with Jinja2 from `templates/index.html`. The browser sends chat messages to `POST /chat` and submits moods to `POST /add_mood`. The mood tracker does not call Groq.

The backend and RAG pipeline are kept in `app.py`. `pyproject.toml` and `uv.lock` are used for Python dependencies, `static/` for browser assets, and `package.json` for Tailwind CSS tooling. The `Documentation/` folder contains the original project report, presentation, and demonstration assets. The `app.ipynb` notebook is an optional way to launch the app.

## Run my project locally

I used Python 3.14.2 and [uv](https://docs.astral.sh/uv/). You also need a [Groq API key](https://console.groq.com/keys) with `openai/gpt-oss-120b` enabled in [Groq model permissions](https://console.groq.com/docs/model-permissions). You do not need the Ollama application, a Meta model download, or a Hugging Face login for text generation.

From the repository root, run these commands in PowerShell:

```powershell
uv venv .venv --python 3.14.2
uv sync --locked
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

In `.env`, set `GROQ_API_KEY` to your own key. I keep this file out of Git; `.env.example` shows the variable without a secret. An existing `GROQ_API_KEY` in your shell takes precedence over the file. You can set `GROQ_MODEL` in `.env` to override the default model. Restart the server after changing either value.

Start the server:

```powershell
uv run --locked uvicorn app:app --host localhost --port 5000
```

Open <http://localhost:5000/> for the chatbot and mood tracker. Both are served on one page. FastAPI's API documentation can be reviewed at <http://localhost:5000/docs>.

If VS Code marks imports in `app.py` as missing, use **Python: Select Interpreter** and choose `.venv\Scripts\python.exe`. The repository includes a workspace setting for that interpreter, but VS Code may retain an earlier selection.

## Model limits and failures

I used Groq's **Free** plan and have not configured a paid fallback. I gave GPT-OSS-120B a 1,024-token completion allowance with low reasoning effort. This is a limit per answer; Groq also applies account rate limits, which you can check in its [current limit documentation](https://console.groq.com/docs/rate-limits) and your Groq console. If a reply reaches the answer limit, a notice appears. If Groq rejects a request with HTTP 429, another notice shows the named quota and retry time.

Wait up to 90 seconds for Groq to answer a query. If the request times out or fails, the draft is kept in the text box for a manual retry. Chat messages are saved only after a successful reply. I did not implement automatic retries because that would use another request from the quota. If your account permits it, you can select the earlier `qwen/qwen3.8-27b` model through `GROQ_MODEL`.

## Optional notebook and styling

The same server can be launched from `app.ipynb`. After creating `.venv`, register its kernel and open the notebook:

```powershell
uv run --locked python -m ipykernel install --prefix .venv --name chatwell-venv --display-name "ChatWell (.venv, Python 3.14.2)"
uv run --locked jupyter notebook app.ipynb
```

Run the notebook cells in order. I managed dependencies through `uv sync --locked` rather than installing packages inside the notebook. The first chat may download the public embedding model and build the local index; it does not download a text-generation model.

I styled the page with Tailwind utilities in `templates/index.html` and `static/script.js`. The compiled stylesheet is included. After changing page or chat styling, rebuild it in PowerShell:

```powershell
npm.cmd install
npm.cmd run dev-build
```

I versioned the CSS and JavaScript URLs in the rendered HTML so a page refresh loads updated assets.

## Test my project

I ran the backend tests from the repository root:

```powershell
uv run --locked pytest -q
```

## Data, privacy, and safety

I stored moods and successful chats locally in `therapist.db`. The page does not redraw old chat bubbles after a refresh, but I have kept the browser's session ID and used recent saved messages as context for the next reply. I sent the current message, up to eight recent messages, optional age/gender/duration fields, and retrieved guidance to Groq. I recommend using synthetic examples or obtaining appropriate consent before entering real mental-health information. Groq describes its retention settings in its [data controls](https://console.groq.com/docs/your-data).

I bind the server to localhost because I have not built user accounts or access controls. I ignore `.env`, `therapist.db`, and `chroma_db/` in the current Git tree. An earlier version committed the database and index, so their contents remain in Git history. Review that history before sharing or forking the repository, especially if any chat records contain personal information.

I use ChromaDB as an embedded local index. A [ChromaDB security advisory](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) concerns its network server API, which I do not start. I keep the index local and do not expose a separate Chroma server. My crisis keyword check is limited and can miss or misclassify situations, and model advice can be wrong or unsafe. I have not validated ChatWell for clinical use.

## License and attribution

I, **Faraz Hussain**, release the original source code under the [ISC License](LICENSE). You may use, copy, modify, and redistribute it, including commercially, as long as you retain the copyright and permission notice in every copy. Please retain that credit when reusing or modifying my work.
