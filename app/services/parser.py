"""
Módulo de parsing especializado para relatórios de afiliados do Mercado Livre.
Suporta leitura de planilhas XLSX e colagem direta de texto.
Tolerante a células com erro (#VALUE!), linhas em branco e formatos não tabulares.
"""
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import re
from typing import Any, Dict, List, Optional, Tuple
import unicodedata

import openpyxl

MONTHS_PT = {
    "jan": "01",
    "fev": "02",
    "mar": "03",
    "abr": "04",
    "mai": "05",
    "jun": "06",
    "jul": "07",
    "ago": "08",
    "set": "09",
    "out": "10",
    "nov": "11",
    "dez": "12",
}

ERROR_VALUES = {"#VALUE!", "#VALOR!", "#N/D", "#REF!", "#DIV/0!", "#NAME?", "#NULO!", "NAN", "NONE", "NULL"}


def normalize_text(text: Optional[str]) -> str:
    """Normaliza strings removendo acentos e caracteres especiais para comparações."""
    if not text:
        return ""
    text_clean = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII")
    return re.sub(r"[^a-z0-9]+", "", text_clean.lower())


def parse_date_transaction(text: str, confirmed_year: int) -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    """
    Interpreta strings como '29/set#9000000000000002'.
    Retorna: (data_iso 'YYYY-MM-DD', data_texto '29/set', transacao '9000000000000002', warnings).
    """
    warnings = []
    text_clean = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d{1,2})/([a-zA-ZçÇáéíóúÁÉÍÓÚ]{3,4})#(\d+)", text_clean)
    if not match:
        return None, None, None, ["Data/Transação não identificada no padrão 'DD/mês#transação'."]

    day_str = match.group(1).zfill(2)
    month_name = match.group(2).lower()
    transacao = match.group(3)
    data_texto = f"{int(day_str)}/{month_name}"

    month_num = MONTHS_PT.get(month_name[:3])
    if not month_num:
        warnings.append(f"Mês '{month_name}' não mapeado.")
        data_iso = f"{confirmed_year}-01-{day_str}"
    else:
        data_iso = f"{confirmed_year}-{month_num}-{day_str}"

    return data_iso, data_texto, transacao, warnings


def parse_title_category(text: str) -> Tuple[str, str, Optional[str]]:
    """
    Interpreta títulos como:
    'Produto fictícioCategoria: Cozinha'
    Retorna: (descricao, categoria, item_id).
    """
    text_clean = text.replace("\xa0", " ").strip()
    # Identificar código do anúncio se presente (ex: MLB123456789)
    item_match = re.search(r"\b(MLB[-\s]?\d+)\b", text_clean, re.IGNORECASE)
    item_id = item_match.group(1).replace("-", "").replace(" ", "").upper() if item_match else None

    # Separar Categoria:
    cat_match = re.search(r"\s*Categoria:\s*(.+)$", text_clean, re.IGNORECASE)
    if cat_match:
        categoria = cat_match.group(1).strip()
        descricao = text_clean[: cat_match.start()].strip()
    else:
        categoria = "Geral"
        descricao = text_clean

    return descricao, categoria, item_id


