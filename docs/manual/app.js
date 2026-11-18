// Manual técnico: índice, notas presas aos parágrafos (marcas expansíveis), caderno e exportação.
// Sem servidor: as notas ficam no localStorage do navegador e podem ser exportadas (.md) ou levadas
// para outra máquina pelo backup (.json).
'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// Aberto do disco (file://) ou de um servidor local, os arquivos citados abrem direto da pasta do repositório;
// publicado em outro lugar, viram links para o GitHub.
const LOCAL = location.protocol === 'file:' || ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
const REPOSITORIO = 'https://github.com/DataLabUFU/Hackthon-NASA-2026/blob/main/';
const CHAVE_NOTAS = 'rotasafra-manual:notas';

const pranchas = $$('.prancha');
const tituloDe = (id) => {
    const p = document.getElementById(id);
    return p ? `${$('.numero', p).textContent} · ${p.dataset.titulo}` : 'Geral';
};

function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function markdown(text) {
    if (window.marked && window.DOMPurify) return DOMPurify.sanitize(marked.parse(text || '', { gfm: true, breaks: true }));
    return `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;
}

function quando(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
        + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

const guardar = {
    ler(chave, padrao) { try { return JSON.parse(localStorage.getItem(chave)) ?? padrao; } catch { return padrao; } },
    gravar(chave, valor) {
        try { localStorage.setItem(chave, JSON.stringify(valor)); return true; } catch { return false; }
    },
};

// ---------- Âncoras estáveis por parágrafo ----------
// O id vem do próprio texto, não da posição: reeditar outra parte do manual não move as notas.

function hashTexto(texto) {
    let h = 5381;
    for (const c of texto) h = ((h << 5) + h + c.codePointAt(0)) >>> 0;
    return h.toString(36);
}

for (const prancha of pranchas) {
    const usados = new Map();
    for (const el of $$('.conteudo > p, .conteudo li, .conteudo > figure, .conteudo .rolagem, .conteudo > .dica, .conteudo > .aviso, .conteudo > .formula', prancha)) {
        const base = `${prancha.id}-${hashTexto(el.textContent.replace(/\s+/g, ' ').trim().slice(0, 160))}`;
        const n = (usados.get(base) || 0) + 1;
        usados.set(base, n);
        el.dataset.ancora = n === 1 ? base : `${base}-${n}`;
    }
}

// ---------- Índice e prancha atual ----------

const lista = $('#lista-pranchas');
lista.innerHTML = pranchas.map((p) => `
    <li><a href="#${p.id}" data-prancha="${p.id}">
        <span class="num">${$('.numero', p).textContent}</span>
        <span>${escapeHtml(p.dataset.titulo)}</span>
        <span class="qtd-notas" data-qtd="${p.id}"></span>
    </a></li>`).join('');

const observador = new IntersectionObserver((entradas) => {
    for (const e of entradas) {
        if (!e.isIntersecting) continue;
        $$('a[data-prancha]', lista).forEach((a) => a.classList.toggle('atual', a.dataset.prancha === e.target.id));
    }
}, { rootMargin: '-45% 0px -50% 0px' });
pranchas.forEach((p) => observador.observe(p));

lista.addEventListener('click', () => document.body.classList.remove('indice-aberto'));
$('#abrir-indice').addEventListener('click', () => document.body.classList.toggle('indice-aberto'));

// Botão de nota no cabeçalho de cada prancha e fichas de arquivos
for (const p of pranchas) {
    $('.acoes', p).innerHTML = `<button class="botao pequeno caneta" data-nova-nota="${p.id}">✎ Nota</button>`;
}
for (const caixa of $$('.arquivos')) {
    caixa.innerHTML = caixa.dataset.arquivos.split(/\s+/).filter(Boolean).map((f) => {
        const href = LOCAL ? `../../${encodeURI(f)}` : `${REPOSITORIO}${encodeURI(f)}`;
        return `<a class="arquivo" href="${href}" target="_blank" rel="noopener">${escapeHtml(f)}</a>`;
    }).join('');
}

// ---------- Notas ----------

let notas = guardar.ler(CHAVE_NOTAS, []);

function mostrarContagem() {
    $('#status').textContent = `${notas.length} ${notas.length === 1 ? 'nota' : 'notas'} neste navegador`;
}

function salvarNotas() {
    if (!guardar.gravar(CHAVE_NOTAS, notas)) {
        alert('O navegador não deixou salvar (modo privado ou armazenamento cheio). Exporte as notas para não perdê-las.');
    }
    mostrarContagem();
}

function novoId() {
    return (crypto.randomUUID && crypto.randomUUID()) || `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function htmlMarca(nota) {
    return `
        <details class="marca" data-nota="${nota.id}">
            <summary>${escapeHtml(nota.titulo || 'Nota sem título')}<span class="quando">${quando(nota.atualizadaEm)}</span></summary>
            <div class="corpo">
                ${nota.trecho ? `<blockquote>${escapeHtml(nota.trecho)}</blockquote>` : ''}
                <div class="texto-nota markdown">${markdown(nota.texto)}</div>
                <div class="acoes-nota">
                    <button class="botao pequeno caneta" data-editar="${nota.id}">Editar</button>
                    <button class="botao pequeno" data-apagar="${nota.id}">Apagar</button>
                </div>
            </div>
        </details>`;
}

// Onde a caixa de marcas de um parágrafo fica: logo depois dele (ou dentro, no fim, se for item de lista).
function caixaDeMarcas(ancora, criar = true) {
    const alvo = $(`[data-ancora="${CSS.escape(ancora)}"]`);
    if (!alvo) return null;
    const dentro = alvo.tagName === 'LI';
    let caixa = dentro ? $(':scope > .marcas', alvo) : (alvo.nextElementSibling?.classList.contains('marcas') ? alvo.nextElementSibling : null);
    if (!caixa && criar) {
        caixa = document.createElement('div');
        caixa.className = 'marcas';
        caixa.dataset.de = ancora;
        if (dentro) alvo.appendChild(caixa); else alvo.after(caixa);
    }
    return caixa;
}

function caixaGeral(prancha) {
    const conteudo = $('.conteudo', prancha);
    let bloco = $(':scope > .notas-gerais', conteudo);
    if (!bloco) {
        bloco = document.createElement('div');
        bloco.className = 'notas-gerais';
        bloco.innerHTML = `<h3>Notas da prancha</h3><div class="marcas"></div>
            <button class="botao pequeno caneta" data-nova-nota="${prancha.id}">✎ Nova nota</button>`;
        conteudo.appendChild(bloco);
    }
    return $('.marcas', bloco);
}

function desenharNotas() {
    // guarda quais marcas estavam abertas para não fechar tudo a cada redesenho
    const abertas = new Set($$('.marca[open]').map((d) => d.dataset.nota));
    $$('.marcas[data-de]').forEach((c) => c.remove());
    $$('[data-ancora].tem-nota').forEach((el) => el.classList.remove('tem-nota'));
    pranchas.forEach((p) => { caixaGeral(p).innerHTML = ''; });

    for (const nota of notas) {
        let caixa = null;
        if (nota.ancora) {
            caixa = caixaDeMarcas(nota.ancora);
            if (caixa) $(`[data-ancora="${CSS.escape(nota.ancora)}"]`).classList.add('tem-nota');
        }
        if (!caixa) {
            // parágrafo reescrito ou prancha que não existe mais: a nota vai para o fim da prancha (ou da primeira)
            caixa = caixaGeral(document.getElementById(nota.prancha) || pranchas[0]);
        }
        caixa.insertAdjacentHTML('beforeend', htmlMarca(nota));
    }

    pranchas.forEach((p) => {
        const qtd = notas.filter((n) => n.prancha === p.id).length;
        $(`[data-qtd="${p.id}"]`).textContent = qtd ? `✎${qtd}` : '';
    });
    abertas.forEach((id) => { const d = $(`.marca[data-nota="${id}"]`); if (d) d.open = true; });
    if ($('#caderno').open) desenharCaderno();
}

// Formulário de nota, aberto no lugar onde a nota vai ficar.
function abrirFormulario({ prancha, ancora = null, trecho = null, nota = null }) {
    $$('.formulario-nota').forEach((f) => f.remove());
    const form = document.createElement('form');
    form.className = 'formulario-nota';
    const valorTrecho = nota?.trecho ?? trecho;
    form.innerHTML = `
        ${valorTrecho ? `<blockquote>${escapeHtml(valorTrecho)}</blockquote>` : ''}
        <label>Título<input name="titulo" maxlength="200" value="${escapeHtml(nota?.titulo || '')}" placeholder="Ex.: por que a T4 tem peso baixo?"></label>
        <label>Nota (aceita Markdown)<textarea name="texto" placeholder="O que eu entendi, o que ainda não entendi…">${escapeHtml(nota?.texto || '')}</textarea></label>
        <div class="acoes-nota">
            <button type="button" class="botao pequeno" data-cancelar>Cancelar</button>
            <button type="submit" class="botao pequeno caneta">${nota ? 'Salvar alterações' : 'Salvar nota'}</button>
        </div>`;

    const marca = nota && $(`.marca[data-nota="${nota.id}"]`);
    if (marca) marca.replaceWith(form);
    else if (ancora && caixaDeMarcas(ancora)) caixaDeMarcas(ancora).prepend(form);
    else caixaGeral(document.getElementById(prancha) || pranchas[0]).after(form);
    form.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    form.elements.titulo.focus();

    form.addEventListener('click', (e) => { if (e.target.matches('[data-cancelar]')) { form.remove(); desenharNotas(); } });
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const dados = { titulo: form.elements.titulo.value.trim(), texto: form.elements.texto.value.trim() };
        if (!dados.titulo && !dados.texto) return form.elements.texto.focus();
        const agora = new Date().toISOString();
        if (nota) {
            notas = notas.map((n) => (n.id === nota.id ? { ...n, ...dados, atualizadaEm: agora } : n));
        } else {
            notas.push({ id: novoId(), prancha, ancora, trecho, ...dados, criadaEm: agora, atualizadaEm: agora });
        }
        salvarNotas();
        form.remove();
        desenharNotas();
    });
}

