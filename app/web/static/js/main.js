/**
 * BASE TRILHEIROS — JavaScript Local (Fase 1)
 * Gerenciamento de abas, requisições assíncronas de prévia e confirmações.
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Gerenciamento de Abas (Upload vs Colar)
    const tabButtons = document.querySelectorAll(".tab-btn");
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            
            btn.classList.add("active");
            const activeContent = document.getElementById(target);
            if (activeContent) activeContent.classList.add("active");
        });
    });

    // 2. Prévia via Upload de XLSX
    const formUpload = document.getElementById("form-upload-xlsx");
    if (formUpload) {
        formUpload.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(formUpload);
            const anoInput = formUpload.querySelector("input[name='ano']");
            if (!anoInput.value) {
                alert("Por favor, informe e confirme o Ano de Referência da planilha.");
                anoInput.focus();
                return;
            }
            await processPreview("/sales/preview-xlsx", formData);
        });
    }

    // 3. Prévia via Colar Texto
    const formPaste = document.getElementById("form-paste-text");
    if (formPaste) {
        formPaste.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(formPaste);
            const anoInput = formPaste.querySelector("input[name='ano']");
            const pasteText = formPaste.querySelector("textarea[name='pasted_text']");
            
            if (!anoInput.value) {
                alert("Por favor, informe e confirme o Ano de Referência.");
                anoInput.focus();
                return;
            }
            if (!pasteText.value.trim()) {
                alert("Por favor, cole o texto da tabela antes de prosseguir.");
                pasteText.focus();
                return;
            }
            await processPreview("/sales/preview-paste", formData);
        });
    }
});

// Processa o retorno da rota de prévia e renderiza a tabela de conferência
async function processPreview(url, formData) {
    const previewContainer = document.getElementById("preview-container");
    const previewContent = document.getElementById("preview-content");
    const btnSubmit = document.querySelector("button[type='submit']:focus");

    if (previewContainer) {
        previewContainer.style.display = "block";
        previewContent.innerHTML = "<p style='padding: 1.5rem; color: #64748b;'>Analisando estrutura de blocos e validando registros...</p>";
        previewContainer.scrollIntoView({ behavior: "smooth" });
    }

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {"X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || ""},
            body: formData,
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            previewContent.innerHTML = `<div class="alert alert-error">Erro ao processar arquivo: ${escapeHtml(data.error || "Formato não reconhecido")}</div>`;
            return;
        }

        renderPreviewTable(data);
    } catch (err) {
        previewContent.innerHTML = `<div class="alert alert-error">Falha na comunicação local: ${escapeHtml(err.message)}</div>`;
    }
}

// Renderiza a tabela de prévia normalizada
function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function renderPreviewTable(data) {
    const previewContent = document.getElementById("preview-content");
    const previewDataInput = document.getElementById("confirmed-preview-data");
    const sourceInfoInput = document.getElementById("confirmed-source-info");

    // Salvar JSON serializado no form oculto de confirmação
    if (previewDataInput) previewDataInput.value = JSON.stringify(data.preview);
    if (sourceInfoInput) sourceInfoInput.value = JSON.stringify(data.source_info);

    const prev = data.preview;
    const resumo = prev.resumo_acoes || { novos: prev.registros.length, atualizacoes: 0, duplicados: 0 };

    let html = `
        <div style="margin-bottom: 1rem; display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; justify-content: space-between;">
            <div>
                <h4 style="font-size: 1.1rem; color: var(--primary);">Prévia Normalizada (${escapeHtml(prev.total_registros_detectados)} Vendas Identificadas)</h4>
                <p style="font-size: 0.85rem; color: #64748b;">
                    Ano confirmado: <strong>${escapeHtml(prev.ano_confirmado)}</strong> | Linhas lidas: <strong>${escapeHtml(prev.total_linhas_lidas)}</strong> | 
                    Células com erro (#VALUE! descartadas): <strong>${escapeHtml(prev.descartadas_invalidas)}</strong>
                </p>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <span class="badge badge-revisao">Em Revisão: ${escapeHtml(prev.comissao_revisao_formatada)}</span>
                <span class="badge badge-direta">Novos: ${resumo.novos}</span>
                ${resumo.atualizacoes > 0 ? `<span class="badge badge-aprovada">Atualizações: ${resumo.atualizacoes}</span>` : ""}
                ${resumo.duplicados > 0 ? `<span class="badge badge-indireta">Duplicados: ${resumo.duplicados}</span>` : ""}
            </div>
        </div>

        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Ação</th>
                        <th>Data</th>
                        <th>Transação</th>
                        <th>Loja</th>
                        <th>Produto / Categoria</th>
                        <th>Preço</th>
                        <th>Comissão</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
    `;

    prev.registros.forEach((reg, i) => {
        const actionBadge = reg.action === "NOVO" 
            ? `<span class="badge badge-aprovada">Novo</span>` 
            : reg.action === "ATUALIZAR_STATUS" 
                ? `<span class="badge badge-paga">Atualizar Status</span>` 
                : `<span class="badge badge-indireta">Ignorar (Duplicado)</span>`;

        html += `
            <tr>
                <td>${actionBadge}</td>
                <td><strong>${escapeHtml(reg.data_venda)}</strong><br><small style="color:#64748b">${escapeHtml(reg.data_texto)}</small></td>
                <td><code>#${escapeHtml(reg.transacao)}</code></td>
                <td>${escapeHtml(reg.loja || "-")}</td>
                <td>
                    <strong>${escapeHtml(reg.descricao)}</strong><br>
                    <small style="color:#64748b">Categoria: ${escapeHtml(reg.categoria)}</small>
                </td>
                <td>${escapeHtml(reg.preco_formatado)} (${escapeHtml(reg.quantidade)} un)</td>
                <td>
                    <strong>${escapeHtml(reg.comissao_formatada)}</strong><br>
                    <small style="color:#64748b">${reg.tipo_venda === 'direta' ? 'Direta' : 'Indireta'} (${escapeHtml(reg.taxa_percentual)}%)</small>
                </td>
                <td><span class="badge badge-revisao">${escapeHtml(reg.status)}</span></td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    previewContent.innerHTML = html;
    document.getElementById("btn-confirm-import").style.display = "inline-flex";
}
