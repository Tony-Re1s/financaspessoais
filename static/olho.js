// Olho de esconder valores — roda no navegador, sem recarregar a página.
// Troca "R$ 1.234,56" por "R$ ••••" nos textos da tela e borra gráficos; lembra a escolha neste aparelho.
(function () {
  const D = document, KEY = "fin_ocultar";
  if (window.__olho) { window.__olho.garantir(); window.__olho.aplicar(); return; }
  const RX = /(-?R\$\s?)\d{1,3}(?:\.\d{3})*,\d{2}/g;
  const MASK = "$1••••";
  const original = new WeakMap();
  let ligado = false, ocupado = false, pendente = false;
  try { ligado = localStorage.getItem(KEY) === "1"; } catch (e) {}

  const OLHO = '\u003csvg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\u003cpath d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>\u003ccircle cx="12" cy="12" r="3"/>\u003c/svg>';
  const FECHADO = '\u003csvg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\u003cpath d="M17.9 17.9A10 10 0 0 1 12 19c-6.5 0-10-7-10-7a18 18 0 0 1 4.1-5.1M9.9 5.2A9 9 0 0 1 12 5c6.5 0 10 7 10 7a18 18 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/>\u003cpath d="M2 2l20 20"/>\u003c/svg>';

  function textos(raiz, fn) {
    const w = D.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        const p = n.parentElement;
        if (!p || p.closest("script,style,textarea,input,#fin-olho")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let n; while ((n = w.nextNode())) fn(n);
  }

  function aplicar() {
    if (ocupado) return;
    ocupado = true;
    try {
      D.documentElement.classList.toggle("fin-oculto", ligado);
      textos(D.body, (n) => {
        const v = n.nodeValue;
        if (ligado) {
          if (v.indexOf("R$") < 0) return;
          RX.lastIndex = 0;
          if (!RX.test(v)) return;
          original.set(n, v);
          n.nodeValue = v.replace(RX, MASK);
        } else if (original.has(n)) {
          const o = original.get(n);
          if (v === o.replace(RX, MASK)) n.nodeValue = o;
          original.delete(n);
        }
      });
      const b = D.getElementById("fin-olho");
      if (b) { b.innerHTML = ligado ? FECHADO : OLHO; b.title = ligado ? "Mostrar valores" : "Esconder valores"; }
    } finally { ocupado = false; }
  }

  function garantir() {
    if (D.getElementById("fin-olho")) return;
    const alvo = D.querySelector('[data-testid="stMainBlockContainer"]') || D.querySelector(".block-container");
    if (!alvo) return;
    const b = D.createElement("button");
    b.id = "fin-olho"; b.type = "button";
    b.addEventListener("click", () => {
      ligado = !ligado;
      try { localStorage.setItem(KEY, ligado ? "1" : "0"); } catch (e) {}
      aplicar();
    });
    alvo.appendChild(b);
    aplicar();
  }

  new MutationObserver(() => {
    if (ocupado || pendente) return;
    pendente = true;
    requestAnimationFrame(() => { pendente = false; garantir(); if (ligado) aplicar(); });
  }).observe(D.body, { childList: true, subtree: true, characterData: true });

  window.__olho = { aplicar, garantir };
  garantir(); aplicar();
})();
