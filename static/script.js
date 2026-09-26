const chatForm = document.getElementById("chat-form");
const chatBox = document.getElementById("chat-box");
const sendButton = document.getElementById("send-button");
const messageInput = document.getElementById("symptoms");

function appendMessage(label, message, kind) {
    const row = document.createElement("div");
    row.className = kind === "user"
        ? "ml-auto flex max-w-[90%] justify-end sm:max-w-[80%]"
        : "flex max-w-[90%] items-start gap-3 sm:max-w-[80%]";
    row.dataset.kind = kind;

    if (kind !== "user") {
        const avatar = document.createElement("div");
        avatar.className = "grid size-8 shrink-0 place-items-center rounded-lg bg-emerald-400/15 text-emerald-300";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = "✦";
        row.appendChild(avatar);
    }

    const body = document.createElement("div");
    body.className = "min-w-0";
    const name = document.createElement("span");
    name.className = kind === "user"
        ? "mb-1 block text-right text-xs font-semibold text-zinc-400"
        : "mb-1 block text-xs font-semibold text-zinc-400";
    name.textContent = label;
    const text = document.createElement("p");
    const commonText = "whitespace-pre-wrap break-words rounded-2xl border px-4 py-3 text-[15px] leading-7";
    if (kind === "user") {
        text.className = `${commonText} rounded-tr-sm border-emerald-600 bg-emerald-700 text-white`;
    } else if (kind === "error") {
        text.className = `${commonText} rounded-tl-sm border-rose-700 bg-rose-950 text-rose-100`;
    } else {
        text.className = `${commonText} rounded-tl-sm border-zinc-700 bg-zinc-800 text-zinc-100`;
    }
    text.textContent = message;
    body.append(name, text);
    row.appendChild(body);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
    return row;
}

chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const symptoms = messageInput.value.trim();
    if (!symptoms || sendButton.disabled) return;

    let sessionId = localStorage.getItem("chat_session_id");
    if (!sessionId) {
        sessionId = crypto.randomUUID();
        localStorage.setItem("chat_session_id", sessionId);
    }

    const payload = {
        symptoms,
        age: document.getElementById("age").value,
        sex: document.getElementById("sex").value,
        duration: document.getElementById("duration").value,
        session_id: sessionId,
    };

    const userMessage = appendMessage("You", symptoms, "user");
    messageInput.value = "";
    sendButton.disabled = true;
    chatBox.setAttribute("aria-busy", "true");
    const pending = appendMessage("ChatWell", "Thinking…", "pending");

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || !data.response) {
            throw new Error(data.error || "The reply could not be loaded. Please try again.");
        }
        appendMessage("ChatWell", data.response, "assistant");
        if (data.truncated) {
            appendMessage("Notice", "This reply stopped at its output limit. Please resend your message.", "error");
        }
    } catch (error) {
        userMessage.remove();
        appendMessage("Error", error.message || "Could not contact the server.", "error");
        messageInput.value = symptoms;
        messageInput.focus();
    } finally {
        pending.remove();
        sendButton.disabled = false;
        chatBox.removeAttribute("aria-busy");
    }
});
