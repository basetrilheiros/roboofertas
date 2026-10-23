"use strict";
const params = new URLSearchParams(location.search);
history.replaceState(null, "", location.pathname);
const state = params.get("state");
const code = params.get("code");
const error = params.get("error");
if (!state || state.length > 256 || (!code && !error) || (code && code.length > 4096)) {
 document.getElementById("status").textContent = "Nenhuma autorização válida recebida. Inicie a conexão pelo painel local.";
} else {
 const fragment = new URLSearchParams();
 fragment.set("state", state);
 if (code) fragment.set("code", code);
 if (error) fragment.set("error", "denied");
 const link = document.getElementById("return");
 link.href = "https://127.0.0.1:5000/ml/return#" + fragment.toString();
 link.hidden = false;
 document.getElementById("status").textContent = "O retorno foi recebido. Continue no mesmo computador e navegador onde você iniciou a conexão.";
}
