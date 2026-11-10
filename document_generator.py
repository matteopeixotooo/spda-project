#!/usr/bin/env python3
"""Gerador de Memorial Descritivo e de Cálculo de SPDA em formato Word (.docx).

Integra os módulos:
- `risk_engine.py` (ABNT NBR 5419-2: Gerenciamento de Risco);
- `physical_design.py` (ABNT NBR 5419-3: Dimensionamento Físico Executivo);
e incorpora diretrizes de MPS/DPS da ABNT NBR 5419-4, produzindo um documento
formal de engenharia pronto para emissão e vinculação de ART/TRT.
"""

from __future__ import annotations

import argparse
from datetime import date
import io
from pathlib import Path
import subprocess
import sys
from typing import Any


def verificar_ou_instalar_python_docx() -> None:
    """Verifica a disponibilidade da biblioteca `python-docx`, instalando-a se ausente."""
    try:
        import docx  # noqa: F401
    except ImportError:
        comandos_tentativa = [
            [sys.executable, "-m", "pip", "install", "python-docx"],
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--break-system-packages",
                "python-docx",
            ],
        ]
        instalado = False
        for cmd in comandos_tentativa:
            resultado = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if resultado.returncode == 0:
                instalado = True
                break
        if not instalado:
            raise RuntimeError(
                "Não foi possível instalar automaticamente 'python-docx'. "
                "Instale manualmente com: pip install python-docx"
            )


verificar_ou_instalar_python_docx()

from docx import Document  # noqa: E402
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement, parse_xml  # noqa: E402
from docx.oxml.ns import nsdecls, qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

from physical_design import SpdaPhysicalDesign, avaliar_metodos_captacao  # noqa: E402
from risk_engine import (  # noqa: E402
    RISCO_TOLERAVEL_R1,
    ResultadoR1,
    calcular_risco_r1,
    determinar_nivel_protecao,
)

# Paleta sobria para documento técnico de engenharia
COR_PRIMARIA = RGBColor(0x1B, 0x36, 0x5D)  # Azul marinho técnico
COR_SECUNDARIA = RGBColor(0x2C, 0x52, 0x82)
COR_TEXTO = RGBColor(0x1F, 0x29, 0x37)
COR_CINZA_SUTIL = RGBColor(0x5A, 0x65, 0x77)
HEX_CABECALHO_TABELA = "1B365D"
HEX_LINHA_ZEBRA = "F3F6FA"
HEX_ALERTA_FUNDO = "FFF8E7"
HEX_BORDA_TABELA = "CBD5E1"

# Corrente impulsiva mínima por polo (Iimp 10/350 us) de referência p/ DPS Classe I no QGBT
DPS_IIMP_POR_NIVEL: dict[str, str] = {
    "I": "25 kA por polo (100 kA total em sistema TT/TN-S 3F+N) - onda 10/350 µs",
    "II": "18,75 kA a 25 kA por polo (75 kA a 100 kA total) - onda 10/350 µs",
    "III": "12,5 kA por polo (50 kA total em sistema 3F+N) - onda 10/350 µs",
    "IV": "12,5 kA por polo (50 kA total em sistema 3F+N) - onda 10/350 µs",
}


def _sombrear_celula(celula: Any, cor_hex: str) -> None:
    """Aplica preenchimento de fundo (shading) em uma célula de tabela do Word."""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{cor_hex}"/>')
    celula._tc.get_or_add_tcPr().append(shading)


def _definir_margens_celula(
    celula: Any,
    top: int = 100,
    bottom: int = 100,
    left: int = 140,
    right: int = 140,
) -> None:
    """Define espaçamento interno (padding em dxa/twips) de uma célula do Word."""
    tc_pr = celula._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for nome_borda, valor in (
        ("top", top),
        ("bottom", bottom),
        ("left", left),
        ("right", right),
    ):
        no = OxmlElement(f"w:{nome_borda}")
        no.set(qn("w:w"), str(valor))
        no.set(qn("w:type"), "dxa")
        tc_mar.append(no)
    tc_pr.append(tc_mar)


def _aplicar_bordas_tabela(tabela: Any, cor_hex: str = HEX_BORDA_TABELA) -> None:
    """Aplica bordas finas e uniformes em toda a tabela."""
    tbl_pr = tabela._tbl.tblPr
    bordas = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="6" w:space="0" w:color="{cor_hex}"/>'
        f'  <w:bottom w:val="single" w:sz="8" w:space="0" w:color="{HEX_CABECALHO_TABELA}"/>'
        f'  <w:left w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{cor_hex}"/>'
        f'  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="{cor_hex}"/>'
        f"</w:tblBorders>"
    )
    tbl_pr.append(bordas)


def _configurar_estilos_documento(doc: Document, titulo_curto: str) -> None:
    """Configura página A4, margens técnicas ABNT, estilos base, cabeçalho e rodapé."""
    secao = doc.sections[0]
    secao.page_width = Cm(21.0)
    secao.page_height = Cm(29.7)
    secao.top_margin = Cm(2.5)
    secao.bottom_margin = Cm(2.0)
    secao.left_margin = Cm(2.5)
    secao.right_margin = Cm(2.0)
    secao.different_first_page_header_footer = True

    estilo_normal = doc.styles["Normal"]
    estilo_normal.font.name = "Calibri"
    estilo_normal.font.size = Pt(11)
    estilo_normal.font.color.rgb = COR_TEXTO
    estilo_normal.paragraph_format.line_spacing = 1.15
    estilo_normal.paragraph_format.space_after = Pt(6)

    # Cabeçalho e rodapé para as páginas internas
    cabecalho = secao.header
    p_cab = cabecalho.paragraphs[0]
    p_cab.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_cab = p_cab.add_run(titulo_curto)
    r_cab.font.name = "Calibri"
    r_cab.font.size = Pt(8.5)
    r_cab.font.color.rgb = COR_CINZA_SUTIL

    rodape = secao.footer
    p_rod = rodape.paragraphs[0]
    p_rod.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_rod = p_rod.add_run(
        "Memorial Descritivo e de Cálculo de SPDA — ABNT NBR 5419:2015 (Partes 1 a 4)"
    )
    r_rod.font.name = "Calibri"
    r_rod.font.size = Pt(8.5)
    r_rod.font.color.rgb = COR_CINZA_SUTIL


