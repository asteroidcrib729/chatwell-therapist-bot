document.getElementById("chat-form").addEventListener("submit", function (event) {
    event.preventDefault();

    // Collect user input
    const symptoms = document.getElementById("symptoms").value;
    const duration = document.getElementById("duration").value;
    const age = document.getElementById("age").value;
    const sex = document.getElementById("sex").value;

    const chatBox = document.getElementById("chat-box");

    // --- FIX 1: DISPLAY NATURAL MESSAGE ---
    // Instead of forcing a sentence, we display exactly what the user typed.
    // We add the context (Age/Sex) in small text below it.
    chatBox.innerHTML += `
        <div style="text-align: right; margin: 10px 0;">
            <p style="background: #A7FEDE; color: black; padding: 10px 15px; border-radius: 15px 15px 0 15px; display: inline-block; text-align: left;">
                <strong>You:</strong> ${symptoms}
                <br>
                <small style="opacity: 0.7; font-size: 0.8em;">(Context: ${age}yr ${sex}, ${duration})</small>
            </p>
        </div>`;

    // Generate/Get Session ID
    let sessionId = localStorage.getItem("chat_session_id");
    if (!sessionId) {
        sessionId = "user_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("chat_session_id", sessionId);
    }

    // Send data to backend
    fetch("/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            symptoms: symptoms,
            duration: duration,
            age: age,
            sex: sex,
            session_id: sessionId
        })
    })
        .then(response => response.json())
        .then(data => {
            if (data.response) {
                // --- FIX 2: IMPROVE AI BUBBLE STYLE ---
                chatBox.innerHTML += `
                <div style="text-align: left; margin: 10px 0;">
                    <p style="background: rgba(255,255,255,0.1); color: white; border: 1px solid rgba(255,255,255,0.2); padding: 10px 15px; border-radius: 15px 15px 15px 0; display: inline-block;">
                        <strong>Therapist AI:</strong><br>
                        ${data.response.replace(/\n/g, '<br>')}
                    </p>
                </div>`;
            } else if (data.error) {
                chatBox.innerHTML += `<p style="color: red;"><strong>Error:</strong> ${data.error}</p>`;
            }
            // Auto-scroll to bottom
            chatBox.scrollTop = chatBox.scrollHeight;
        })
        .catch(error => {
            console.error('Error:', error);
        });

    // Clear the main input field only
    document.getElementById("symptoms").value = "";
});