"use strict";
const params = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, "", location.pathname);
const form = document.getElementById("complete");
const state = params.get("state");
if (!state || state.length > 256 || (!params.get("code") && !params.get("error"))) {
 document.getElementById("message").textContent = "Retorno inválido. Inicie novamente pelo painel Mercado Livre.";
} else {
 for (const key of ["code", "state", "error"]) form.elements[key].value = params.get(key) || "";
 document.getElementById("message").textContent = "Confirme para concluir a conexão iniciada no seu painel. Nenhuma busca será feita automaticamente.";
 form.hidden = false;
}