function apagarNota(id) {
    const nota = notas.find((n) => n.id === id);
    if (!nota || !confirm(`Apagar a nota "${nota.titulo || 'sem título'}"?`)) return;
    notas = notas.filter((n) => n.id !== id);
    salvarNotas();
    desenharNotas();
}

// ---------- Seleção de texto: anotar ----------

const balao = $('#balao-selecao');
let selecao = null;

function lerSelecao() {
    const sel = window.getSelection();
    const texto = sel?.toString().replace(/\s+/g, ' ').trim();
    if (!sel || sel.isCollapsed || !texto) return null;
    const no = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
    const prancha = no?.closest('.prancha');
    if (!prancha || no.closest('.formulario-nota, .marca, .acoes, .carimbo')) return null;
    return {
        prancha: prancha.id,
        ancora: no.closest('[data-ancora]')?.dataset.ancora || null,
        trecho: texto.slice(0, 1200),
        retangulo: sel.getRangeAt(0).getBoundingClientRect(),
    };
}

document.addEventListener('mouseup', (e) => {
    if (balao.contains(e.target)) return;
    setTimeout(() => {
        selecao = lerSelecao();
        if (!selecao) return balao.classList.remove('visivel');
        balao.style.top = `${window.scrollY + selecao.retangulo.top - 46}px`;
        balao.style.left = `${Math.max(8, window.scrollX + selecao.retangulo.left)}px`;
        balao.classList.add('visivel');
    }, 0);
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') balao.classList.remove('visivel'); });

$('#anotar-selecao').addEventListener('click', () => {
    if (!selecao) return;
    balao.classList.remove('visivel');
    abrirFormulario({ prancha: selecao.prancha, ancora: selecao.ancora, trecho: selecao.trecho });
    window.getSelection().removeAllRanges();
});

// ---------- Caderno, exportação e backup ----------

function notasPorPrancha() {
    return pranchas.map((p) => ({ prancha: p, notas: notas.filter((n) => n.prancha === p.id) })).filter((g) => g.notas.length);
}

function desenharCaderno() {
    const grupos = notasPorPrancha();
    $('#caderno-corpo').innerHTML = grupos.length
        ? grupos.map(({ prancha, notas: doGrupo }) => `
            <h3><a href="#${prancha.id}" data-fechar-caderno>${escapeHtml(tituloDe(prancha.id))}</a></h3>
            <div class="marcas">${doGrupo.map(htmlMarca).join('')}</div>`).join('')
        : '<p class="vazio">Nenhuma nota ainda. Selecione um trecho de qualquer prancha e clique em "Anotar".</p>';
}

function baixar(nome, conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = Object.assign(document.createElement('a'), { href: url, download: nome });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportarNotas() {
    const linhas = ['# Notas de estudo — recomendador RotaSafra', '', `Exportado em ${quando(new Date().toISOString())}.`, ''];
    for (const { prancha, notas: doGrupo } of notasPorPrancha()) {
        linhas.push(`## ${tituloDe(prancha.id)}`, '');
        for (const n of doGrupo) {
            linhas.push(`### ${n.titulo || 'Nota sem título'}`, '');
            if (n.trecho) linhas.push(`> ${n.trecho.replace(/\n/g, '\n> ')}`, '');
            linhas.push(n.texto, '', `_${quando(n.atualizadaEm)}_`, '');
        }
    }
    baixar('notas-recomendador.md', linhas.join('\n'), 'text/markdown;charset=utf-8');
}

function exportarBackup() {
    baixar('notas-recomendador.json', JSON.stringify(notas, null, 2), 'application/json');
}

async function importarBackup(arquivo) {
    try {
        const recebidas = JSON.parse(await arquivo.text());
        if (!Array.isArray(recebidas)) throw new Error('o arquivo não é uma lista de notas');
        const ids = new Set(notas.map((n) => n.id));
        const novas = recebidas.filter((n) => n && n.id && n.prancha && !ids.has(n.id));
        notas = [...notas, ...novas];
        salvarNotas();
        desenharNotas();
        alert(`${novas.length} ${novas.length === 1 ? 'nota importada' : 'notas importadas'} (repetidas foram ignoradas).`);
    } catch (err) {
        alert(`Não consegui importar: ${err.message}`);
    }
}

$('#abrir-caderno').addEventListener('click', () => { desenharCaderno(); $('#caderno').showModal(); });
$('#fechar-caderno').addEventListener('click', () => $('#caderno').close());
$('#exportar-notas').addEventListener('click', exportarNotas);
$('#exportar-notas-caderno').addEventListener('click', exportarNotas);
$('#backup-notas').addEventListener('click', exportarBackup);
$('#importar-notas').addEventListener('click', () => $('#arquivo-backup').click());
$('#arquivo-backup').addEventListener('change', (e) => {
    if (e.target.files[0]) importarBackup(e.target.files[0]);
    e.target.value = '';
});

// ---------- Cliques delegados ----------

document.addEventListener('click', (e) => {
    const alvo = e.target.closest('button, a');
    if (!alvo) return;
    if (alvo.dataset.novaNota) abrirFormulario({ prancha: alvo.dataset.novaNota });
    else if (alvo.dataset.editar) {
        const nota = notas.find((n) => n.id === alvo.dataset.editar);
        if ($('#caderno').open) $('#caderno').close();
        if (nota) abrirFormulario({ prancha: nota.prancha, ancora: nota.ancora, nota });
    } else if (alvo.dataset.apagar) apagarNota(alvo.dataset.apagar);
    else if (alvo.hasAttribute('data-fechar-caderno')) $('#caderno').close();
});

// ---------- Início ----------

mostrarContagem();
desenharNotas();
// As notas inseridas depois do carregamento empurram o conteúdo: um link para "#p05" cairia no lugar errado.
if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'instant' });