def _adicionar_titulo_secao(doc: Document, numero: int, titulo: str) -> None:
    """Adiciona título numerado de seção com barra inferior estilizada."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True

    run = p.add_run(f"{numero}. {titulo.upper()}")
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = Pt(13)
    run.font.color.rgb = COR_PRIMARIA

    p_bdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:bottom w:val="single" w:sz="10" w:space="3" w:color="{HEX_CABECALHO_TABELA}"/>'
        f"</w:pBdr>"
    )
    p._p.get_or_add_pPr().append(p_bdr)


def _adicionar_subtitulo(doc: Document, texto: str) -> None:
    """Adiciona subtítulo técnico dentro de uma seção."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(texto)
    r.bold = True
    r.font.name = "Calibri"
    r.font.size = Pt(11)
    r.font.color.rgb = COR_SECUNDARIA


def _adicionar_paragrafo_justificado(doc: Document, texto: str, negrito_prefixo: str = "") -> None:
    """Adiciona parágrafo de corpo de texto justificado."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if negrito_prefixo:
        r_pref = p.add_run(negrito_prefixo)
        r_pref.bold = True
    p.add_run(texto)


def _adicionar_item_lista(doc: Document, prefixo_negrito: str, texto: str) -> None:
    """Adiciona item com marcador técnico e prefixo em destaque."""
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(3)
    if prefixo_negrito:
        r_pref = p.add_run(prefixo_negrito)
        r_pref.bold = True
    p.add_run(texto)


def _adicionar_caixa_destaque(doc: Document, titulo: str, texto: str) -> None:
    """Adiciona quadro técnico sombreado para alertas normativos (ex.: descargas laterais)."""
    tabela = doc.add_table(rows=1, cols=1)
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    celula = tabela.cell(0, 0)
    _sombrear_celula(celula, HEX_ALERTA_FUNDO)
    _definir_margens_celula(celula, top=140, bottom=140, left=180, right=180)

    bordas = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="D97706"/>'
        f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="FCD34D"/>'
        f'  <w:right w:val="single" w:sz="4" w:space="0" w:color="FCD34D"/>'
        f'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="FCD34D"/>'
        f"</w:tcBorders>"
    )
    celula._tc.get_or_add_tcPr().append(bordas)

    p = celula.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(2)
    r_tit = p.add_run(f"{titulo}\n")
    r_tit.bold = True
    r_tit.font.color.rgb = RGBColor(0x92, 0x40, 0x0E)
    r_txt = p.add_run(texto)
    r_txt.font.size = Pt(10)
    doc.add_paragraph()


def _adicionar_tabela_estilizada(
    doc: Document,
    cabecalhos: list[str],
    linhas: list[list[str]],
    larguras_cm: list[float] | None = None,
    destacar_ultima_linha: bool = False,
) -> None:
    """Cria tabela formatada no padrão corporativo de engenharia."""
    tabela = doc.add_table(rows=1 + len(linhas), cols=len(cabecalhos))
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabela.autofit = False
    _aplicar_bordas_tabela(tabela)

    # Cabeçalho
    linha_cab = tabela.rows[0]
    for idx, texto_cab in enumerate(cabecalhos):
        cel = linha_cab.cells[idx]
        if larguras_cm and idx < len(larguras_cm):
            cel.width = Cm(larguras_cm[idx])
        cel.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _sombrear_celula(cel, HEX_CABECALHO_TABELA)
        _definir_margens_celula(cel, top=110, bottom=110, left=130, right=130)
        p = cel.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT if idx == 0 else WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(texto_cab)
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Linhas de dados
    for r_idx, valores in enumerate(linhas):
        row = tabela.rows[r_idx + 1]
        eh_ultima = destacar_ultima_linha and (r_idx == len(linhas) - 1)
        cor_fundo = "E2E8F0" if eh_ultima else (HEX_LINHA_ZEBRA if r_idx % 2 == 1 else "")

        for c_idx, valor in enumerate(valores):
            cel = row.cells[c_idx]
            if larguras_cm and c_idx < len(larguras_cm):
                cel.width = Cm(larguras_cm[c_idx])
            cel.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if cor_fundo:
                _sombrear_celula(cel, cor_fundo)
            _definir_margens_celula(cel, top=85, bottom=85, left=130, right=130)
            p = cel.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if c_idx == 0 else WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(valor)
            r.font.size = Pt(9.5)
            if eh_ultima or c_idx == 0:
                r.bold = eh_ultima


def _normalizar_entradas(
    dados_gerais: dict[str, Any],
    resultado_risco: dict[str, Any] | ResultadoR1,
    diretrizes_fisicas: SpdaPhysicalDesign | dict[str, Any],
) -> tuple[dict[str, Any], ResultadoR1, dict[str, Any], dict[str, Any]]:
    """Uniformiza os objetos recebidos do `risk_engine` e do `physical_design`."""
    if isinstance(resultado_risco, ResultadoR1):
        res_r1 = resultado_risco
        rt_usado = float(dados_gerais.get("RT", RISCO_TOLERAVEL_R1))
        decisao = determinar_nivel_protecao(res_r1, RT=rt_usado)
    elif isinstance(resultado_risco, dict):
        if "resultado_r1" in resultado_risco and isinstance(
            resultado_risco["resultado_r1"], ResultadoR1
        ):
            res_r1 = resultado_risco["resultado_r1"]
            decisao = resultado_risco.get("decisao") or determinar_nivel_protecao(res_r1)
        else:
            raise ValueError(
                "`resultado_risco` como dicionário deve conter a chave 'resultado_r1' (ResultadoR1)."
            )
    else:
        raise TypeError("`resultado_risco` deve ser `ResultadoR1` ou um dicionário compatível.")

    if isinstance(diretrizes_fisicas, SpdaPhysicalDesign):
        fisico = {
            "nivel_protecao": diretrizes_fisicas.nivel_protecao,
            "L": diretrizes_fisicas.L,
            "W": diretrizes_fisicas.W,
            "H": diretrizes_fisicas.H,
            "h_caixa_dagua": diretrizes_fisicas.h_caixa_dagua,
            "h_total": diretrizes_fisicas.h_total,
            "perimetro": diretrizes_fisicas.perimetro,
            "usa_descidas_naturais": diretrizes_fisicas.usa_descidas_naturais,
            "avaliacao_captacao": diretrizes_fisicas.avaliar_captacao(),
            "captacao": diretrizes_fisicas.dimensionar_captacao(),
            "descidas": diretrizes_fisicas.dimensionar_descidas(),
            "lateral": diretrizes_fisicas.dimensionar_protecao_lateral_e_aneis(),
            "aterramento": diretrizes_fisicas.dimensionar_aterramento(),
        }
    elif isinstance(diretrizes_fisicas, dict):
        fisico = dict(diretrizes_fisicas)
        if "avaliacao_captacao" not in fisico:
            fisico["avaliacao_captacao"] = avaliar_metodos_captacao(
                L=float(fisico["L"]),
                W=float(fisico["W"]),
                H=float(fisico["H"]),
                nivel_protecao=str(fisico["nivel_protecao"]),
            )
    else:
        raise TypeError(
            "`diretrizes_fisicas` deve ser uma instância de `SpdaPhysicalDesign` ou `dict`."
        )

    dados = {
        "titulo_projeto": (
            "MEMORIAL DESCRITIVO E MEMÓRIA DE CÁLCULO\n"
            "SISTEMA DE PROTEÇÃO CONTRA DESCARGAS ATMOSFÉRICAS (SPDA) E MPS"
        ),
        "identificacao_edificacao": "Residencial Multifamiliar Vertical - 16 pavimentos",
        "autor_projetista": "Engenheiro(a) Eletricista Responsável — Registro CREA / ART",
        "cliente_empreendimento": "Condomínio Edifício Residencial Multifamiliar (16 Pavimentos)",
        "local_data": f"Brasil, {date.today().strftime('%d/%m/%Y')}",
        "L": fisico["L"],
        "W": fisico["W"],
        "H": fisico["H"],
        "h_caixa_dagua": fisico["h_caixa_dagua"],
        "Ng": 2.5,
        "Cd": 1.0,
    }
    dados.update(dados_gerais)

    return dados, res_r1, decisao, fisico


def gerar_memorial_docx(
    dados_gerais: dict[str, Any],
    resultado_risco: dict[str, Any] | ResultadoR1,
    diretrizes_fisicas: SpdaPhysicalDesign | dict[str, Any],
    nome_arquivo: str = "Memorial_Descritivo_SPDA.docx",
) -> Path:
    """Gera o Memorial Descritivo e de Cálculo de SPDA completo em arquivo Word (`.docx`).

    Args:
        dados_gerais: Metadados do projeto e grandezas de entrada (L, W, H, Ng, autor, etc.).
        resultado_risco: Objeto `ResultadoR1` ou dicionário com `resultado_r1` e `decisao`.
        diretrizes_fisicas: Objeto `SpdaPhysicalDesign` ou dicionário com subsistemas dimensionados.
        nome_arquivo: Nome ou caminho do arquivo `.docx` a ser salvo.

    Returns:
        `Path` absoluto do documento `.docx` gerado.
    """
    dados, res_r1, decisao, fisico = _normalizar_entradas(
        dados_gerais, resultado_risco, diretrizes_fisicas
    )

    nivel_adotado = str(fisico["nivel_protecao"])
    captacao = fisico["captacao"]
    descidas = fisico["descidas"]
    lateral = fisico["lateral"]
    aterramento = fisico["aterramento"]

    doc = Document()
    _configurar_estilos_documento(
        doc,
        titulo_curto=f"SPDA Nível {nivel_adotado} — {dados['identificacao_edificacao']}",
    )

    # =========================================================================
    # CAPA / CABEÇALHO EXECUTIVO
    # =========================================================================
    p_topo = doc.add_paragraph()
    p_topo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_topo.paragraph_format.space_before = Pt(24)
    p_topo.paragraph_format.space_after = Pt(6)
    r_sub = p_topo.add_run("PROJETO EXECUTIVO DE ENGENHARIA ELÉTRICA")
    r_sub.bold = True
    r_sub.font.size = Pt(11)
    r_sub.font.color.rgb = COR_SECUNDARIA

    p_titulo = doc.add_paragraph()
    p_titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_titulo.paragraph_format.space_before = Pt(12)
    p_titulo.paragraph_format.space_after = Pt(18)
    r_tit = p_titulo.add_run(dados["titulo_projeto"])
    r_tit.bold = True
    r_tit.font.size = Pt(18)
    r_tit.font.color.rgb = COR_PRIMARIA

    _adicionar_tabela_estilizada(
        doc,
        cabecalhos=["CAMPO DE IDENTIFICAÇÃO DO PROJETO", "DESCRIÇÃO TÉCNICA"],
        linhas=[
            ["Tipologia / Identificação da Edificação", str(dados["identificacao_edificacao"])],
            ["Empreendimento / Objeto", str(dados["cliente_empreendimento"])],
            ["Autor / Projetista Responsável", str(dados["autor_projetista"])],
            [
                "Nível de Proteção Adotado (SPDA + MPS)",
                f"Nível {nivel_adotado} (ABNT NBR 5419:2015)",
            ],
            ["Local e Data de Emissão", str(dados["local_data"])],
        ],
        larguras_cm=[6.5, 10.0],
    )

    _adicionar_subtitulo(doc, "Normas Técnicas de Referência")
    normas = [
        (
            "ABNT NBR 5419-1:2015 — ",
            "Proteção contra descargas atmosféricas — Parte 1: Princípios gerais;",
        ),
        (
            "ABNT NBR 5419-2:2015 — ",
            "Proteção contra descargas atmosféricas — Parte 2: Gerenciamento de risco;",
        ),
        (
            "ABNT NBR 5419-3:2015 — ",
            "Proteção contra descargas atmosféricas — Parte 3: Danos físicos a estruturas e perigos à vida;",
        ),
        (
            "ABNT NBR 5419-4:2015 — ",
            "Proteção contra descargas atmosféricas — Parte 4: Sistemas elétricos e eletrônicos internos na estrutura;",
        ),
        (
            "ABNT NBR 5410:2004 — ",
            "Instalações elétricas de baixa tensão (equipotencialização, aterramento e seleção de DPS).",
        ),
    ]
    for pref, desc in normas:
        _adicionar_item_lista(doc, pref, desc)

    doc.add_page_break()

    # =========================================================================
    # SEÇÃO 1: CARACTERÍSTICAS GEOMÉTRICAS E AMBIENTAIS
    # =========================================================================
    _adicionar_titulo_secao(doc, 1, "Características Geométricas e Ambientais")
    _adicionar_paragrafo_justificado(
        doc,
        f"O presente memorial tem por objetivo apresentar o gerenciamento de risco e o "
        f"dimensionamento executivo do Sistema de Proteção contra Descargas Atmosféricas (SPDA) "
        f"e das Medidas de Proteção contra Surtos (MPS) para um {dados['identificacao_edificacao']}, "
        f"modelado como estrutura isolada em terreno plano conforme o Anexo A da ABNT NBR 5419-2:2015.",
    )
    _adicionar_paragrafo_justificado(
        doc,
        "A Área de Exposição Equivalente (Ad) representa a superfície plana no solo que "
        "apresenta a mesma frequência anual de descargas diretas que a estrutura considerada, "
        "calculada por Ad = L·W + 2·(L + W)·3H + π·(3H)², a partir da qual se obtém o número "
        "anual médio de eventos perigosos diretos Nd = Ng · Ad · Cd · 10⁻⁶.",
    )

    _adicionar_tabela_estilizada(
        doc,
        cabecalhos=["PARÂMETRO GEOMÉTRICO / AMBIENTAL", "SÍMBOLO", "VALOR ADOTADO", "UNIDADE / REF."],
        linhas=[
            ["Comprimento em projeção horizontal", "L", f"{dados['L']:.2f}", "m"],
            ["Largura em projeção horizontal", "W", f"{dados['W']:.2f}", "m"],
            ["Perímetro da edificação", "P", f"{fisico['perimetro']:.2f}", "m"],
            ["Altura da cobertura principal", "H", f"{dados['H']:.2f}", "m"],
            [
                "Elevação da casa de máquinas / reservatório",
                "h_caixa",
                f"{dados['h_caixa_dagua']:.2f} (topo +{fisico['h_total']:.2f})",
                "m",
            ],
            [
                "Fator de localização da estrutura",
                "Cd",
                f"{dados['Cd']:.2f}",
                "Isolada (Tab. A.1)",
            ],
            [
                "Densidade de descargas atmosféricas para a terra",
                "Ng",
                f"{dados['Ng']:.2f}",
                "descargas/km²/ano",
            ],
            [
                "Área de exposição equivalente da estrutura",
                "Ad",
                f"{res_r1.Ad:,.2f}",
                "m² (NBR 5419-2)",
            ],
            [
                "Número anual médio de eventos perigosos diretos",
                "Nd",
                f"{res_r1.Nd:.4e}",
                "eventos/ano",
            ],
        ],
        larguras_cm=[7.5, 2.2, 3.8, 3.0],
    )

    # =========================================================================
    # SEÇÃO 2: MEMÓRIA DE CÁLCULO DO GERENCIAMENTO DE RISCO
    # =========================================================================
    _adicionar_titulo_secao(doc, 2, "Memória de Cálculo do Gerenciamento de Risco")
    _adicionar_paragrafo_justificado(
        doc,
        "Em conformidade com a ABNT NBR 5419-2:2015, avaliou-se o Risco R1 (risco de perda de "
        "vida humana ou ferimentos permanentes), cujo limite normativo tolerável é RT = 1,00 × 10⁻⁵ "
        "por ano (Tabela 4). O risco R1 foi decomposto nas parcelas associadas a descargas diretas "
        "na estrutura (Ra e Rb) e a surtos conduzidos pelas linhas externas de energia e sinal (Ru e Rv).",
    )

    status_mitigacao = (
        f"ATENDE (R1 mitigado ≤ RT com Nível {nivel_adotado})"
        if decisao["mitigado"]
        else "EXIGE MEDIDAS COMPLEMENTARES ALÉM DO NÍVEL I"
    )

    _adicionar_tabela_estilizada(
        doc,
        cabecalhos=["COMPONENTE / INDICADOR DE RISCO", "DESCRIÇÃO NORMATIVA", "VALOR (1/ANO)"],
        linhas=[
            [
                "Componente Ra (Sem SPDA)",
                "Choque elétrico por tensão de toque e passo na estrutura (S1)",
                f"{res_r1.Ra:.4e}",
            ],
            [
                "Componente Rb (Sem SPDA)",
                "Dano físico (incêndio/explosão) por descarga direta na estrutura (S1)",
                f"{res_r1.Rb:.4e}",
            ],
            [
                "Componente Ru (Sem DPS)",
                "Choque elétrico interno devido a surtos em linhas conectadas (S3)",
                f"{res_r1.Ru:.4e}",
            ],
            [
                "Componente Rv (Sem DPS)",
                "Dano físico devido a surtos transmitidos pelas linhas conectadas (S3)",
                f"{res_r1.Rv:.4e}",
            ],
            [
                "Risco Total Desprotegido (R1 inicial)",
                "Soma R1 = Ra + Rb + Ru + Rv antes das medidas de proteção",
                f"{decisao['r1_inicial']:.4e}",
            ],
            [
                "Risco Tolerável Normativo (RT)",
                "Limite máximo admissível para perda de vida humana (Tabela 4)",
                f"{decisao['rt']:.4e}",
            ],
            [
                f"Risco Residual Mitigado (SPDA + DPS Nível {nivel_adotado})",
                status_mitigacao,
                f"{decisao['r1_final']:.4e}",
            ],
        ],
        larguras_cm=[5.2, 7.8, 3.5],
        destacar_ultima_linha=True,
    )

    if decisao["iteracoes"]:
        _adicionar_subtitulo(doc, "2.1. Iteração Normativa dos Níveis de Proteção (IV → I)")
        linhas_iter = [
            [
                f"Nível {it['nivel']}",
                f"{it['PB']:.2f}",
                f"{it.get('PEB', 1.0):.2f}",
                f"{it['R1']:.4e}",
                "APROVADO (R1 ≤ RT)" if it["atende_RT"] else "INSUFICIENTE (R1 > RT)",
            ]
            for it in decisao["iteracoes"]
        ]
        _adicionar_tabela_estilizada(
            doc,
            cabecalhos=["NÍVEL TESTADO", "FATOR PB", "FATOR PEB", "R1 CALCULADO", "PARECER"],
            linhas=linhas_iter,
            larguras_cm=[3.0, 2.5, 2.5, 3.5, 5.0],
        )

    # =========================================================================
    # SEÇÃO 3: SUBSISTEMA DE CAPTAÇÃO
    # =========================================================================
    _adicionar_titulo_secao(doc, 3, "Subsistema de Captação (ABNT NBR 5419-3)")
    avaliacao_cap = fisico["avaliacao_captacao"]
    malha_max = captacao["dimensao_maxima_malha_m"]
    malha_proj = captacao["dimensao_projetada_malha_m"]
    modulos = captacao["modulos_LxW"]

    _adicionar_subtitulo(doc, "3.1 - Avaliação Comparativa dos Métodos de Captação")
    _adicionar_paragrafo_justificado(
        doc,
        f"Conforme o item 5.2.2 e a Tabela 2 da ABNT NBR 5419-3:2015, o posicionamento do "
        f"subsistema captor deve ser avaliado frente aos limites normativos do Nível "
        f"{nivel_adotado} (Raio da Esfera Rolante R = {avaliacao_cap['raio_esfera_m']:.0f} m e "
        f"dimensão máxima de malha {malha_max[0]:.0f} m × {malha_max[1]:.0f} m). A tabela a "
        f"seguir registra a memória de decisão e as limitações de cada método para a edificação:",
    )

    linhas_metodos = [
        [
            m["metodo"],
            m["aplicabilidade"],
            m["status"],
            m["justificativa"],
        ]
        for m in avaliacao_cap["metodos"]
    ]
    _adicionar_tabela_estilizada(
        doc,
        cabecalhos=[
            "MÉTODO (NBR 5419-3)",
            "APLICABILIDADE NA EDIFICAÇÃO",
            "STATUS",
            "LIMITAÇÕES E JUSTIFICATIVA NORMATIVA (TABELA 2)",
        ],
        linhas=linhas_metodos,
        larguras_cm=[3.4, 4.2, 2.2, 6.7],
    )

    _adicionar_paragrafo_justificado(
        doc,
        f"{avaliacao_cap['metodo_recomendado']}. {avaliacao_cap['parecer_tecnico']}",
        negrito_prefixo="Veredito Técnico de Seleção: ",
    )

    _adicionar_subtitulo(doc, "3.2 - Especificação Executiva do Subsistema Captor")
    _adicionar_paragrafo_justificado(
        doc,
        f"Para o Nível de Proteção {nivel_adotado}, detalha-se a solução de captação adotada: "
        f"{captacao['metodo']} (referência de abertura máxima de malha pela Tabela 2 da "
        f"ABNT NBR 5419-3:2015: {malha_max[0]:.0f} m × {malha_max[1]:.0f} m).",
    )
    _adicionar_item_lista(
        doc,
        "Arranjo e modulação adotada na cobertura: ",
        f"{modulos[0]} × {modulos[1]} vãos de {malha_proj[0]:.2f} m × "
        f"{malha_proj[1]:.2f} m, formados por {captacao['condutores_longitudinais']} eixos "
        f"longitudinais ({fisico['L']:.2f} m) e {captacao['condutores_transversais']} eixos "
        f"transversais ({fisico['W']:.2f} m), totalizando aproximadamente "
        f"{captacao['metragem_estimada_laje_principal_m']:.2f} m lineares estimados.",
    )
    _adicionar_item_lista(
        doc,
        "Especificação dos condutores captores (NBR 5419-3): ",
        captacao["condutor_recomendado"],
    )
    _adicionar_item_lista(
        doc,
        "Diretrizes construtivas específicas da cobertura / volume superior: ",
        captacao["malha_reservatorio"],
    )
    _adicionar_item_lista(
        doc,
        "Elementos metálicos na cobertura: ",
        "Rufos metálicos, guarda-corpos, escadas de marinheiro, tubulações aparentes, bases de "
        "exaustores e mastros de antenas deverão ser diretamente equipotencializados à malha "
        "captora ou protegidos por captores verticais dedicados quando aplicável.",
    )

    # =========================================================================
    # SEÇÃO 4: SUBSISTEMA DE DESCIDAS E EQUIPOTENCIALIZAÇÃO LATERAL
    # =========================================================================
    _adicionar_titulo_secao(doc, 4, "Subsistema de Descidas e Equipotencialização Lateral")
    _adicionar_paragrafo_justificado(
        doc,
        f"Conforme a Tabela 4 da ABNT NBR 5419-3:2015, o espaçamento médio normativo entre "
        f"condutores de descida para o Nível {nivel_adotado} é de "
        f"{descidas['espacamento_normativo_m']:.0f} m. Considerando o perímetro de "
        f"{fisico['perimetro']:.2f} m da projeção da edificação, exigem-se no mínimo "
        f"ceil({fisico['perimetro']:.2f} / {descidas['espacamento_normativo_m']:.0f}) = "
        f"{descidas['numero_minimo_descidas']} prumadas de descida distribuídas uniformemente "
        f"pelo perímetro (espaçamento médio efetivo de {descidas['espacamento_medio_efetivo_m']:.2f} m), "
        f"priorizando obrigatoriamente os cantos externos da torre.",
    )
    if fisico["usa_descidas_naturais"]:
        _adicionar_item_lista(
            doc,
            "Descidas estruturais naturais (ABNT NBR 5419-3, item 5.3.5): ",
            "Adota-se a utilização das armaduras de aço estrutural dos pilares de concreto armado "
            "como condutores naturais de descida, garantindo interligação elétrica contínua desde a "
            "malha captora na cobertura até a armadura das fundações (alternativamente mediante "
            "condutor dedicado de continuidade em barra redonda de aço galvanizado a fogo Ø 3/8\" / "
            "10 mm ou cobre nu 35 mm² solidário aos estribos/armaduras principais).",
        )
        _adicionar_item_lista(
            doc,
            "Ensaio obrigatório de continuidade elétrica (≤ 0,2 Ω): ",
            "De acordo com o item 5.3.5 e Anexo E da ABNT NBR 5419-3, a continuidade elétrica total "
            "entre a parte superior das descidas estruturais e o nível do aterramento/BEP no térreo "
            "deverá ser comprovada por medição com miliohmímetro de 4 fios (corrente mínima de ensaio "
            "de 1 A a 10 A), não podendo ultrapassar o valor máximo admissível de 0,2 Ω.",
        )
        _adicionar_item_lista(
            doc,
            "Caixas de equalização e inspeção: ",
            "Deverão ser instaladas caixas de equalização/ensaio acessíveis no pavimento térreo "
            "(ou subsolo técnico) interligadas aos pontos de afloramento das ferragens estruturais "
            "(rebars/conectores de latão estanhado) para medição periódica e inspeção.",
        )
    else:
        _adicionar_item_lista(
            doc,
            "Descidas externas não estruturais (ABNT NBR 5419-3, item 5.3): ",
            descidas["especificacao"],
        )
        _adicionar_item_lista(
            doc,
            "Conexões de ensaio e proteção mecânica: ",
            "Cada condutor de descida deverá possuir conexão de medição seccionável para ensaio "
            "junto à entrada no solo/térreo e proteção mecânica em eletroduto rígido nos últimos "
            "2,50 m acima do nível do piso acabado.",
        )

    if lateral["exige_protecao_lateral"]:
        _adicionar_caixa_destaque(
            doc,
            titulo="EXIGÊNCIA OBRIGATÓRIA — PROTEÇÃO CONTRA DESCARGAS LATERAIS E CINTAMENTO",
            texto=(
                f"{lateral['alerta']}\n\n"
                f"Cintamentos intermediários: {lateral['recomendacao']}"
            ),
        )
    else:
        _adicionar_item_lista(
            doc,
            "Avaliação de descargas laterais: ",
            lateral["recomendacao"],
        )

    # =========================================================================
    # SEÇÃO 5: SUBSISTEMA DE ATERRAMENTO E DPS
    # =========================================================================
    _adicionar_titulo_secao(doc, 5, "Subsistema de Aterramento e DPS (NBR 5419-3 e NBR 5419-4)")
    _adicionar_subtitulo(doc, "5.1. Eletrodo Natural de Aterramento pelas Fundações (Tipo B)")
    _adicionar_paragrafo_justificado(
        doc,
        "Em consonância com o item 5.4.4 da ABNT NBR 5419-3:2015, o subsistema de aterramento "
        "será constituído pelo aproveitamento integral das armaduras de aço interligadas das "
        "fundações em concreto armado da edificação (sapatas, blocos de coroamento, estacas e "
        "vigas baldrame periféricas), configurando um eletrodo de aterramento natural Tipo B "
        "(arranjo em anel/malha embutida). Todas as prumadas de descida e o Barramento de "
        "Equipotencialização Principal (BEP) deverão ser solidariamente conectados a essa malha, "
        "assegurando impedância reduzida de dispersão e controle das tensões de toque e passo.",
    )

    _adicionar_subtitulo(
        doc, "5.2. Medidas de Proteção contra Surtos (MPS) e Coordenação de DPS (NBR 5419-4)"
    )
    espec_iimp = DPS_IIMP_POR_NIVEL.get(nivel_adotado, DPS_IIMP_POR_NIVEL["IV"])
    _adicionar_paragrafo_justificado(
        doc,
        "Para mitigar as parcelas de risco associadas a impulsos eletromagnéticos (LEMP) e surtos "
        "conduzidos pelas redes externas (Ru e Rv), deverá ser implantado um sistema coordenado "
        "de Dispositivos de Proteção contra Surtos (DPS) nas mudanças de Zonas de Proteção contra "
        "Raios (ZPR), conforme a ABNT NBR 5419-4:2015 e a ABNT NBR 5410:2004:",
    )
    _adicionar_item_lista(
        doc,
        "QGBT (Transição ZPR 0A → ZPR 1) — DPS Classe I / Combinado Classe I+II: ",
        f"Instalar conjunto coordenado de DPS Classe I (ensaiado com forma de onda 10/350 µs) "
        f"junto ao Quadro Geral de Baixa Tensão (QGBT) conectado ao BEP, com capacidade mínima "
        f"de escoamento Iimp de referência: {espec_iimp}, tensão máxima de operação contínua "
        f"Uc ≥ 1,15 · U0 (ex.: Uc ≥ 275 Vca em redes 220/380 V ou 127/220 V) e nível de proteção "
        f"Up ≤ 1,5 kV (ou coordenado com estágio Classe II para limitar a tensão residual).",
    )
    _adicionar_item_lista(
        doc,
        "Quadros de Distribuição Secundários (ZPR 1 → ZPR 2) — DPS Classe II: ",
        "Instalar DPS Classe II (forma de onda 8/20 µs, In ≥ 20 kA, Imáx ≥ 40 kA, Up ≤ 1,2–1,5 kV) "
        "nos quadros de distribuição de serviços condominiais (elevadores, bombas de recalque, "
        "portaria/automação) e nos QDCs das unidades autônomas, respeitando o desacoplamento "
        "energético com o DPS de entrada.",
    )
    _adicionar_item_lista(
        doc,
        "Linhas de Sinal, Telecomunicações e Dados: ",
        "Instalar protetores de surto específicos para linhas de sinal/telecom/interfone/CFTV "
        "no DG/sala de telecomunicações na entrada da edificação, interligados ao barramento de "
        "equipotencialização local (BEL/BEP) com condutores de ligação curtos e retilíneos "
        "(comprimento total das conexões ≤ 0,50 m).",
    )

    # =========================================================================
    # SEÇÃO 6: CONCLUSÃO E TERMO DE RESPONSABILIDADE TÉCNICA
    # =========================================================================
    _adicionar_titulo_secao(doc, 6, "Conclusão e Termo de Responsabilidade Técnica")
    _adicionar_paragrafo_justificado(
        doc,
        f"Conclui-se que a adoção conjunta do Sistema de Proteção contra Descargas Atmosféricas "
        f"(SPDA) classificado no Nível {nivel_adotado} e das Medidas de Proteção contra Surtos "
        f"(MPS/DPS coordenados) reduz o risco anual de perda de vida humana de "
        f"R1 = {decisao['r1_inicial']:.4e} para R1 = {decisao['r1_final']:.4e}, atendendo "
        f"integralmente ao limite normativo tolerável RT = {decisao['rt']:.4e} estabelecido "
        f"pela ABNT NBR 5419-2:2015.",
    )
    _adicionar_paragrafo_justificado(
        doc,
        "Declara-se, para os devidos fins junto aos órgãos públicos, Corpo de Bombeiros, "
        "concessionárias e condomínio, que as diretrizes técnicas, memórias de cálculo e "
        "especificações construtivas constantes neste Memorial Descritivo encontram-se em "
        "plena conformidade com as normas vigentes da Associação Brasileira de Normas Técnicas, "
        "em especial a série ABNT NBR 5419:2015 (Partes 1, 2, 3 e 4) e a ABNT NBR 5410:2004, "
        "devendo a execução em obra observar rigorosamente os ensaios de continuidade elétrica "
        "e a emissão de laudo fotográfico e de comissionamento antes da energização definitiva.",
    )

    p_espaco = doc.add_paragraph()
    p_espaco.paragraph_format.space_before = Pt(28)
    p_espaco.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_espaco.add_run(f"{dados['local_data']}\n\n\n")
    r_linha = p_espaco.add_run("__________________________________________________________\n")
    r_linha.bold = True
    r_ass = p_espaco.add_run(f"{dados['autor_projetista']}\n")
    r_ass.bold = True
    r_ass.font.color.rgb = COR_PRIMARIA
    r_art = p_espaco.add_run("CREA / CFT nº: _______________________   |   ART / TRT nº: _______________________")
    r_art.font.size = Pt(9.5)
    r_art.font.color.rgb = COR_CINZA_SUTIL

    if isinstance(nome_arquivo, io.BytesIO) or hasattr(nome_arquivo, "write"):
        doc.save(nome_arquivo)
        if hasattr(nome_arquivo, "seek"):
            nome_arquivo.seek(0)
        return nome_arquivo  # type: ignore[return-value]

    caminho_saida = Path(nome_arquivo).resolve()
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(caminho_saida))
    return caminho_saida


def gerar_memorial_bytes(
    dados_gerais: dict[str, Any],
    resultado_risco: dict[str, Any] | ResultadoR1,
    diretrizes_fisicas: SpdaPhysicalDesign | dict[str, Any],
) -> bytes:
    """Gera o Memorial Descritivo em memória (`BytesIO`) e retorna os bytes do `.docx`."""
    buffer = io.BytesIO()
    gerar_memorial_docx(
        dados_gerais=dados_gerais,
        resultado_risco=resultado_risco,
        diretrizes_fisicas=diretrizes_fisicas,
        nome_arquivo=buffer,  # type: ignore[arg-type]
    )
    return buffer.getvalue()


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Gera o Memorial Descritivo de SPDA em Word (.docx) integrando "
            "`risk_engine.py` e `physical_design.py`."
        )
    )
    parser.add_argument(
        "-L",
        "--comprimento",
        type=float,
        default=24.0,
        help="Comprimento L da edificação em metros (padrão: 24.0)",
    )
    parser.add_argument(
        "-W",
        "--largura",
        type=float,
        default=18.0,
        help="Largura W da edificação em metros (padrão: 18.0)",
    )
    parser.add_argument(
        "-H",
        "--altura",
        type=float,
        default=49.0,
        help="Altura H da edificação em metros (padrão: 49.0)",
    )
    parser.add_argument(
        "--h-caixa",
        type=float,
        default=3.8,
        help="Altura da caixa d'água / casa de máquinas em metros (padrão: 3.8)",
    )
    parser.add_argument(
        "-Ng",
        "--ng",
        dest="ng",
        type=float,
        default=2.5,
        help="Densidade de descargas atmosféricas Ng em descargas/km²/ano (padrão: 2.5)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="Memorial_Descritivo_SPDA.docx",
        help="Nome do arquivo .docx de saída (padrão: Memorial_Descritivo_SPDA.docx)",
    )
    parser.add_argument(
        "--autor",
        default="Eng. Eletricista Responsável — CREA / Registro Profissional",
        help="Nome e registro do autor/projetista exibido na capa e termo técnico",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa o pipeline completo (NBR 5419-2 -> NBR 5419-3 -> .docx)."""
    parser = _construir_parser()
    args = parser.parse_args(argv)

    try:
        # 1. Gerenciamento de Risco (ABNT NBR 5419-2)
        resultado_r1 = calcular_risco_r1(
            L=args.comprimento,
            W=args.largura,
            H=args.altura,
            Ng=args.ng,
        )
        decisao = determinar_nivel_protecao(resultado_r1)

        # Caso R1 <= RT por Ng muito baixo, adota Nível IV construtivo; se > Nível I, usa Nível I
        if not decisao["necessita_protecao"]:
            nivel_projeto = "IV"
        elif not decisao["mitigado"]:
            nivel_projeto = "I"
        else:
            nivel_projeto = str(decisao["nivel_protecao"])

        # 2. Dimensionamento Físico Executivo (ABNT NBR 5419-3)
        projeto_fisico = SpdaPhysicalDesign(
            nivel_protecao=nivel_projeto,
            L=args.comprimento,
            W=args.largura,
            H=args.altura,
            h_caixa_dagua=args.h_caixa,
            usa_descidas_naturais=True,
        )

        # 3. Geração do Memorial Descritivo em Word (.docx)
        dados_gerais = {
            "identificacao_edificacao": "Residencial Multifamiliar Vertical - 16 pavimentos",
            "autor_projetista": args.autor,
            "L": args.comprimento,
            "W": args.largura,
            "H": args.altura,
            "h_caixa_dagua": args.h_caixa,
            "Ng": args.ng,
            "Cd": 1.0,
        }

        caminho_docx = gerar_memorial_docx(
            dados_gerais=dados_gerais,
            resultado_risco={"resultado_r1": resultado_r1, "decisao": decisao},
            diretrizes_fisicas=projeto_fisico,
            nome_arquivo=args.output,
        )

        print(f"Memorial Descritivo gerado com sucesso: {caminho_docx}")
        print(
            f"Resumo: L={args.comprimento}m | W={args.largura}m | H={args.altura}m "
            f"(+{args.h_caixa}m) | Ng={args.ng} | R1_inicial={decisao['r1_inicial']:.4e} -> "
            f"Nível {nivel_projeto} (R1_mitigado={decisao['r1_final']:.4e})"
        )
        return 0
    except Exception as exc:
        print(f"Erro ao gerar memorial .docx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