def parse_price_quantity(text: str) -> Tuple[int, Decimal, int, List[str]]:
    """
    Interpreta preços como 'R$24,281 unidade', 'R$751 unidade', 'R$580,531 unidade'.
    Retorna: (preco_centavos, preco_decimal, quantidade, warnings).
    """
    warnings = []
    text_clean = text.replace("\xa0", " ").strip()

    # Padrão com vírgula decimal (ex: R$24,281 unidade)
    m1 = re.search(r"R\$\s*([\d\.]+),(\d{2})\s*(\d*)\s*(?:unidade[s]?|un\b)?", text_clean, re.IGNORECASE)
    if m1:
        int_part = m1.group(1).replace(".", "")
        dec_part = m1.group(2)
        qty_str = m1.group(3)
        preco_dec = Decimal(f"{int_part}.{dec_part}")
        qty = int(qty_str) if qty_str else 1
        return int(preco_dec * 100), preco_dec, qty, warnings

    # Padrão sem vírgula decimal (ex: R$751 unidade -> R$ 75 e 1 unidade)
    m2 = re.search(r"R\$\s*(\d+?)(\d)\s*(?:unidade[s]?|un\b)", text_clean, re.IGNORECASE)
    if m2:
        val_str = m2.group(1)
        qty_str = m2.group(2)
        preco_dec = Decimal(val_str)
        warnings.append(f"Preço inferido sem vírgula decimal: R$ {val_str},00 ({qty_str} unid.)")
        return int(preco_dec * 100), preco_dec, int(qty_str), warnings

    # Fallback genérico para número decimal
    m3 = re.search(r"R\$\s*([\d\.,]+)", text_clean, re.IGNORECASE)
    if m3:
        num_str = m3.group(1).replace(".", "").replace(",", ".")
        preco_dec = Decimal(num_str)
        return int(preco_dec * 100), preco_dec, 1, warnings

    warnings.append(f"Preço não identificado na string: '{text}'")
    return 0, Decimal("0.00"), 1, warnings


def parse_commission_rate_type(text: str) -> Tuple[int, Decimal, str, float, List[str]]:
    """
    Interpreta 'R$2,39Venda direta: 12%' ou 'R$1,52Venda indireta: 2.5%'.
    Retorna: (comissao_centavos, comissao_decimal, tipo_venda, taxa_percentual, warnings).
    """
    warnings = []
    text_clean = text.replace("\xa0", " ").strip()

    m = re.search(
        r"R\$\s*([\d\.]+),(\d{2})\s*(Venda\s+(?:direta|indireta))(?:\s*:\s*([\d\.,]+)%)?",
        text_clean,
        re.IGNORECASE,
    )
    if m:
        int_part = m.group(1).replace(".", "")
        dec_part = m.group(2)
        comm_dec = Decimal(f"{int_part}.{dec_part}")
        tipo_str = m.group(3).lower()
        tipo_venda = "indireta" if "indireta" in tipo_str else "direta"
        taxa_str = m.group(4)
        taxa = float(taxa_str.replace(",", ".")) if taxa_str else 0.0
        return int(comm_dec * 100), comm_dec, tipo_venda, taxa, warnings

    # Fallback simples se vier apenas valor
    m_simple = re.search(r"R\$\s*([\d\.]+),(\d{2})", text_clean, re.IGNORECASE)
    if m_simple:
        comm_dec = Decimal(f"{m_simple.group(1).replace('.', '')}.{m_simple.group(2)}")
        warnings.append(f"Tipo de venda não explicitado em '{text}'; adotado 'direta'.")
        return int(comm_dec * 100), comm_dec, "direta", 0.0, warnings

    warnings.append(f"Comissão não identificada na string: '{text}'")
    return 0, Decimal("0.00"), "direta", 0.0, warnings


def parse_status(text: str) -> str:
    """Higieniza o status para os estados padrão da Fase 1."""
    t = text.strip().upper()
    if "REVIS" in t:
        return "EM REVISÃO"
    if "APROV" in t:
        return "APROVADA"
    if "PAG" in t:
        return "PAGA"
    if "CANCEL" in t:
        return "CANCELADA"
    return "EM REVISÃO"


