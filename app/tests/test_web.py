"""
Testes de integração das rotas web (interface Flask).
"""
import json
from services.parser import parse_pasted_text


def test_web_dashboard_renders(client):
    """Verifica se o dashboard carrega com os cards e placeholders."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Base Trilheiros" in html
    assert "Comissões em Revisão" in html
    assert "Produtos Monitorados" in html
    assert "Ofertas do Dia" in html
    assert "Fase 2" in html


def test_web_parameters_view_and_save(client):
    """Testa renderização e envio do formulário de parâmetros."""
    # GET
    res_get = client.get("/parameters")
    assert res_get.status_code == 200
    assert "Parâmetros de Curadoria" in res_get.data.decode("utf-8")

    # POST
    res_post = client.post(
        "/parameters/save",
        data={
            "categorias_busca": "Camping, Trekking",
            "termos_busca": "barraca, fogareiro",
            "preco_min": "30.00",
            "preco_max": "900.00",
            "desconto_min_ativo": "1",
            "desconto_min_percentual": "12.5",
            "avaliacao_minima": "4.6",
            "min_avaliacoes": "25",
            "reputacao_minima": "mercado_lider_gold",
            "volume_anuncios_alvo": "350",
            "max_recomendacoes": "10",
            "peso_desconto": "0.40",
            "peso_avaliacao": "0.35",
            "peso_frete": "0.25",
            "diversidade_max_por_categoria": "3",
            "antirrepeticao_dias": "15",
            "horario_curadoria": "08:00 America/Sao_Paulo",
        },
        follow_redirects=True,
    )
    assert res_post.status_code == 200
    assert "Parâmetros de curadoria atualizados" in res_post.data.decode("utf-8")


def test_web_monitored_flow(client):
    """Testa cadastro e visualização de monitorados via web."""
    res_add = client.post(
        "/monitored/add",
        data={
            "titulo": "Canivete Tático Multiuso",
            "url": "https://produto.mercadolivre.com.br/MLB-8888-canivete",
            "categoria": "Sobrevivência",
            "preco_alvo": "85.00",
            "observacoes": "Modelo preto com presilha",
        },
        follow_redirects=True,
    )
    assert res_add.status_code == 200
    html = res_add.data.decode("utf-8")
    assert "Canivete Tático Multiuso" in html
    assert "R$ 85,00" in html


def test_web_sales_preview_and_confirm(client):
    """Testa fluxo completo de importação via texto colado no client web."""
    pasted = """
LOJA_FICTICIA_D	R$24,281 unidade	R$2,39Venda direta: 12%	EM REVISÃO
29/set#9000000000000002
Produto fictício DCategoria: Cozinha
"""
    # 1. Prévia via POST
    res_prev = client.post(
        "/sales/preview-paste",
        data={"pasted_text": pasted, "ano": "2026"},
    )
    assert res_prev.status_code == 200
    data = res_prev.get_json()
    assert data["success"] is True
    assert data["preview"]["total_registros_detectados"] == 1

    # 2. Confirmação e persistência
    res_conf = client.post(
        "/sales/confirm-import",
        data={
            "preview_data": json.dumps(data["preview"]),
            "source_info": json.dumps(data["source_info"]),
        },
        follow_redirects=True,
    )
    assert res_conf.status_code == 200
    html = res_conf.data.decode("utf-8")
    assert "Importação confirmada" in html
    assert "Produto fictício D" in html
    assert "R$ 2,39" in html


def test_web_diagnostics_and_backup(client):
    """Testa página de diagnóstico e disparo de backup manual."""
    res = client.get("/diagnostics")
    assert res.status_code == 200
    assert "Diagnóstico do Sistema" in res.data.decode("utf-8")

    # Acionar backup
    res_bkp = client.post("/diagnostics/backup", follow_redirects=True)
    assert res_bkp.status_code == 200
    assert "Backup gerado com sucesso" in res_bkp.data.decode("utf-8")

