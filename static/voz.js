// Lançar por voz: botão de microfone que dita (reconhecimento de fala do próprio navegador, pt-BR),
// escreve no campo de texto do Lançamento rápido; ao terminar, a tela manda a IA ler sozinha.
(function () {
  const D = document;
  const caixa = D.querySelector(".st-key-voz_btn");
  if (!caixa || caixa.querySelector(".fin-mic")) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  const btn = D.createElement("button");
  btn.type = "button";
  btn.className = "fin-mic";
  const info = D.createElement("div");
  info.className = "fin-mic-info";
  caixa.appendChild(btn);
  caixa.appendChild(info);

  function campo() { return D.querySelector(".st-key-rap_txt textarea"); }
  function escrever(txt) {
    const t = campo();
    if (!t) return;
    const set = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
    set.call(t, txt);
    t.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function confirmar() {
    const t = campo();
    if (!t) return;
    t.focus();
    t.blur();            // o Streamlit guarda o texto ao sair do campo e a tela já manda a IA ler
  }
  function estado(gravando, msg) {
    btn.classList.toggle("on", gravando);
    btn.textContent = gravando ? "⏹️  Parar" : "🎤  Toque e fale";
    info.textContent = msg || "";
  }

  if (!SR) {
    btn.disabled = true;
    estado(false, "Este navegador não tem ditado. Use o 🎤 do teclado do celular no campo abaixo.");
    return;
  }

  let rec = null, falando = false, final = "";
  btn.addEventListener("click", () => {
    if (falando && rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = "pt-BR";
    rec.interimResults = true;
    rec.continuous = false;
    final = "";
    rec.onstart = () => { falando = true; estado(true, "Ouvindo… ex.: “mercado 85 e 90 no débito do Itaú”"); };
    rec.onresult = (ev) => {
      let parcial = "";
      for (let i = ev.resultIndex; i !== ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) final += r[0].transcript + " ";
        else parcial += r[0].transcript;
      }
      escrever((final + parcial).trim());
    };
    rec.onerror = (ev) => {
      const m = ev.error === "not-allowed" || ev.error === "service-not-allowed"
        ? "Sem permissão para o microfone — libere nas configurações do navegador."
        : ev.error === "no-speech" ? "Não ouvi nada. Tente de novo." : "Erro no ditado: " + ev.error;
      estado(false, m);
    };
    rec.onend = () => {
      falando = false;
      if (final.trim()) { estado(false, "Entendi! Lendo com a IA…"); escrever(final.trim()); confirmar(); }
      else if (!info.textContent || info.textContent.startsWith("Ouvindo")) estado(false, "");
    };
    try { rec.start(); } catch (e) { estado(false, "Não consegui abrir o microfone."); }
  });
  estado(false, "");
})();
