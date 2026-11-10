#!/usr/bin/env python3
"""Aplicação Web Universal (Streamlit) — Dimensionador de SPDA ABNT NBR 5419.

Atende dinamicamente casas unifamiliares, galpões metálicos, edifícios verticais e
estruturas hospitalares/especiais integrando:
- `risk_engine.py` (ABNT NBR 5419-2: Gerenciamento de Risco por Tipologia);
- `physical_design.py` (ABNT NBR 5419-3: Seleção Dinâmica de Captação e Descidas);
- `document_generator.py` (Emissão de Memorial Descritivo em Word `.docx`).
"""

from __future__ import annotations

import io
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from document_generator import gerar_memorial_docx
from physical_design import PASSO_ANEIS_CINTAMENTO_M, SpdaPhysicalDesign
from risk_engine import (
    LISTA_TIPOLOGIAS,
    PERFIS_TIPOLOGIA,
    RISCO_TOLERAVEL_R1,
    TipologiaEdificacao,
    calcular_risco_r1,
    determinar_nivel_protecao,
)

# Configuração da Página
st.set_page_config(
    page_title="Dimensionador de SPDA - NBR 5419",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inicializar_estado_sessao() -> None:
    """Inicializa os parâmetros de `st.session_state` com a tipologia inicial."""
    if "tipologia_selecionada" not in st.session_state:
        tipologia_inicial = TipologiaEdificacao.EDIFICIO_VERTICAL.value
        st.session_state["tipologia_selecionada"] = tipologia_inicial
        _aplicar_perfil_no_estado(tipologia_inicial)


def _aplicar_perfil_no_estado(tipologia: str) -> None:
    """Carrega dimensões, premissas de descidas e fatores NBR 5419-2 da tipologia."""
    perfil = PERFIS_TIPOLOGIA[tipologia]
    st.session_state["L_input"] = float(perfil["L_padrao"])
    st.session_state["W_input"] = float(perfil["W_padrao"])
    st.session_state["H_input"] = float(perfil["H_padrao"])
    st.session_state["h_caixa_input"] = float(perfil["h_caixa_padrao"])
    st.session_state["Ng_input"] = float(perfil["Ng_padrao"])
    st.session_state["descidas_naturais_input"] = bool(
        perfil["usa_descidas_naturais_padrao"]
    )
    st.session_state["rf_input"] = float(perfil["rf"])
    st.session_state["rp_input"] = float(perfil["rp"])
    st.session_state["lf_input"] = float(perfil["lf"])


def _ao_mudar_tipologia() -> None:
    """Callback disparado ao alterar `st.selectbox('Tipo de Edificação')`."""
    _aplicar_perfil_no_estado(st.session_state["tipologia_selecionada"])


def calcular_pontos_descidas_perimetro(
    L: float,
    W: float,
    num_descidas: int,
) -> list[tuple[float, float, str]]:
    """Calcula coordenadas (x, y, rótulo) das descidas distribuídas no perímetro L x W."""
    if num_descidas <= 1:
        return [(0.0, 0.0, "D1")]
    if num_descidas == 2:
        return [(0.0, 0.0, "D1"), (L, W, "D2")]
    if num_descidas == 3:
        return [(0.0, 0.0, "D1"), (L, 0.0, "D2"), (L / 2.0, W, "D3")]

    comprimentos_lados = [L, W, L, W]
    divisoes = [1, 1, 1, 1]

    for _ in range(num_descidas - 4):
        indice_maior_vao = max(
            range(4),
            key=lambda idx: comprimentos_lados[idx] / divisoes[idx],
        )
        divisoes[indice_maior_vao] += 1

    coordenadas_brutas: list[tuple[float, float]] = []

    for k in range(divisoes[0]):
        coordenadas_brutas.append((L * k / divisoes[0], 0.0))
    for k in range(divisoes[1]):
        coordenadas_brutas.append((L, W * k / divisoes[1]))
    for k in range(divisoes[2]):
        coordenadas_brutas.append((L * (1.0 - k / divisoes[2]), W))
    for k in range(divisoes[3]):
        coordenadas_brutas.append((0.0, W * (1.0 - k / divisoes[3])))

    return [(x, y, f"D{idx + 1}") for idx, (x, y) in enumerate(coordenadas_brutas)]


def _posicao_rotulo_perimetro(x: float, y: float, L: float, W: float) -> str:
    """Define a posição externa ideal do rótulo (D1..Dn) para não sobrepor a malha."""
    na_esquerda = abs(x) < 1e-6
    na_direita = abs(x - L) < 1e-6
    embaixo = abs(y) < 1e-6
    em_cima = abs(y - W) < 1e-6

    if embaixo and na_esquerda:
        return "bottom left"
    if embaixo and na_direita:
        return "bottom right"
    if em_cima and na_esquerda:
        return "top left"
    if em_cima and na_direita:
        return "top right"
    if embaixo:
        return "bottom center"
    if em_cima:
        return "top center"
    if na_direita:
        return "middle right"
    if na_esquerda:
        return "middle left"
    return "top center"


def construir_grafico_cobertura(
    projeto: SpdaPhysicalDesign,
    captacao: dict[str, Any],
    descidas: dict[str, Any],
) -> go.Figure:
    """Gera planta 2D interativa em Dark Mode adaptada ao método de captação selecionado."""
    L = projeto.L
    W = projeto.W
    codigo_captacao = captacao.get("tipo_captacao_codigo", "malha_faraday")
    modulos_l, modulos_w = captacao["modulos_LxW"]
    dx, dy = captacao["dimensao_projetada_malha_m"]
    malha_max_l, malha_max_w = captacao["dimensao_maxima_malha_m"]
    num_descidas = descidas["numero_minimo_descidas"]

    fig = go.Figure()

    # 1. Perímetro da cobertura (espessura destacada)
    rotulo_contorno = (
        f"Beiral do Telhado ({L:.1f}×{W:.1f} m)"
        if codigo_captacao == "cumeeira_franklin"
        else f"Cobertura Metálica ({L:.1f}×{W:.1f} m)"
        if codigo_captacao == "galpao_cumeeira_telha"
        else f"Perímetro da Laje ({L:.1f}×{W:.1f} m)"
    )
    fig.add_trace(
        go.Scatter(
            x=[0, L, L, 0, 0],
            y=[0, 0, W, W, 0],
            fill="toself",
            fillcolor="rgba(56, 65, 82, 0.55)",
            line={"color": "#CBD5E1", "width": 5.5},
            mode="lines",
            name=rotulo_contorno,
            hoverinfo="name",
        )
    )

    # 2. Volume superior (reservatório / ático) tracejado com transparência visível
    if projeto.h_caixa_dagua > 0:
        l_atico = min(max(L * 0.25, 2.5), L * 0.50)
        w_atico = min(max(W * 0.25, 2.5), W * 0.50)
        x0 = (L - l_atico) / 2.0
        x1 = x0 + l_atico
        y0 = (W - w_atico) / 2.0
        y1 = y0 + w_atico
        fig.add_trace(
            go.Scatter(
                x=[x0, x1, x1, x0, x0],
                y=[y0, y0, y1, y1, y0],
                fill="toself",
                fillcolor="rgba(255, 165, 0, 0.24)",
                line={"color": "#FFA500", "width": 2.4, "dash": "dash"},
                mode="lines",
                name=f"Reservatório / Cumeeira (+{projeto.h_total:.1f} m)",
                hovertemplate=(
                    "<b>Volume Superior / Elevação Complementar</b><br>"
                    f"Elevação adicional: +{projeto.h_caixa_dagua:.2f} m (Topo +{projeto.h_total:.2f} m)<extra></extra>"
                ),
            )
        )

    # 3. Subsistema de Captação conforme método dinâmico selecionado
    xs_cap: list[float | None] = []
    ys_cap: list[float | None] = []

    if codigo_captacao == "cumeeira_franklin":
        # Cabo captor na cumeeira central (y = W/2) + descidas pelas águas até os beirais
        y_cum = W / 2.0
        xs_cap.extend([0.0, L, None])
        ys_cap.extend([y_cum, y_cum, None])

        qtd_trav = captacao["condutores_transversais"]
        passo_x = L / max(1, qtd_trav - 1)
        for i in range(qtd_trav):
            x_pos = round(i * passo_x, 4)
            xs_cap.extend([x_pos, x_pos, None])
            ys_cap.extend([0.0, W, None])

        alfa = captacao.get("angulo_protecao_graus") or 70.0
        nome_cap = f"Cabo na Cumeeira + Captores (α ≈ {alfa:.0f}°)"

        fig.add_trace(
            go.Scatter(
                x=xs_cap,
                y=ys_cap,
                mode="lines",
                line={"color": "#00E5FF", "width": 3.0},
                name=nome_cap,
                hovertemplate=(
                    f"<b>Cabo Captor de Cumeeira — Nível {projeto.nivel_protecao}</b><br>"
                    f"Ângulo de proteção α ≈ {alfa:.1f}°<br>"
                    "Coord.: (%{x:.2f} m, %{y:.2f} m)<extra></extra>"
                ),
            )
        )

        # Marca hastes Franklin sugeridas ao longo da cumeeira
        xs_franklin = [round(L * f, 2) for f in (0.15, 0.50, 0.85)] if L >= 12 else [round(L / 2.0, 2)]
        ys_franklin = [y_cum for _ in xs_franklin]
        fig.add_trace(
            go.Scatter(
                x=xs_franklin,
                y=ys_franklin,
                mode="markers",
                marker={
                    "size": 12,
                    "color": "#FFA500",
                    "symbol": "diamond",
                    "line": {"color": "#FFFFFF", "width": 1.8},
                },
                name=" Captores Franklin (Cumeeira)",
                hovertemplate=(
                    f"<b>Haste Captora Franklin (α ≈ {alfa:.1f}°)</b><br>"
                    "Posição na cumeeira: (%{x:.2f} m, %{y:.2f} m)<extra></extra>"
                ),
            )
        )

    elif codigo_captacao == "galpao_cumeeira_telha":
        # Beirais (y=0, y=W) + Cumeeira central (y=W/2) + fechamentos transversais
        for y_eixo in (0.0, W / 2.0, W):
            xs_cap.extend([0.0, L, None])
            ys_cap.extend([y_eixo, y_eixo, None])

        for i in range(modulos_l + 1):
            x_pos = round(i * dx, 4)
            xs_cap.extend([x_pos, x_pos, None])
            ys_cap.extend([0.0, W, None])

        fig.add_trace(
            go.Scatter(
                x=xs_cap,
                y=ys_cap,
                mode="lines",
                line={"color": "#00E5FF", "width": 2.8},
                name=f"Cumeeira/Beirais ou Telha Natural (Nível {projeto.nivel_protecao})",
                hovertemplate=(
                    f"<b>Captação Galpão — Nível {projeto.nivel_protecao}</b><br>"
                    "Cumeeira + Beirais ou Telha Metálica Natural (Tabela 3 NBR 5419-3)<br>"
                    "Coord.: (%{x:.2f} m, %{y:.2f} m)<extra></extra>"
                ),
            )
        )
    else:
        # Malha Gaiola de Faraday clássica
        for i in range(modulos_l + 1):
            x_pos = round(i * dx, 4)
            xs_cap.extend([x_pos, x_pos, None])
            ys_cap.extend([0.0, W, None])

        for j in range(modulos_w + 1):
            y_pos = round(j * dy, 4)
            xs_cap.extend([0.0, L, None])
            ys_cap.extend([y_pos, y_pos, None])

        fig.add_trace(
            go.Scatter(
                x=xs_cap,
                y=ys_cap,
                mode="lines",
                line={"color": "#00E5FF", "width": 2.8},
                name=(
                    f"Malha Captora Nível {projeto.nivel_protecao} "
                    f"({dx:.1f}×{dy:.1f} m ≤ {malha_max_l:.0f}×{malha_max_w:.0f} m)"
                ),
                hovertemplate=(
                    f"<b>Condutor Captor — Nível {projeto.nivel_protecao}</b><br>"
                    f"Módulo projetado: {dx:.2f} m × {dy:.2f} m<br>"
                    "Coord.: (%{x:.2f} m, %{y:.2f} m)<extra></extra>"
                ),
            )
        )

    # 4. Pontos perimétricos das descidas (marcadores circulares contrastantes + rótulos D1..Dn)
    pontos_descidas = calcular_pontos_descidas_perimetro(L, W, num_descidas)
    xs_desc = [pt[0] for pt in pontos_descidas]
    ys_desc = [pt[1] for pt in pontos_descidas]
    rotulos_desc = [pt[2] for pt in pontos_descidas]
    posicoes_texto = [
        _posicao_rotulo_perimetro(pt[0], pt[1], L, W) for pt in pontos_descidas
    ]

    tipo_pilar = (
        "Descida Natural (Pilar)"
        if projeto.usa_descidas_naturais
        else "Descida Externa Aparente"
    )
    cor_marcador = "#FF3B30" if projeto.usa_descidas_naturais else "#FFD60A"

    fig.add_trace(
        go.Scatter(
            x=xs_desc,
            y=ys_desc,
            mode="markers+text",
            text=rotulos_desc,
            textposition=posicoes_texto,
            textfont={"size": 12, "color": "#FFFFFF", "family": "Arial Black, sans-serif"},
            cliponaxis=False,
            marker={
                "size": 14,
                "color": cor_marcador,
                "symbol": "circle",
                "line": {"color": "#FFFFFF", "width": 2.2},
            },
            name=f"{tipo_pilar} ({num_descidas}x)",
            hovertemplate=(
                f"<b>%{{text}} — {tipo_pilar}</b><br>"
                "Posição na planta: X = %{x:.2f} m | Y = %{y:.2f} m<br>"
                f"Espaçamento médio efetivo: {descidas['espacamento_medio_efetivo_m']:.2f} m<extra></extra>"
            ),
        )
    )

    margem_x = max(L * 0.12, 3.0)
    margem_y = max(W * 0.16, 3.0)

    titulo_curto_metodo = (
        "Cumeeira / Franklin"
        if codigo_captacao == "cumeeira_franklin"
        else "Cumeeira / Telha Natural"
        if codigo_captacao == "galpao_cumeeira_telha"
        else "Gaiola de Faraday"
    )

    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#1E2229",
        paper_bgcolor="#1E2229",
        font={"color": "#E0E0E0", "size": 12},
        title={
            "text": (
                f"Planta de Cobertura — {titulo_curto_metodo} (Nível {projeto.nivel_protecao}) "
                f"e Descidas ({num_descidas} pontos)"
            ),
            "x": 0.02,
            "font": {"size": 15, "color": "#E0E0E0"},
        },
        xaxis={
            "title": {"text": "Comprimento L (m)", "font": {"color": "#E0E0E0"}},
            "tickfont": {"color": "#E0E0E0"},
            "range": [-margem_x, L + margem_x],
            "zeroline": False,
            "showgrid": True,
            "gridcolor": "#333842",
        },
        yaxis={
            "title": {"text": "Largura W (m)", "font": {"color": "#E0E0E0"}},
            "tickfont": {"color": "#E0E0E0"},
            "range": [-margem_y, W + margem_y],
            "scaleanchor": "x",
            "scaleratio": 1,
            "zeroline": False,
            "showgrid": True,
            "gridcolor": "#333842",
        },
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.25,
            "xanchor": "center",
            "x": 0.5,
            "font": {"color": "#FFFFFF", "size": 11},
            "bgcolor": "rgba(0,0,0,0.5)",
        },
        margin={"l": 35, "r": 35, "t": 60, "b": 100},
        height=540,
    )
    return fig


