document.querySelectorAll('.affiliate-link-form').forEach(form => {
    const status = form.querySelector('.affiliate-status');
    const saved = form.querySelector('.affiliate-saved');
    const copy = form.querySelector('.affiliate-copy');
    async function copyText(value) {
        try { await navigator.clipboard.writeText(value); status.textContent = 'Copiado.'; }
        catch (_) { status.textContent = 'Não foi possível copiar. Selecione o endereço e copie manualmente.'; }
    }
    copy.addEventListener('click', () => copyText(saved.href));
    form.querySelector('.affiliate-copy-source').addEventListener('click', event => copyText(event.target.dataset.url));
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        status.textContent = 'Salvando…';
        try {
            const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', redirect: 'error'});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Não foi possível salvar.');
            saved.href = data.url;
            saved.hidden = false;
            copy.hidden = false;
            form.querySelector('summary').textContent = 'Editar link';
            form.querySelector('details').open = false;
            status.textContent = 'Link salvo para BaseTrilheiros / whatsapp.';
        } catch (error) { status.textContent = error.message || 'Falha ao salvar. Tente novamente.'; }
        finally { button.disabled = false; }
    });
});