def generate_dedup_key(transacao: str, item_id: Optional[str], descricao: str, loja: str) -> str:
    """
    Gera chave de deduplicação determinística.
    Prioriza transação + item_id. Caso ausente, utiliza transação + slug(produto) + slug(loja).
    """
    if item_id:
        seed = f"{transacao}:{item_id.strip().upper()}"
    else:
        seed = f"{transacao}:{normalize_text(descricao)[:45]}:{normalize_text(loja)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def parse_raw_rows(
    raw_rows: List[List[str]],
    confirmed_year: int,
) -> Dict[str, Any]:
    """
    Agrupa e processa linhas brutas em blocos de vendas.
    Descarta células e linhas residuais como #VALUE!.
    """
    records: List[Dict[str, Any]] = []
    discarded_cells: int = 0
    total_lines = len(raw_rows)

    # Limpeza e remoção de linhas vazias
    cleaned_rows: List[List[str]] = []
    for row in raw_rows:
        row_vals = []
        for cell in row:
            c = str(cell).strip() if cell is not None else ""
            if c.upper() in ERROR_VALUES:
                discarded_cells += 1
                row_vals.append("")
            else:
                row_vals.append(c)
        if any(row_vals):
            cleaned_rows.append(row_vals)

    # Agrupador de blocos:
    # Um bloco comercial tem normalmente 3 linhas:
    # 1. Linha principal: Loja, Preço/Qtd, Comissão/Tipo/Taxa, Status
    # 2. Linha de Data e Transação: DD/mês#transação
    # 3. Linha de Descrição e Categoria: Título Categoria: Nome
    idx = 0
    while idx < len(cleaned_rows):
        row = cleaned_rows[idx]
        non_empty = [c for c in row if c]

        # Verificar se esta linha contém 'R$' e status (Linha Principal)
        is_main_row = any("R$" in c for c in non_empty) and any(
            any(st in c.upper() for st in ["REVIS", "APROV", "PAG", "CANCEL"]) for c in non_empty
        )

        if is_main_row:
            # Temos a linha principal. Coletar os próximos elementos do bloco
            block_lines = [row]
            idx += 1
            # Coletar até 2 linhas seguintes se não forem outra linha principal
            while idx < len(cleaned_rows) and len(block_lines) < 3:
                next_row = cleaned_rows[idx]
                next_non_empty = [c for c in next_row if c]
                is_next_main = any("R$" in c for c in next_non_empty) and any(
                    any(st in c.upper() for st in ["REVIS", "APROV", "PAG", "CANCEL"]) for c in next_non_empty
                )
                if is_next_main:
                    break
                block_lines.append(next_row)
                idx += 1

            # Processar bloco identificado
            record = _build_record_from_block(block_lines, confirmed_year)
            if record:
                records.append(record)
        else:
            # Linha fora do padrão esperado
            idx += 1

    # Totais calculados na prévia
    comissao_revisao_centavos = sum(r["comissao_centavos"] for r in records if r["status"] == "EM REVISÃO")
    comissao_aprovada_centavos = sum(r["comissao_centavos"] for r in records if r["status"] == "APROVADA")
    comissao_paga_centavos = sum(r["comissao_centavos"] for r in records if r["status"] == "PAGA")
    comissao_cancelada_centavos = sum(r["comissao_centavos"] for r in records if r["status"] == "CANCELADA")

    return {
        "total_linhas_lidas": total_lines,
        "total_registros_detectados": len(records),
        "descartadas_invalidas": discarded_cells,
        "ano_confirmado": confirmed_year,
        "comissao_revisao_centavos": comissao_revisao_centavos,
        "comissao_revisao_formatada": f"R$ {comissao_revisao_centavos / 100:.2f}".replace(".", ","),
        "comissao_aprovada_centavos": comissao_aprovada_centavos,
        "comissao_aprovada_formatada": f"R$ {comissao_aprovada_centavos / 100:.2f}".replace(".", ","),
        "comissao_paga_centavos": comissao_paga_centavos,
        "comissao_paga_formatada": f"R$ {comissao_paga_centavos / 100:.2f}".replace(".", ","),
        "comissao_cancelada_centavos": comissao_cancelada_centavos,
        "registros": records,
    }