def main() -> None:
    """Renderiza a interface universal do Dimensionador de SPDA no Streamlit."""
    _inicializar_estado_sessao()

    # =========================================================================
    # BARRA LATERAL (SIDEBAR) COM ADAPTAÇÃO AUTOMÁTICA POR TIPOLOGIA
    # =========================================================================
    with st.sidebar:
        st.header("🏢 Tipologia e Parâmetros")

        tipologia = st.selectbox(
            "Tipo de Edificação",
            options=list(LISTA_TIPOLOGIAS),
            key="tipologia_selecionada",
            on_change=_ao_mudar_tipologia,
            help=(
                "Selecionar a tipologia ajusta automaticamente dimensões típicas, "
                "fatores de risco NBR 5419-2, método de captação e premissas de descida."
            ),
        )
        perfil_ativo = PERFIS_TIPOLOGIA[tipologia]

        st.divider()
        st.caption("Geometria e Densidade Atmosférica")

        L = st.slider(
            "Comprimento L (m)",
            min_value=5.0,
            max_value=150.0,
            step=0.5,
            key="L_input",
            help="Comprimento da projeção horizontal da edificação em metros.",
        )
        W = st.slider(
            "Largura W (m)",
            min_value=5.0,
            max_value=120.0,
            step=0.5,
            key="W_input",
            help="Largura da projeção horizontal da edificação em metros.",
        )
        H = st.slider(
            "Altura principal H (m)",
            min_value=3.0,
            max_value=150.0,
            step=0.5,
            key="H_input",
            help="Altura até a laje de cobertura principal ou beiral da edificação.",
        )
        h_caixa = st.number_input(
            "Altura da caixa d'água / cumeeira / ático (m)",
            min_value=0.0,
            max_value=25.0,
            step=0.1,
            format="%.1f",
            key="h_caixa_input",
            help="Elevação complementar acima de H (casa de máquinas, reservatório ou cumeeira).",
        )
        Ng = st.number_input(
            "Densidade de descargas Ng (raios/km²/ano)",
            min_value=0.1,
            max_value=35.0,
            step=0.1,
            format="%.1f",
            key="Ng_input",
            help="Densidade anual de descargas atmosféricas na região (Anexo F da NBR 5419-2).",
        )

        rotulo_checkbox_descidas = (
            "Utilizar pilares metálicos como descidas naturais"
            if tipologia == TipologiaEdificacao.GALPAO_INDUSTRIAL.value
            else "Utilizar armaduras dos pilares como descidas naturais"
        )
        usa_descidas_naturais = st.checkbox(
            rotulo_checkbox_descidas,
            key="descidas_naturais_input",
            help="Aplica o item 5.3.5 da ABNT NBR 5419-3 com ensaio de continuidade ≤ 0,2 Ω.",
        )

        with st.expander("⚙️ Fatores de Risco NBR 5419-2 (Tipologia)", expanded=False):
            rf = st.number_input(
                "Risco de incêndio (rf)",
                min_value=0.0001,
                max_value=1.0,
                step=0.005,
                format="%.4f",
                key="rf_input",
                help="Tabela C.5: 0.1 (alto), 0.01 (ordinário), 0.001 (baixo).",
            )
            rp = st.number_input(
                "Providências contra incêndio (rp)",
                min_value=0.1,
                max_value=1.0,
                step=0.1,
                format="%.2f",
                key="rp_input",
                help="Tabela C.4: 1.0 (nenhuma), 0.5 (hidrantes/extintores), 0.2 (sprinklers).",
            )
            lf = st.number_input(
                "Perda típica por dano físico (Lf)",
                min_value=0.001,
                max_value=0.5,
                step=0.01,
                format="%.3f",
                key="lf_input",
                help="Tabela C.2: 0.10 (hospital/escola), 0.02 (industrial/comercial), 0.01 (residencial).",
            )

        recalcular = st.button(
            "🔄 Recalcular Dimensionamento",
            type="primary",
            width="stretch",
        )
        if recalcular:
            st.toast(f"Projeto recalculado para: {tipologia}", icon="⚡")

    # =========================================================================
    # PIPELINE DE CÁLCULO UNIVERSAL (NBR 5419-2 -> NBR 5419-3)
    # =========================================================================
    resultado_r1 = calcular_risco_r1(
        L=L,
        W=W,
        H=H,
        Ng=Ng,
        tipologia=tipologia,
        rf=rf,
        rp=rp,
        lf=lf,
    )
    decisao_risco = determinar_nivel_protecao(resultado_r1, RT=RISCO_TOLERAVEL_R1)

    if not decisao_risco["necessita_protecao"]:
        rotulo_nivel_metrica = "Dispensado (Adotado IV)"
        delta_nivel = f"R1 = {decisao_risco['r1_inicial']:.2e} ≤ RT"
        nivel_dimensionamento = "IV"
    elif decisao_risco["mitigado"]:
        nivel_dimensionamento = str(decisao_risco["nivel_protecao"])
        rotulo_nivel_metrica = f"Nível {nivel_dimensionamento}"
        delta_nivel = f"R1 mitigado: {decisao_risco['r1_final']:.2e} ≤ RT"
    else:
        nivel_dimensionamento = "I"
        rotulo_nivel_metrica = "Nível I + Med. Adic."
        delta_nivel = f"R1 residual: {decisao_risco['r1_final']:.2e} > RT"

    projeto_fisico = SpdaPhysicalDesign(
        nivel_protecao=nivel_dimensionamento,
        L=L,
        W=W,
        H=H,
        h_caixa_dagua=h_caixa,
        usa_descidas_naturais=usa_descidas_naturais,
        tipologia=tipologia,
    )

    avaliacao_captacao = projeto_fisico.avaliar_captacao()
    captacao = projeto_fisico.dimensionar_captacao()
    descidas = projeto_fisico.dimensionar_descidas()
    lateral = projeto_fisico.dimensionar_protecao_lateral_e_aneis()
    aterramento = projeto_fisico.dimensionar_aterramento()

    # Prepara o Memorial .docx em memória (BytesIO) adaptado à tipologia atual
    dados_gerais = {
        "identificacao_edificacao": tipologia,
        "cliente_empreendimento": f"Projeto Executivo de SPDA — {tipologia}",
        "autor_projetista": "Eng. Eletricista Responsável — CREA / Registro Profissional",
        "L": L,
        "W": W,
        "H": H,
        "h_caixa_dagua": h_caixa,
        "Ng": Ng,
        "Cd": 1.0,
    }
    buffer_docx = io.BytesIO()
    gerar_memorial_docx(
        dados_gerais=dados_gerais,
        resultado_risco={"resultado_r1": resultado_r1, "decisao": decisao_risco},
        diretrizes_fisicas=projeto_fisico,
        nome_arquivo=buffer_docx,  # type: ignore[arg-type]
    )

    # =========================================================================
    # ÁREA PRINCIPAL — CABEÇALHO EXECUTIVO, JUSTIFICATIVA E DOWNLOAD DIRETO
    # =========================================================================
    col_titulo, col_download = st.columns([3.2, 1.3], vertical_alignment="center")
    with col_titulo:
        st.title("⚡ Dimensionador Universal de SPDA — ABNT NBR 5419")
        st.markdown(
            f"**{tipologia}** &nbsp;|&nbsp; "
            f"Planta `{L:.1f} m × {W:.1f} m` &nbsp;|&nbsp; "
            f"Altura `+{H:.1f} m` (Topo `+{projeto_fisico.h_total:.1f} m`) &nbsp;|&nbsp; "
            f"Descidas: **{'Estruturais Naturais' if usa_descidas_naturais else 'Externas Aparentes'}**"
        )
    with col_download:
        st.download_button(
            label="📄 Baixar Memorial Descritivo (.docx)",
            data=buffer_docx.getvalue(),
            file_name="Memorial_Descritivo_SPDA.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            width="stretch",
            help="Gera e baixa imediatamente o Memorial Descritivo completo em formato Word.",
        )

    st.info(
        f"**Justificativa Normativa ({tipologia}):** {perfil_ativo['justificativa_normativa']}",
        icon="📘",
    )

    # =========================================================================
    # 4 MÉTRICAS EM DESTAQUE
    # =========================================================================
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        label="Área Exposta Equivalente (Ad)",
        value=f"{resultado_r1.Ad:,.2f} m²",
        delta=f"Perímetro: {projeto_fisico.perimetro:.1f} m",
        delta_color="off",
    )
    m2.metric(
        label="Frequência Anual de Raios (Nd)",
        value=f"{resultado_r1.Nd:.4f} /ano",
        delta=f"Ng = {Ng:.1f} raios/km²/ano",
        delta_color="off",
    )
    m3.metric(
        label="Nível de Proteção Necessário",
        value=rotulo_nivel_metrica,
        delta=delta_nivel,
        delta_color="normal" if decisao_risco["mitigado"] else "inverse",
    )
    m4.metric(
        label="Quantidade Mínima de Descidas",
        value=f"{descidas['numero_minimo_descidas']} descidas",
        delta=f"Espaç. médio: {descidas['espacamento_medio_efetivo_m']:.1f} m (máx. {descidas['espacamento_normativo_m']:.0f} m)",
        delta_color="off",
    )

    # =========================================================================
    # CARD EM DESTAQUE — MÉTODO DE CAPTAÇÃO RECOMENDADO E TABELA COMPARATIVA
    # =========================================================================
    icone_status = {
        "Recomendado": "🟢 Recomendado",
        "Restrito": "🟡 Restrito",
        "Inaplicável": "🔴 Inaplicável",
    }
    resumo_alfa = (
        f"α ≈ {avaliacao_captacao['angulo_alfa_graus']:.1f}°"
        if avaliacao_captacao["angulo_alfa_graus"] is not None
        else f"Não aplicável (H ≥ {avaliacao_captacao['raio_esfera_m']:.0f} m)"
    )
    malha_lim_l, malha_lim_w = avaliacao_captacao["malha_maxima_m"]

    with st.container(border=True):
        st.subheader("🎯 Método de Captação Recomendado pela Norma")
        st.success(
            f"**Veredito Normativo (ABNT NBR 5419-3, item 5.2.2 e Tabela 2):** "
            f"{avaliacao_captacao['metodo_recomendado']}\n\n"
            f"**Parâmetros Tabela 2 (Nível {nivel_dimensionamento}):** "
            f"`R = {avaliacao_captacao['raio_esfera_m']:.0f} m` &nbsp;|&nbsp; "
            f"`Malha máx. = {malha_lim_l:.0f} × {malha_lim_w:.0f} m` &nbsp;|&nbsp; "
            f"`Ângulo Franklin: {resumo_alfa}`\n\n"
            f"{avaliacao_captacao['parecer_tecnico']}"
        )

        linhas_comparativas = [
            {
                "Método": item["metodo"],
                "Aplicabilidade na Edificação": item["aplicabilidade"],
                "Status": icone_status.get(item["status"], item["status"]),
                "Justificativa Normativa": item["justificativa"],
            }
            for item in avaliacao_captacao["metodos"]
        ]
        st.table(linhas_comparativas)

    # =========================================================================
    # GRÁFICO 2D INTERATIVO (DARK MODE) E SÍNTESE EXECUTIVA
    # =========================================================================
    col_grafico, col_resumo = st.columns([2.2, 1.1], gap="large")

    with col_grafico:
        figura_planta = construir_grafico_cobertura(projeto_fisico, captacao, descidas)
        st.plotly_chart(figura_planta, width="stretch", theme=None)

    with col_resumo:
        st.subheader("📐 Síntese Executiva")
        malha_max = captacao["dimensao_maxima_malha_m"]
        malha_proj = captacao["dimensao_projetada_malha_m"]
        linha_angulo = (
            f"- **Ângulo de Proteção ($\\alpha$):** `{captacao['angulo_protecao_graus']:.1f}°` (Figura 2 - NBR 5419-3)\n"
            if captacao.get("angulo_protecao_graus") is not None
            else ""
        )
        st.markdown(
            f"- **Método de Captação:** {captacao['metodo']}\n"
            f"{linha_angulo}"
            f"- **Arranjo / Vãos na Cobertura:** `{malha_proj[0]:.2f} m × {malha_proj[1]:.2f} m` "
            f"(máx. `{malha_max[0]:.0f}×{malha_max[1]:.0f} m` | `{captacao['metragem_estimada_laje_principal_m']:.1f} m` lineares)\n"
            f"- **Condutores Captores:** {captacao['condutor_recomendado']}\n"
            f"- **Aterramento:** `{aterramento['configuracao']}`\n"
            f"- **Fatores NBR 5419-2 Aplicados:** `rf={rf:.3g}` | `rp={rp:.2f}` | `Lf={lf:.3g}` | "
            f"`hz={resultado_r1.fatores_utilizados['hz']:.1f}`"
        )

        st.markdown("##### Decomposição do Risco $R_1$ (NBR 5419-2)")
        st.dataframe(
            [
                {"Parcela": "Ra (Choque - Estrutura)", "Valor (1/ano)": f"{resultado_r1.Ra:.3e}"},
                {"Parcela": "Rb (Dano Físico - Estrutura)", "Valor (1/ano)": f"{resultado_r1.Rb:.3e}"},
                {"Parcela": "Ru (Choque - Linhas)", "Valor (1/ano)": f"{resultado_r1.Ru:.3e}"},
                {"Parcela": "Rv (Dano Físico - Linhas)", "Valor (1/ano)": f"{resultado_r1.Rv:.3e}"},
                {"Parcela": "R1 Inicial (Sem SPDA/DPS)", "Valor (1/ano)": f"{decisao_risco['r1_inicial']:.3e}"},
                {"Parcela": f"R1 Mitigado (Nível {nivel_dimensionamento})", "Valor (1/ano)": f"{decisao_risco['r1_final']:.3e}"},
                {"Parcela": "Limite Tolerável (RT)", "Valor (1/ano)": f"{RISCO_TOLERAVEL_R1:.3e}"},
            ],
            width="stretch",
            hide_index=True,
        )

    # =========================================================================
    # PAINEL EXPANSÍVEL DE ALERTAS NORMATIVOS
    # =========================================================================
    altura_total = projeto_fisico.h_total
    possui_alerta_altura = altura_total > 20.0 or H > 20.0

    with st.expander(
        "⚠️ Painel de Alertas Normativos e Prescrições Executivas (ABNT NBR 5419-3 / 5419-4)",
        expanded=True,
    ):
        if possui_alerta_altura:
            altura_ref = H if lateral["exige_protecao_lateral"] else altura_total
            h_corte = lateral["h_corte_m"] if lateral["h_corte_m"] is not None else 0.8 * altura_ref
            extensao_faixa = altura_ref - h_corte

            qtd_aneis = int((altura_ref - 1e-9) // PASSO_ANEIS_CINTAMENTO_M)
            cotas_aneis = [
                PASSO_ANEIS_CINTAMENTO_M * idx for idx in range(1, qtd_aneis + 1)
            ]
            texto_aneis = (
                ", ".join(f"+{cota:.2f} m" for cota in cotas_aneis)
                if cotas_aneis
                else "+20.00 m (nível de transição superior)"
            )

            st.warning(
                f"**ALERTA OBRIGATÓRIO — EDIFICAÇÃO ELEVADA (Altura Total = {altura_total:.2f} m > 20 m):**\n\n"
                f"- **Proteção contra Descargas Laterais (20% superiores):** Obrigatória na fachada entre a "
                f"cota **+{h_corte:.2f} m** e **+{altura_ref:.2f} m** (extensão vertical protegida de "
                f"**{extensao_faixa:.2f} m**, além do volume superior até **+{altura_total:.2f} m**), "
                f"obedecendo ao reticulado máximo do **Nível {nivel_dimensionamento}** e equipotencializando "
                f"esquadrias/elementos metálicos externos.\n"
                f"- **Anéis Horizontais de Cintamento (a cada 20 m):** Instalar anéis horizontais "
                f"intermediários de equipotencialização nas cotas **{texto_aneis}**, interligando todas as "
                f"**{descidas['numero_minimo_descidas']} prumadas de descida**.",
                icon="🚨",
            )
        else:
            st.success(
                f"**Altura Total = {altura_total:.2f} m (≤ 20 m):** Edificação isenta da obrigatoriedade de "
                "captação lateral de fachada e de anéis horizontais intermediários de cintamento a cada 20 m.",
                icon="✅",
            )

        st.info(f"**Diretriz de Cobertura:** {captacao['malha_reservatorio']}", icon="🏠")
        st.info(f"**Diretriz de Descidas:** {descidas['especificacao']}", icon="⚡")

    with st.expander("📋 Visualizar Texto Completo do Relatório Técnico (NBR 5419-3)"):
        st.code(projeto_fisico.relatorio_tecnico(), language="text")


if __name__ == "__main__":
    main()
