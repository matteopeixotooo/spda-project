#!/usr/bin/env python3
"""Dimensionamento físico executivo universal de SPDA conforme a ABNT NBR 5419-3.

Suporta dinamicamente:
- Edifício Vertical (Concreto Armado / Laje Plana)
- Galpão Industrial / Comercial (Estrutura Metálica)
- Residência Unifamiliar (Alvenaria / Telhado Cerâmico)
- Estrutura Especial / Hospitalar
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

from risk_engine import (
    PERFIS_TIPOLOGIA,
    RISCO_TOLERAVEL_R1,
    TipologiaEdificacao,
    calcular_risco_r1,
    determinar_nivel_protecao,
    normalizar_nome_tipologia,
)

# ABNT NBR 5419-3, Tabela 2 - Raio da esfera rolante R por Nível de Proteção (m)
RAIO_ESFERA_ROLANTE_M: dict[str, float] = {
    "I": 20.0,
    "II": 30.0,
    "III": 45.0,
    "IV": 60.0,
}

# ABNT NBR 5419-3, Tabela 2 - Dimensões máximas da malha captora por Nível de Proteção (m)
DIMENSOES_MALHA_M: dict[str, tuple[float, float]] = {
    "I": (5.0, 5.0),
    "II": (10.0, 10.0),
    "III": (15.0, 15.0),
    "IV": (20.0, 20.0),
}

# ABNT NBR 5419-3, Tabela 4 - Espaçamento médio entre condutores de descida (m)
ESPACAMENTO_DESCIDAS_M: dict[str, float] = {
    "I": 10.0,
    "II": 10.0,
    "III": 15.0,
    "IV": 20.0,
}

# Limite de altura para exigência de anéis de cintamento e avaliação de descargas laterais (m)
ALTURA_LIMITE_LATERAL_M: float = 20.0
PASSO_ANEIS_CINTAMENTO_M: float = 20.0
ALTURA_LIMITE_RESIDENCIA_BAIXA_M: float = 10.0

# Mapeamento do tipo de cobertura padrão a partir da tipologia da edificação
TIPO_COBERTURA_POR_TIPOLOGIA: dict[str, str] = {
    TipologiaEdificacao.EDIFICIO_VERTICAL.value: "plana",
    TipologiaEdificacao.ESTRUTURA_ESPECIAL.value: "plana",
    TipologiaEdificacao.GALPAO_INDUSTRIAL.value: "metalica",
    TipologiaEdificacao.RESIDENCIA_UNIFAMILIAR.value: "ceramica",
}

# Pontos de referência (altura m -> ângulo graus) da Figura 2 da ABNT NBR 5419-3 até H = R
_CURVA_ANGULO_PROTECAO: dict[str, list[tuple[float, float]]] = {
    "I": [(2.0, 71.0), (5.0, 65.0), (10.0, 49.0), (15.0, 36.0), (20.0, 25.0)],
    "II": [
        (2.0, 74.0),
        (5.0, 72.0),
        (10.0, 62.0),
        (15.0, 51.0),
        (20.0, 43.0),
        (25.0, 32.0),
        (30.0, 25.0),
    ],
    "III": [
        (2.0, 77.0),
        (5.0, 76.0),
        (10.0, 69.0),
        (15.0, 61.0),
        (20.0, 55.0),
        (30.0, 40.0),
        (40.0, 29.0),
        (45.0, 25.0),
    ],
    "IV": [
        (2.0, 79.0),
        (5.0, 78.0),
        (10.0, 74.0),
        (15.0, 68.0),
        (20.0, 62.0),
        (30.0, 50.0),
        (40.0, 40.0),
        (50.0, 31.0),
        (60.0, 25.0),
    ],
}


def calcular_angulo_protecao_nbr5419(altura_m: float, nivel: str) -> float:
    """Interpola o ângulo de proteção alfa (graus) pela Figura 2 da ABNT NBR 5419-3."""
    pontos = _CURVA_ANGULO_PROTECAO[nivel]
    if altura_m <= pontos[0][0]:
        return pontos[0][1]
    if altura_m >= pontos[-1][0]:
        return pontos[-1][1]
    for (h0, a0), (h1, a1) in zip(pontos, pontos[1:]):
        if h0 <= altura_m <= h1:
            fator = (altura_m - h0) / (h1 - h0)
            return a0 + fator * (a1 - a0)
    return pontos[-1][1]


def avaliar_metodos_captacao(
    L: float,
    W: float,
    H: float,
    nivel_protecao: str,
    tipo_cobertura: str = "plana",
    *,
    possui_volumes_elevados: bool | None = None,
) -> dict[str, Any]:
    """Avalia e recomenda o método de captação conforme a ABNT NBR 5419-3 (Tabela 2 e item 5.2.2).

    Compara tecnicamente os três métodos reconhecidos pela norma:
    1. Método do Ângulo de Proteção (Captores Franklin);
    2. Método Eletrogeométrico (Esfera Rolante de raio R);
    3. Método das Malhas (Gaiola de Faraday).

    Args:
        L: Comprimento em planta da edificação (m).
        W: Largura em planta da edificação (m).
        H: Altura da edificação até o plano de cobertura principal (m).
        nivel_protecao: Nível de Proteção ('I', 'II', 'III' ou 'IV').
        tipo_cobertura: 'plana' (ou 'laje'), 'metalica' ou 'ceramica' (ou 'inclinada').
        possui_volumes_elevados: Indica presença de reservatório/ático/equipamentos no topo.

    Returns:
        Dicionário contendo parâmetros da Tabela 2, lista comparativa `metodos` e o veredito
        (`metodo_recomendado` e `parecer_tecnico`).
    """
    nivel = nivel_protecao.strip().upper()
    if nivel not in RAIO_ESFERA_ROLANTE_M:
        raise ValueError(
            f"Nível de proteção inválido: {nivel_protecao!r}. Use 'I', 'II', 'III' ou 'IV'."
        )
    if L <= 0 or W <= 0 or H <= 0:
        raise ValueError("As dimensões L, W e H devem ser maiores que zero.")

    cobertura_norm = tipo_cobertura.strip().lower()
    raio_esfera = RAIO_ESFERA_ROLANTE_M[nivel]
    malha_max_l, malha_max_w = DIMENSOES_MALHA_M[nivel]

    semidiagonal_m = 0.5 * math.hypot(L, W)
    modulos_l = math.ceil(L / malha_max_l)
    modulos_w = math.ceil(W / malha_max_w)
    dx = L / modulos_l
    dy = W / modulos_w

    # -------------------------------------------------------------------------
    # 1. Avaliação: Captores Franklin (Método do Ângulo de Proteção)
    # -------------------------------------------------------------------------
    if H >= raio_esfera:
        alfa_aprox: float | None = None
        raio_cone_solo: float | None = None
        h_mastro_est: float | None = None
        aplic_franklin = f"Inaplicável por Norma (H = {H:.1f} m ≥ Raio da Esfera R = {raio_esfera:.0f} m)"
        status_franklin = "Inaplicável"
        just_franklin = (
            f"Conforme Tabela 2 e Figura 2 da ABNT NBR 5419-3, o Método do Ângulo de Proteção "
            f"é normativamente inaplicável para a edificação como um todo quando H ≥ R "
            f"({H:.1f} m ≥ {raio_esfera:.0f} m no Nível {nivel}). Seu uso fica vedado para a "
            f"planta geral, admitindo-se apenas minicaptores locais tendo a própria cobertura "
            f"como plano de referência (h_local ≪ R)."
        )
    else:
        alfa_aprox = calcular_angulo_protecao_nbr5419(H, nivel)
        tan_alfa = math.tan(math.radians(alfa_aprox))
        raio_cone_solo = H * tan_alfa
        h_mastro_est = semidiagonal_m / tan_alfa

        mastro_desproporcional = (
            h_mastro_est > 5.0
            or (H + h_mastro_est) >= raio_esfera
            or max(L, W) > 25.0
            or (H > 15.0 and (L * W) > 160.0)
        )

        if mastro_desproporcional:
            aplic_franklin = "Desfavorável / Inviável para Coberturas Amplas"
            status_franklin = "Restrito"
            just_franklin = (
                f"Embora H = {H:.1f} m < R = {raio_esfera:.0f} m (ângulo α ≈ {alfa_aprox:.1f}°, "
                f"raio equivalente ao solo ≈ {raio_cone_solo:.1f} m), cobrir a diagonal da "
                f"planta de {L:.1f} × {W:.1f} m (semidiagonal = {semidiagonal_m:.1f} m) exigiria "
                f"mastros verticais desproporcionais (h_mastro ≈ {h_mastro_est:.1f} m), gerando "
                f"esforços mecânicos de vento e impacto arquitetônico inviáveis. Restrito apenas "
                f"à proteção localizada de pequenos elementos salientes no topo."
            )
        else:
            eh_inclinada = cobertura_norm in {"ceramica", "inclinada", "telhado"}
            aplic_franklin = (
                f"Favorável para Cobertura Compacta (α ≈ {alfa_aprox:.1f}°, mastro ~{h_mastro_est:.1f} m)"
            )
            status_franklin = "Recomendado" if eh_inclinada else "Restrito"
            just_franklin = (
                f"Com H = {H:.1f} m < R = {raio_esfera:.0f} m (Nível {nivel}), obtém-se ângulo "
                f"de proteção favorável α ≈ {alfa_aprox:.1f}° (raio de cone ≈ {raio_cone_solo:.1f} m; "
                f"elevação estimada de ~{h_mastro_est:.1f} m para cobrir semidiagonal de "
                f"{semidiagonal_m:.1f} m), viabilizando hastes Franklin e/ou cabo captor na cumeeira."
            )

    # -------------------------------------------------------------------------
    # 2. Avaliação: Método Eletrogeométrico (Esfera Rolante)
    # -------------------------------------------------------------------------
    if H > ALTURA_LIMITE_LATERAL_M:
        aplic_esfera = (
            f"Obrigatório p/ Verificação Geométrica e Impactos Laterais (H > 20 m; R = {raio_esfera:.0f} m)"
        )
        status_esfera = "Recomendado"
        just_esfera = (
            f"Método universal (NBR 5419-3, item 5.2.2) com esfera fictícia de raio "
            f"R = {raio_esfera:.0f} m (Nível {nivel}). Por possuir H = {H:.1f} m > 20 m, sua "
            f"aplicação é obrigatória na verificação de descargas laterais nos 20% superiores "
            f"da fachada (+{0.8 * H:.1f} m a +{H:.1f} m) e nas transições de volume do ático/reservatório."
        )
    else:
        aplic_esfera = f"Aplicável para Verificação Geométrica Complementar (R = {raio_esfera:.0f} m)"
        status_esfera = "Restrito"
        just_esfera = (
            f"Universalmente aceito pela NBR 5419-3 (item 5.2.2, R = {raio_esfera:.0f} m no "
            f"Nível {nivel}), porém como H = {H:.1f} m ≤ 20 m não há exigência de proteção "
            f"lateral de fachada, sendo utilizado de modo complementar para validar sombras de "
            f"proteção sobre equipamentos ou desníveis de cobertura."
        )

    # -------------------------------------------------------------------------
    # 3. Avaliação: Gaiola de Faraday (Método das Malhas)
    # -------------------------------------------------------------------------
    if cobertura_norm in {"plana", "laje"}:
        aplic_faraday = (
            f"Altamente Recomendado — Cobertura Plana ({modulos_l}×{modulos_w} módulos de {dx:.1f}×{dy:.1f} m)"
        )
        status_faraday = "Recomendado"
        just_faraday = (
            f"Solução preferencial da NBR 5419-3 (item 5.2.2-b e Tabela 2) para superfícies "
            f"planas e lajes: modulação calculada de {modulos_l}×{modulos_w} células "
            f"({dx:.2f} × {dy:.2f} m ≤ limite normativo de {malha_max_l:.0f} × {malha_max_w:.0f} m "
            f"do Nível {nivel}), assegurando baixa indutância, divisão da corrente entre as "
            f"descidas e proteção perimetral das platibandas."
        )
    elif cobertura_norm == "metalica":
        aplic_faraday = (
            f"Altamente Recomendado — Galpão Amplo ({modulos_l}×{modulos_w} vãos ou Telha Natural)"
        )
        status_faraday = "Recomendado"
        just_faraday = (
            f"Ideal para grandes coberturas metálicas ({L:.1f} × {W:.1f} m), permitindo "
            f"compor malha ≤ {malha_max_l:.0f} × {malha_max_w:.0f} m (Nível {nivel}) sobre "
            f"cumeeira/beirais ou homologar as próprias telhas metálicas contínuas como malha "
            f"captora natural desde que atendam à Tabela 3 da NBR 5419-3."
        )
    else:
        if status_franklin == "Recomendado":
            aplic_faraday = (
                f"Aplicável com Restrição Estética em Telhado Cerâmico ({modulos_l}×{modulos_w} vãos)"
            )
            status_faraday = "Restrito"
            just_faraday = (
                f"Atende tecnicamente à Tabela 2 (malha máx. {malha_max_l:.0f} × {malha_max_w:.0f} m), "
                f"mas em telhados cerâmicos compactos (H = {H:.1f} m) demanda fixação extensiva "
                f"de condutores sobre beirais e telhas, sendo menos enxuta que cabo na cumeeira / Franklin."
            )
        else:
            aplic_faraday = (
                f"Recomendado para Cobertura Inclinada Ampla ({modulos_l}×{modulos_w} vãos ≤ {malha_max_l:.0f}×{malha_max_w:.0f} m)"
            )
            status_faraday = "Recomendado"
            just_faraday = (
                f"Devido às dimensões da planta ({L:.1f} × {W:.1f} m), o fechamento em malha "
                f"sobre cumeeira, espigões e beirais ({dx:.2f} × {dy:.2f} m ≤ {malha_max_l:.0f} × "
                f"{malha_max_w:.0f} m) elimina a necessidade de mastros elevados."
            )

    # -------------------------------------------------------------------------
    # Veredito da Recomendação Técnica
    # -------------------------------------------------------------------------
    if possui_volumes_elevados is None:
        tem_volumes_topo = cobertura_norm in {"plana", "laje"}
    else:
        tem_volumes_topo = bool(possui_volumes_elevados)

    if cobertura_norm in {"ceramica", "inclinada", "telhado"} and status_franklin == "Recomendado":
        classificacao_veredito = "Franklin / Cabo Captor na Cumeeira (Método do Ângulo de Proteção)"
        parecer_veredito = (
            f"Recomenda-se o Método do Ângulo de Proteção (Captores Franklin / Cabo Captor na "
            f"Cumeeira, α ≈ {alfa_aprox:.1f}°), pois a edificação possui porte reduzido "
            f"(H = {H:.1f} m < R = {raio_esfera:.0f} m) e cobertura cerâmica compacta "
            f"({L:.1f} × {W:.1f} m), garantindo cobertura volumétrica integral sem mastros "
            f"desproporcionais e com mínima intervenção sobre o telhado."
        )
    elif cobertura_norm in {"plana", "laje"} and (tem_volumes_topo or H > ALTURA_LIMITE_LATERAL_M):
        classificacao_veredito = (
            "Método Misto (Gaiola de Faraday na Laje + Captores Pontuais nos Volumes Elevados)"
        )
        motivo_franklin = (
            f"inaplicável por norma (H = {H:.1f} m ≥ R = {raio_esfera:.0f} m)"
            if H >= raio_esfera
            else f"inviável isoladamente pela altura de mastro requerida (~{h_mastro_est:.1f} m)"
        )
        complemento_lateral = (
            f", combinada à verificação pela Esfera Rolante (R = {raio_esfera:.0f} m) e proteção "
            f"lateral nos 20% superiores da fachada (+{0.8 * H:.1f} m a +{H:.1f} m)"
            if H > ALTURA_LIMITE_LATERAL_M
            else f", validada geometricamente pela Esfera Rolante (R = {raio_esfera:.0f} m)"
        )
        parecer_veredito = (
            f"Recomenda-se a adoção do Método Misto conforme ABNT NBR 5419-3 (item 5.2.2 e "
            f"Tabela 2): o método de Franklin isolado é {motivo_franklin}; portanto, adota-se "
            f"Gaiola de Faraday na laje principal e na cobertura do reservatório ({modulos_l}×{modulos_w} "
            f"módulos de {dx:.2f}×{dy:.2f} m ≤ {malha_max_l:.0f}×{malha_max_w:.0f} m), associada a "
            f"captores verticais pontuais (Franklin local) para antenas, exaustores e saliências "
            f"no topo{complemento_lateral}."
        )
    else:
        classificacao_veredito = "Gaiola de Faraday (Método das Malhas)"
        parecer_veredito = (
            f"Recomenda-se o Método das Malhas (Gaiola de Faraday) respeitando o reticulado "
            f"máximo de {malha_max_l:.0f} × {malha_max_w:.0f} m da Tabela 2 da ABNT NBR 5419-3 "
            f"(Nível {nivel}, R = {raio_esfera:.0f} m), por cobrir uniformemente toda a "
            f"projeção de {L:.1f} × {W:.1f} m ({modulos_l}×{modulos_w} vãos de {dx:.2f}×{dy:.2f} m) "
            f"sem necessidade de mastros elevados e otimizando a divisão de corrente nas descidas."
        )

    metodos_comparados = [
        {
            "metodo": "Franklin (Ângulo de Proteção α)",
            "aplicabilidade": aplic_franklin,
            "status": status_franklin,
            "justificativa": just_franklin,
        },
        {
            "metodo": f"Esfera Rolante (R = {raio_esfera:.0f} m)",
            "aplicabilidade": aplic_esfera,
            "status": status_esfera,
            "justificativa": just_esfera,
        },
        {
            "metodo": f"Gaiola de Faraday (Malha ≤ {malha_max_l:.0f}×{malha_max_w:.0f} m)",
            "aplicabilidade": aplic_faraday,
            "status": status_faraday,
            "justificativa": just_faraday,
        },
    ]

    return {
        "nivel_protecao": nivel,
        "tipo_cobertura": cobertura_norm,
        "raio_esfera_m": raio_esfera,
        "malha_maxima_m": (malha_max_l, malha_max_w),
        "malha_projetada_m": (dx, dy),
        "modulos_LxW": (modulos_l, modulos_w),
        "angulo_alfa_graus": alfa_aprox,
        "raio_cobertura_solo_m": raio_cone_solo,
        "altura_mastro_estimada_m": h_mastro_est,
        "metodo_recomendado": classificacao_veredito,
        "parecer_tecnico": parecer_veredito,
        "metodos": metodos_comparados,
    }


class SpdaPhysicalDesign:
    """Dimensionador executivo universal do SPDA conforme a ABNT NBR 5419-3."""

    def __init__(
        self,
        nivel_protecao: str,
        L: float,
        W: float,
        H: float,
        h_caixa_dagua: float = 3.8,
        usa_descidas_naturais: bool | None = None,
        tipologia: str | TipologiaEdificacao = TipologiaEdificacao.EDIFICIO_VERTICAL,
    ) -> None:
        """Inicializa os parâmetros geométricos, construtivos e tipológicos do SPDA.

        Args:
            nivel_protecao: Nível de Proteção ('I', 'II', 'III' ou 'IV').
            L: Comprimento da edificação em metros.
            W: Largura da edificação em metros.
            H: Altura da cobertura principal / beiral em metros.
            h_caixa_dagua: Altura adicional do volume superior / cumeeira / reservatório em m.
            usa_descidas_naturais: Se None, adota a premissa normativa padrão da tipologia.
            tipologia: Tipologia da edificação conforme `TipologiaEdificacao`.
        """
        nivel_limpo = nivel_protecao.strip().upper()
        if nivel_limpo not in DIMENSOES_MALHA_M:
            raise ValueError(
                f"Nível de proteção inválido: {nivel_protecao!r}. "
                "Valores aceitos: 'I', 'II', 'III' ou 'IV'."
            )
        if L <= 0 or W <= 0 or H <= 0:
            raise ValueError("As dimensões L, W e H devem ser maiores que zero.")
        if h_caixa_dagua < 0:
            raise ValueError("A altura h_caixa_dagua não pode ser negativa.")

        self.tipologia: str = normalizar_nome_tipologia(tipologia)
        self.perfil_tipologia: dict[str, Any] = PERFIS_TIPOLOGIA[self.tipologia]

        if usa_descidas_naturais is None:
            descidas_nat = bool(self.perfil_tipologia["usa_descidas_naturais_padrao"])
        else:
            descidas_nat = bool(usa_descidas_naturais)

        self.nivel_protecao: str = nivel_limpo
        self.L: float = float(L)
        self.W: float = float(W)
        self.H: float = float(H)
        self.h_caixa_dagua: float = float(h_caixa_dagua)
        self.usa_descidas_naturais: bool = descidas_nat

        self.perimetro: float = 2.0 * (self.L + self.W)
        self.h_total: float = self.H + self.h_caixa_dagua

    @classmethod
    def a_partir_analise_risco(
        cls,
        L: float,
        W: float,
        H: float,
        Ng: float,
        h_caixa_dagua: float = 3.8,
        usa_descidas_naturais: bool | None = None,
        tipologia: str | TipologiaEdificacao = TipologiaEdificacao.EDIFICIO_VERTICAL,
        rt: float = RISCO_TOLERAVEL_R1,
        **kwargs_risco: Any,
    ) -> SpdaPhysicalDesign:
        """Instancia `SpdaPhysicalDesign` diretamente a partir do cálculo da NBR 5419-2."""
        resultado_r1 = calcular_risco_r1(
            L=L,
            W=W,
            H=H,
            Ng=Ng,
            tipologia=tipologia,
            **kwargs_risco,
        )
        decisao = determinar_nivel_protecao(resultado_r1, RT=rt)

        if not decisao["necessita_protecao"]:
            raise ValueError(
                f"R1 ({decisao['r1_inicial']:.4e}) <= RT ({rt:.4e}): "
                "SPDA dispensado pelo gerenciamento de risco."
            )
        nivel = "I" if not decisao["mitigado"] else str(decisao["nivel_protecao"])

        return cls(
            nivel_protecao=nivel,
            L=L,
            W=W,
            H=H,
            h_caixa_dagua=h_caixa_dagua,
            usa_descidas_naturais=usa_descidas_naturais,
            tipologia=tipologia,
        )

    def dimensionar_captacao(self) -> dict[str, Any]:
        """Seleciona e dimensiona dinamicamente o Subsistema de Captação conforme tipologia e H."""
        malha_max_l, malha_max_w = DIMENSOES_MALHA_M[self.nivel_protecao]
        modulos_l = math.ceil(self.L / malha_max_l)
        modulos_w = math.ceil(self.W / malha_max_w)
        espacamento_real_l = self.L / modulos_l
        espacamento_real_w = self.W / modulos_w
        condutores_transversais = modulos_l + 1
        condutores_longitudinais = modulos_w + 1
        comprimento_cabo_malha_m = (
            condutores_transversais * self.W + condutores_longitudinais * self.L
        )

        eh_residencia = self.tipologia == TipologiaEdificacao.RESIDENCIA_UNIFAMILIAR.value
        eh_galpao = self.tipologia == TipologiaEdificacao.GALPAO_INDUSTRIAL.value

        # CASO 1: Residência Unifamiliar Baixa (H <= 10 m) -> Cumeeira ou Hastes Franklin
        if eh_residencia and self.H <= ALTURA_LIMITE_RESIDENCIA_BAIXA_M:
            h_ref = self.h_total if self.h_caixa_dagua > 0 else self.H
            alfa_graus = calcular_angulo_protecao_nbr5419(h_ref, self.nivel_protecao)
            meia_largura = self.W / 2.0
            # Altura mínima de haste acima do beiral para cobrir meia largura W/2 pelo ângulo alfa
            h_captor_necessaria = meia_largura / math.tan(math.radians(alfa_graus))
            # Extensão estimada: cabo na cumeeira (L) + descidas pelas águas até os beirais
            qtd_travessas_aguas = max(2, math.ceil(self.L / malha_max_l) + 1)
            extensao_cumeeira_m = self.L + qtd_travessas_aguas * self.W

            especificacao_volume = (
                f"Estender cabo captor principal ao longo de toda a cumeeira ({self.L:.2f} m, "
                f"cota +{self.h_total:.2f} m) sobre espaçadores cerâmicos/poliméricos, ou "
                f"instalar hastes captoras Franklin dimensionadas pelo Método do Ângulo de "
                f"Proteção (α ≈ {alfa_graus:.1f}° p/ Nível {self.nivel_protecao} em H={h_ref:.1f} m; "
                f"elevação mínima acima do plano a proteger de {h_captor_necessaria:.2f} m para "
                f"cobrir W/2 = {meia_largura:.2f} m), interligando caixa d'água e antenas."
            )

            return {
                "tipo_captacao_codigo": "cumeeira_franklin",
                "metodo": (
                    "Cabo Captor na Cumeeira e/ou Captores Franklin "
                    "(Método do Ângulo de Proteção - ABNT NBR 5419-3, Tabela 2)"
                ),
                "angulo_protecao_graus": alfa_graus,
                "dimensao_maxima_malha_m": (malha_max_l, malha_max_w),
                "dimensao_projetada_malha_m": (espacamento_real_l, self.W / 2.0),
                "modulos_LxW": (modulos_l, 2),
                "condutores_longitudinais": 1,  # linha central de cumeeira
                "condutores_transversais": qtd_travessas_aguas,
                "metragem_estimada_laje_principal_m": extensao_cumeeira_m,
                "condutor_recomendado": (
                    "Cabo de cobre nu seção mínima 35 mm² (recomendado sobre telhado cerâmico "
                    "pela maleabilidade nos espigões/cumeeira) ou hastes Franklin de cobre/latão "
                    "Ø ≥ 16 mm (ABNT NBR 5419-3, Tabela 6)."
                ),
                "malha_reservatorio": especificacao_volume,
            }

        # CASO 2: Galpão Industrial / Comercial (Estrutura Metálica)
        if eh_galpao:
            # Cumeeira central + 2 beirais longitudinais + travessas de fechamento
            travessas_galpao = modulos_l + 1
            extensao_nao_natural_m = (3 * self.L) + (travessas_galpao * self.W)
            especificacao_galpao = (
                "1) Verificação como Captor Natural (ABNT NBR 5419-3, item 5.2.5 e Tabela 3): "
                "As telhas metálicas podem atuar como captor natural se houver continuidade "
                "elétrica permanente entre chapas, ausência de revestimento isolante e espessura "
                "mínima t' ≥ 0,5 mm (aço galvanizado) ou t' ≥ 0,65 mm (alumínio) quando não "
                "houver risco de perfuração/ignição sob a telha (ou t ≥ 4,0 mm aço / 7,0 mm Al "
                "se exigida proteção contra perfuração). "
                "2) Alternativa Dedicada: Caso a telha não atenda à espessura mínima (ex.: 0,43 mm) "
                "ou possua isolante termoacústico combustível, instalar condutores captores sobre "
                "a cumeeira central, beirais longitudinais e fechamentos transversais."
            )
            return {
                "tipo_captacao_codigo": "galpao_cumeeira_telha",
                "metodo": (
                    "Captação por Condutores na Cumeeira/Beirais ou Telha Metálica como "
                    "Captor Natural (ABNT NBR 5419-3, item 5.2.5 / Tabela 3)"
                ),
                "angulo_protecao_graus": None,
                "dimensao_maxima_malha_m": (malha_max_l, malha_max_w),
                "dimensao_projetada_malha_m": (espacamento_real_l, min(espacamento_real_w, self.W / 2.0)),
                "modulos_LxW": (modulos_l, max(2, modulos_w)),
                "condutores_longitudinais": max(3, condutores_longitudinais),
                "condutores_transversais": travessas_galpao,
                "metragem_estimada_laje_principal_m": extensao_nao_natural_m,
                "condutor_recomendado": (
                    "Telha metálica contínua homologada (Tabela 3: t' ≥ 0,5 mm aço / 0,65 mm Al) "
                    "ou condutores sobrepostos em barra chata de alumínio ≥ 70 mm² / cabo de "
                    "cobre nu ≥ 35 mm² (fixadores compatíveis com perfil trapezoidal/zipado)."
                ),
                "malha_reservatorio": especificacao_galpao,
            }

        # CASO 3: Edifício Vertical / Estrutura Especial / Residência com H > 10 m -> Malhas (Faraday)
        possui_volume_superior = self.h_caixa_dagua > 0
        especificacao_reservatorio = (
            f"Prever malha captora periférica independente na cobertura da casa de máquinas/"
            f"reservatório superior (cota +{self.h_total:.2f} m, elevação de {self.h_caixa_dagua:.2f} m "
            f"acima da laje principal), interligada à malha captora da laje principal (+{self.H:.2f} m) "
            f"por no mínimo 2 condutores de interligação/descida e equipotencializada às tubulações "
            f"metálicas e escadas de acesso."
            if possui_volume_superior
            else "Sem volume superior sobresalente informado (h_caixa_dagua = 0.00 m); manter malha "
            "periférica fechada em toda a platibanda da cobertura principal."
        )

        return {
            "tipo_captacao_codigo": "malha_faraday",
            "metodo": "Método das Malhas (Gaiola de Faraday) - ABNT NBR 5419-3, Tabela 2",
            "angulo_protecao_graus": None,
            "dimensao_maxima_malha_m": (malha_max_l, malha_max_w),
            "dimensao_projetada_malha_m": (espacamento_real_l, espacamento_real_w),
            "modulos_LxW": (modulos_l, modulos_w),
            "condutores_longitudinais": condutores_longitudinais,
            "condutores_transversais": condutores_transversais,
            "metragem_estimada_laje_principal_m": comprimento_cabo_malha_m,
            "condutor_recomendado": (
                "Barra chata de alumínio (mín. 70 mm², ex.: 25x3 mm ou 7/8\"x1/8\") "
                "ou cabo de cobre nu seção mínima 35 mm² (ABNT NBR 5419-3, Tabela 6)."
            ),
            "malha_reservatorio": especificacao_reservatorio,
        }

    def dimensionar_descidas(self) -> dict[str, Any]:
        """Dimensiona o Subsistema de Descidas adaptando as premissas construtivas à tipologia."""
        espacamento_normativo = ESPACAMENTO_DESCIDAS_M[self.nivel_protecao]
        descidas_pelo_perimetro = math.ceil(self.perimetro / espacamento_normativo)
        num_descidas = max(2, descidas_pelo_perimetro)
        espacamento_medio_efetivo = self.perimetro / num_descidas

        eh_galpao = self.tipologia == TipologiaEdificacao.GALPAO_INDUSTRIAL.value

        if self.usa_descidas_naturais and eh_galpao:
            especificacao_construtiva = (
                "Utilizar os próprios pilares/colunas estruturais metálicos do galpão como "
                "condutores de descida naturais (ABNT NBR 5419-3, item 5.3.5), garantindo "
                "continuidade elétrica vertical ≤ 0,2 Ohm entre tesouras/cobertura e chumbadores/"
                "fundação, prevendo conectores bimetálicos e pontos de ensaio junto à base."
            )
        elif self.usa_descidas_naturais:
            especificacao_construtiva = (
                "Utilizar as armaduras de aço estrutural dos pilares de concreto armado como "
                "condutores de descida naturais (ABNT NBR 5419-3, item 5.3.5), assegurando "
                "continuidade elétrica vertical <= 0,2 Ohm entre captação e fundação (via "
                "amarração/solda/conectores mecânicos em ao menos 50% das interseções ou barra "
                "dedicada de aço galvanizado/cobre interna ao pilar) e prevendo caixas de "
                "equalização/inspeção/ensaio no pavimento térreo conectadas ao anel/BEP."
            )
        else:
            especificacao_construtiva = (
                "Instalar condutores de descida externos aparentes (não estruturais) em cabo de "
                "cobre nu 35 mm² ou barra chata de alumínio 70 mm², distribuídos simetricamente "
                "pelo perímetro (priorizando os cantos vivos da edificação), dotados de conectores "
                "seccionáveis de medição/ensaio e eletroduto rígido de proteção mecânica até "
                "2,50 m acima do nível do piso acabado."
            )

        return {
            "perimetro_m": self.perimetro,
            "espacamento_normativo_m": espacamento_normativo,
            "descidas_calculadas_perimetro": descidas_pelo_perimetro,
            "numero_minimo_descidas": num_descidas,
            "espacamento_medio_efetivo_m": espacamento_medio_efetivo,
            "usa_descidas_naturais": self.usa_descidas_naturais,
            "especificacao": especificacao_construtiva,
        }

    def dimensionar_protecao_lateral_e_aneis(self) -> dict[str, Any]:
        """Avalia exigência de proteção contra descargas laterais e anéis a cada 20 m (H > 20 m)."""
        exige_protecao_lateral = self.H > ALTURA_LIMITE_LATERAL_M

        if not exige_protecao_lateral:
            return {
                "exige_protecao_lateral": False,
                "alerta": None,
                "h_corte_m": None,
                "faixa_superior_m": 0.0,
                "cotas_aneis_cintamento_m": [],
                "recomendacao": (
                    f"Estrutura com H = {self.H:.2f} m (<= {ALTURA_LIMITE_LATERAL_M:.0f} m): "
                    "isenta de proteção dedicada contra descargas laterais e de anéis "
                    "horizontais intermediários de cintamento."
                ),
            }

        h_corte = 0.8 * self.H
        faixa_protegida = self.H - h_corte

        quantidade_aneis = int((self.H - 1e-9) // PASSO_ANEIS_CINTAMENTO_M)
        cotas_aneis = [
            PASSO_ANEIS_CINTAMENTO_M * indice for indice in range(1, quantidade_aneis + 1)
        ]

        alerta = (
            f"[ALERTA NORMATIVO - H = {self.H:.2f} m > 20 m] Edificação sujeita a descargas "
            f"atmosféricas laterais! É obrigatória a proteção lateral da fachada nos 20% "
            f"superiores da altura: da cota H_corte = {h_corte:.2f} m até o topo H = {self.H:.2f} m "
            f"(faixa vertical superior de {faixa_protegida:.2f} m), atendendo às dimensões da "
            f"malha do Nível {self.nivel_protecao} e interligando elementos metálicos de fachada."
        )

        cotas_formatadas = ", ".join(f"+{cota:.2f} m" for cota in cotas_aneis)
        recomendacao = (
            f"Instalar anéis horizontais intermediários de cintamento/equipotencialização a cada "
            f"{PASSO_ANEIS_CINTAMENTO_M:.0f} m verticais (cotas: {cotas_formatadas}), "
            f"interligando todas as prumadas de descida (ou armaduras periféricas das vigas de "
            f"borda) para equalização de potencial e divisão da corrente de descarga."
        )

        return {
            "exige_protecao_lateral": True,
            "alerta": alerta,
            "h_corte_m": h_corte,
            "faixa_superior_m": faixa_protegida,
            "cotas_aneis_cintamento_m": cotas_aneis,
            "recomendacao": recomendacao,
        }

    def dimensionar_aterramento(self) -> dict[str, Any]:
        """Especifica o Subsistema de Aterramento conforme tipologia e ABNT NBR 5419-3 (Seção 5.4)."""
        eh_residencia = self.tipologia == TipologiaEdificacao.RESIDENCIA_UNIFAMILIAR.value

        if eh_residencia and not self.usa_descidas_naturais:
            return {
                "configuracao": "Eletrodo de aterramento Tipo B (anel externo enterrado ou fundação)",
                "eletrodo_natural": False,
                "especificacao": (
                    "Executar eletrodo de aterramento Tipo B em anel fechado de cabo de cobre nu "
                    "seção mínima 50 mm² enterrado a no mínimo 0,50 m de profundidade e afastado "
                    "cerca de 1,00 m das paredes externas (complementado por hastes cobreadas nas "
                    "descidas), ou aproveitar as armaduras das vigas baldrame se comprovadamente "
                    "contínuas (≤ 0,2 Ohm), interligando ao BEP e aos DPS do QDC."
                ),
            }

        return {
            "configuracao": "Eletrodo de aterramento Tipo B (em anel / malha de fundação)",
            "eletrodo_natural": True,
            "especificacao": (
                "Aproveitar as armaduras de aço interligadas das fundações de concreto armado "
                "(sapatas, blocos sobre estacas e vigas baldrame periféricas) como eletrodo "
                "natural de aterramento Tipo B (em anel), conforme ABNT NBR 5419-3 item 5.4.4. "
                "Garantir continuidade elétrica <= 0,2 Ohm e disponibilizar conexões para o "
                "BEP (Barramento de Equipotencialização Principal) e DPS de entrada."
            ),
        }

    def avaliar_captacao(self, tipo_cobertura: str | None = None) -> dict[str, Any]:
        """Executa `avaliar_metodos_captacao` com os dados da instância atual."""
        cobertura = (
            tipo_cobertura
            if tipo_cobertura is not None
            else TIPO_COBERTURA_POR_TIPOLOGIA.get(self.tipologia, "plana")
        )
        return avaliar_metodos_captacao(
            L=self.L,
            W=self.W,
            H=self.H,
            nivel_protecao=self.nivel_protecao,
            tipo_cobertura=cobertura,
            possui_volumes_elevados=(self.h_caixa_dagua > 0),
        )

    def relatorio_tecnico(self) -> str:
        """Gera texto executivo estruturado com todas as especificações calculadas."""
        avaliacao = self.avaliar_captacao()
        captacao = self.dimensionar_captacao()
        descidas = self.dimensionar_descidas()
        lateral = self.dimensionar_protecao_lateral_e_aneis()
        aterramento = self.dimensionar_aterramento()

        malha_max = captacao["dimensao_maxima_malha_m"]
        malha_proj = captacao["dimensao_projetada_malha_m"]
        modulos = captacao["modulos_LxW"]
        tipo_descida = (
            "Estrutural / Natural (pilares metálicos ou concreto armado)"
            if self.usa_descidas_naturais
            else "Externa Aparente / Não estrutural"
        )

        linhas = [
            "=" * 76,
            "  MEMORIAL EXECUTIVO DE DIMENSIONAMENTO DO SPDA - ABNT NBR 5419-3",
            "=" * 76,
            "1. DADOS DE ENTRADA, TIPOLOGIA E GEOMETRIA DA EDIFICAÇÃO",
            f"   - Tipologia construtiva           : {self.tipologia}",
            f"   - Nível de Proteção adotado (NP)  : Nível {self.nivel_protecao} (R = {avaliacao['raio_esfera_m']:.0f} m)",
            f"   - Dimensões em planta (L x W)     : {self.L:.2f} m x {self.W:.2f} m",
            f"   - Perímetro da projeção           : {self.perimetro:.2f} m",
            f"   - Altura principal (H)            : {self.H:.2f} m",
            f"   - Elevação complementar / ático   : {self.h_caixa_dagua:.2f} m (Cota topo: +{self.h_total:.2f} m)",
            f"   - Concepção das descidas          : {tipo_descida}",
            "",
            f"2. SUBSISTEMA DE CAPTAÇÃO ({captacao['metodo'].upper()})",
            f"   - Solução recomendada (Tab. 2)    : {avaliacao['metodo_recomendado']}",
            f"   - Parecer técnico                 : {avaliacao['parecer_tecnico']}",
            f"   - Parâmetro normativo (Nível {self.nivel_protecao:<2}) : Malha máx. {malha_max[0]:.0f} m x {malha_max[1]:.0f} m"
            + (
                f" | Ângulo α ≈ {captacao['angulo_protecao_graus']:.1f}°"
                if captacao["angulo_protecao_graus"] is not None
                else ""
            ),
            f"   - Arranjo / modulação adotada     : {modulos[0]} x {modulos[1]} vãos ({malha_proj[0]:.2f} m x {malha_proj[1]:.2f} m)",
            f"   - Extensão estimada de condutores : {captacao['metragem_estimada_laje_principal_m']:.2f} m lineares",
            f"   - Especificação de condutores     : {captacao['condutor_recomendado']}",
            f"   - Diretriz específica cobertura   : {captacao['malha_reservatorio']}",
            "",
            "3. SUBSISTEMA DE DESCIDAS",
            f"   - Espaçamento médio normativo     : {descidas['espacamento_normativo_m']:.0f} m (Nível {self.nivel_protecao})",
            f"   - Cálculo pelo perímetro          : ceil({self.perimetro:.2f} / {descidas['espacamento_normativo_m']:.0f}) = "
            f"{descidas['numero_minimo_descidas']} descidas mínimas",
            f"   - Espaçamento médio efetivo       : {descidas['espacamento_medio_efetivo_m']:.2f} m",
            f"   - Diretriz executiva              : {descidas['especificacao']}",
            "",
            "4. ANÉIS DE EQUALIZAÇÃO E PROTEÇÃO CONTRA DESCARGAS LATERAIS",
        ]

        if lateral["exige_protecao_lateral"]:
            linhas.append(f"   - {lateral['alerta']}")
            linhas.append(
                f"   - Zona de proteção lateral (20%)  : De H_corte = +{lateral['h_corte_m']:.2f} m "
                f"até H = +{self.H:.2f} m ({lateral['faixa_superior_m']:.2f} m superiores)"
            )
            linhas.append(f"   - Cintamento horizontal (a cada 20m): {lateral['recomendacao']}")
        else:
            linhas.append(f"   - Situação normativa              : {lateral['recomendacao']}")

        linhas.extend(
            [
                "",
                "5. SUBSISTEMA DE ATERRAMENTO E EQUIPOTENCIALIZAÇÃO",
                f"   - Arranjo normativo               : {aterramento['configuracao']}",
                f"   - Diretriz executiva              : {aterramento['especificacao']}",
                "=" * 76,
            ]
        )

        return "\n".join(linhas)


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dimensionamento executivo universal do SPDA conforme a ABNT NBR 5419-3. "
            "Informe -Nivel (I, II, III, IV) ou --ng para obter o nível via risk_engine.py."
        )
    )
    parser.add_argument("-L", "--comprimento", type=float, required=True, help="Comprimento L (m)")
    parser.add_argument("-W", "--largura", type=float, required=True, help="Largura W (m)")
    parser.add_argument("-H", "--altura", type=float, required=True, help="Altura H (m)")
    parser.add_argument(
        "-Nivel",
        "--nivel",
        "-N",
        dest="nivel",
        type=str,
        help="Nível de Proteção do SPDA ('I', 'II', 'III' ou 'IV')",
    )
    parser.add_argument(
        "-Ng",
        "--ng",
        dest="ng",
        type=float,
        help="Densidade Ng (descargas/km²/ano) para calcular automaticamente o Nível via risk_engine",
    )
    parser.add_argument(
        "-T",
        "--tipologia",
        type=str,
        default=TipologiaEdificacao.EDIFICIO_VERTICAL.value,
        help="Tipologia da edificação",
    )
    parser.add_argument(
        "--h-caixa-dagua",
        type=float,
        default=3.8,
        help="Altura adicional do reservatório/cumeeira/ático (padrão: 3.8 m)",
    )
    parser.add_argument(
        "--descidas-externas",
        action="store_true",
        help="Força condutores de descida externos aparentes (usa_descidas_naturais=False)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada CLI do dimensionador físico NBR 5419-3."""
    parser = _construir_parser()
    args = parser.parse_args(argv)

    usa_naturais = False if args.descidas_externas else None

    try:
        if args.nivel is not None:
            projeto = SpdaPhysicalDesign(
                nivel_protecao=args.nivel,
                L=args.comprimento,
                W=args.largura,
                H=args.altura,
                h_caixa_dagua=args.h_caixa_dagua,
                usa_descidas_naturais=usa_naturais,
                tipologia=args.tipologia,
            )
        elif args.ng is not None:
            projeto = SpdaPhysicalDesign.a_partir_analise_risco(
                L=args.comprimento,
                W=args.largura,
                H=args.altura,
                Ng=args.ng,
                h_caixa_dagua=args.h_caixa_dagua,
                usa_descidas_naturais=usa_naturais,
                tipologia=args.tipologia,
            )
        else:
            parser.error("Informe -Nivel (I, II, III, IV) ou --ng para cálculo automático via NBR 5419-2.")

        print(projeto.relatorio_tecnico())
        return 0
    except ValueError as exc:
        print(f"Erro no dimensionamento: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