def _build_record_from_block(block_lines: List[List[str]], confirmed_year: int) -> Optional[Dict[str, Any]]:
    """Monta o registro normalizado a partir das linhas do bloco."""
    main_row = block_lines[0]
    main_non_empty = [c for c in main_row if c]

    # Identificar campos na linha principal
    loja = ""
    preco_raw = ""
    comm_raw = ""
    status_raw = "EM REVISÃO"

    for cell in main_non_empty:
        if any(st in cell.upper() for st in ["REVIS", "APROV", "PAG", "CANCEL"]):
            status_raw = cell
        elif "VENDA" in cell.upper() and "R$" in cell:
            comm_raw = cell
        elif "R$" in cell and not comm_raw:
            preco_raw = cell
        elif not loja:
            loja = cell

    status = parse_status(status_raw)
    preco_centavos, preco_dec, quantidade, p_warn = parse_price_quantity(preco_raw)
    comm_centavos, comm_dec, tipo_venda, taxa, c_warn = parse_commission_rate_type(comm_raw)

    # Linhas secundárias (Data/Transação e Título/Categoria)
    data_iso = f"{confirmed_year}-01-01"
    data_texto = ""
    transacao = ""
    descricao = ""
    categoria = "Geral"
    item_id = None
    all_warnings = p_warn + c_warn

    for extra_row in block_lines[1:]:
        text_joined = " ".join([c for c in extra_row if c])
        if "#" in text_joined and re.search(r"\d{1,2}/[a-zA-Z]{3,4}#\d+", text_joined):
            d_iso, d_txt, tr, dt_warn = parse_date_transaction(text_joined, confirmed_year)
            if d_iso:
                data_iso = d_iso
                data_texto = d_txt or ""
                transacao = tr or ""
            all_warnings.extend(dt_warn)
        elif text_joined:
            desc, cat, it_id = parse_title_category(text_joined)
            descricao = desc
            categoria = cat
            item_id = it_id

    if not transacao:
        all_warnings.append("Transação ausente no bloco.")
        transacao = "SEM_TRANSACAO"

    if not descricao:
        descricao = f"Venda {transacao} - {loja}"

    dedup_key = generate_dedup_key(transacao, item_id, descricao, loja)

    return {
        "dedup_key": dedup_key,
        "transacao": transacao,
        "item_id": item_id,
        "data_venda": data_iso,
        "data_texto": data_texto,
        "ano_confirmado": confirmed_year,
        "descricao": descricao,
        "descricao_normalizada": normalize_text(descricao),
        "categoria": categoria,
        "loja": loja,
        "preco_unitario_centavos": preco_centavos,
        "preco_formatado": f"R$ {preco_centavos / 100:.2f}".replace(".", ","),
        "quantidade": quantidade,
        "comissao_centavos": comm_centavos,
        "comissao_formatada": f"R$ {comm_centavos / 100:.2f}".replace(".", ","),
        "taxa_percentual": taxa,
        "tipo_venda": tipo_venda,
        "status": status,
        "raw_block": "\n".join([" | ".join(row) for row in block_lines]),
        "warnings": all_warnings,
    }


def parse_xlsx(file_source: Any, confirmed_year: int) -> Dict[str, Any]:
    """Lê arquivo XLSX (caminho ou stream de bytes) e executa o parser."""
    wb = openpyxl.load_workbook(file_source, data_only=True)
    sheet = wb.active
    raw_rows: List[List[str]] = []
    for row in sheet.iter_rows(values_only=True):
        raw_rows.append([str(c).strip() if c is not None else "" for c in row])
    return parse_raw_rows(raw_rows, confirmed_year)


def parse_pasted_text(text: str, confirmed_year: int) -> Dict[str, Any]:
    """
    Lê texto colado diretamente pelo usuário.
    Detecta tabulações (colunas) ou quebras de linhas sucessivas.
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    raw_rows: List[List[str]] = []

    for line in lines:
        if "\t" in line:
            raw_rows.append([col.strip() for col in line.split("\t")])
        else:
            # Linha única com colunas separadas por múltiplos espaços ou pipe
            if " | " in line:
                raw_rows.append([col.strip() for col in line.split(" | ")])
            else:
                raw_rows.append([line])

    return parse_raw_rows(raw_rows, confirmed_year)
