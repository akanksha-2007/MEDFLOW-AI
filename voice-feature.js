/*
  Drop-in voice controls for MediFlow.
  Requires no backend/API key. Best support: Chrome and Microsoft Edge.
*/
(() => {
  "use strict";

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const inputSelectors = ["#messageInput", "#message-input", "#chatInput", "textarea", "input[type='text']"];
  // Exact assistant-reply selector used by the supplied MediFlow HTML.
  const assistantSelectors = ".row.agent .bubble";

  function findChatInput() {
    for (const selector of inputSelectors) {
      const element = document.querySelector(selector);
      if (element && !element.disabled) return element;
    }
    return null;
  }

  function announce(message, isError = false) {
    const status = document.getElementById("voice-status");
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("voice-error", isError);
  }

  function injectStyles() {
    const style = document.createElement("style");
    style.textContent = `
      #voice-controls { position: relative; display: flex; align-items: center; }
      .voice-control { border: 0; border-radius: 12px; width: 42px; height: 42px; cursor: pointer; background: var(--tool-tag-bg, #e8f2ff); color: var(--ink, #0b5cab); font-size: 18px; }
      .voice-control:hover { background: #cfe5ff; }
      .voice-control.listening { background: #c62828; color: #fff; animation: voice-pulse 1s infinite; }
      .voice-language { border: 1px solid var(--line, #d1d5db); border-radius: 8px; cursor: pointer; height: 30px; padding: 0 6px; background: var(--panel, #fff); color: var(--ink, #111827); font-size: 11px; font-weight: 700; }
      .voice-speak { border: 0; background: transparent; cursor: pointer; font-size: 15px; margin-left: 6px; color: #0b5cab; }
      #voice-status { position: absolute; right: 0; bottom: 48px; width: 230px; font-size: 12px; min-height: 16px; color: var(--ink-soft, #4b5563); background: var(--panel, #fff); border-radius: 6px; text-align: right; }
      #voice-status.voice-error { color: #b91c1c; }
      @keyframes voice-pulse { 50% { transform: scale(1.08); } }
    `;
    document.head.appendChild(style);
  }

  function addSpeakButton(messageElement) {
    if (messageElement.dataset.voiceReady === "true") return;
    const text = messageElement.innerText.trim();
    if (!text) return;
    messageElement.dataset.voiceReady = "true";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "voice-speak";
    button.title = "Listen to this reply";
    button.setAttribute("aria-label", "Listen to this reply");
    button.textContent = "🔊 Listen";
    button.addEventListener("click", () => window.mediFlowSpeak(text));
    messageElement.appendChild(button);
  }

  function observeAssistantReplies() {
    document.querySelectorAll(assistantSelectors).forEach(addSpeakButton);
    new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          if (node.matches(assistantSelectors)) addSpeakButton(node);
          node.querySelectorAll?.(assistantSelectors).forEach(addSpeakButton);
        });
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  function setupMicrophone() {
    const input = findChatInput();
    if (!input) {
      console.warn("Voice feature: chat input not found.");
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.id = "voice-controls";
    const status = document.createElement("div");
    status.id = "voice-status";
    status.setAttribute("aria-live", "polite");
    const mic = document.createElement("button");
    mic.type = "button";
    mic.className = "voice-control";
    mic.title = "Speak your message";
    mic.setAttribute("aria-label", "Speak your message");
    mic.textContent = "🎤";
    const languageButton = document.createElement("button");
    languageButton.type = "button";
    languageButton.className = "voice-language";
    languageButton.title = "Switch voice language";
    let recognitionLanguage = "en-IN";
    languageButton.textContent = "EN";
    languageButton.addEventListener("click", () => {
      recognitionLanguage = recognitionLanguage === "en-IN" ? "hi-IN" : "en-IN";
      languageButton.textContent = recognitionLanguage === "hi-IN" ? "हि" : "EN";
      announce(recognitionLanguage === "hi-IN" ? "Hindi voice selected." : "English voice selected.");
    });
    wrapper.append(status, mic, languageButton);
    input.insertAdjacentElement("afterend", wrapper);

    if (!Recognition) {
      mic.disabled = true;
      mic.title = "Voice input works in Chrome or Microsoft Edge";
      announce("Voice input is not supported in this browser.", true);
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = recognitionLanguage;
    let isListening = false;
    let finalText = "";

    mic.addEventListener("click", () => {
      if (isListening) {
        recognition.stop();
        return;
      }
      finalText = "";
      recognition.lang = recognitionLanguage;
      try { recognition.start(); } catch (_) { /* already starting; ignore */ }
    });

    recognition.onstart = () => {
      isListening = true;
      mic.classList.add("listening");
      mic.textContent = "■";
      announce("Listening… speak now.");
    };
    recognition.onresult = (event) => {
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index][0].transcript;
        if (event.results[index].isFinal) finalText += transcript;
        else interimText += transcript;
      }
      input.value = finalText || interimText;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };
    recognition.onerror = (event) => {
      const messages = {
        "not-allowed": "Microphone permission was denied. Allow it in browser settings.",
        "no-speech": "No speech was heard. Please try again.",
        "network": "Speech recognition needs an internet connection.",
      };
      announce(messages[event.error] || `Voice input error: ${event.error}`, true);
    };
    recognition.onend = () => {
      isListening = false;
      mic.classList.remove("listening");
      mic.textContent = "🎤";
      if (finalText) announce("Voice text added. Review it, then send.");
    };
  }

  window.mediFlowSpeak = (text) => {
    if (!("speechSynthesis" in window)) {
      alert("Text-to-speech is not supported in this browser.");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = navigator.language && navigator.language.startsWith("hi") ? "hi-IN" : "en-IN";
    utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
  };

  document.addEventListener("DOMContentLoaded", () => {
    injectStyles();
    setupMicrophone();
    observeAssistantReplies();
  });
})();
