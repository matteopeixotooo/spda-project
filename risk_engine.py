#!/usr/bin/env python3
"""Motor de cálculo para Gerenciamento de Risco de SPDA conforme a ABNT NBR 5419-2.

Atende de forma universal múltiplas tipologias de edificações isoladas:
- Edifício Vertical (Concreto Armado / Laje Plana)
- Galpão Industrial / Comercial (Estrutura Metálica)
- Residência Unifamiliar (Alvenaria / Telhado Cerâmico)
- Estrutura Especial / Hospitalar
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import Enum
import math
import sys
from typing import Any

# Risco tolerável padrão para perda de vida humana (ABNT NBR 5419-2, Tabela 4)
RISCO_TOLERAVEL_R1: float = 1e-5

# Ordem normativa de iteração dos Níveis de Proteção (do menos rigoroso ao mais rigoroso)
ORDEM_NIVEIS_PROTECAO: tuple[str, ...] = ("IV", "III", "II", "I")


class TipologiaEdificacao(str, Enum):
    """Tipologias construtivas e de ocupação suportadas pelo sistema."""

    EDIFICIO_VERTICAL = "Edifício Vertical (Concreto Armado / Laje Plana)"
    GALPAO_INDUSTRIAL = "Galpão Industrial / Comercial (Estrutura Metálica)"
    RESIDENCIA_UNIFAMILIAR = "Residência Unifamiliar (Alvenaria / Telhado Cerâmico)"
    ESTRUTURA_ESPECIAL = "Estrutura Especial / Hospitalar"


# Parâmetros normativos padrão (ABNT NBR 5419-2, Anexo C) e premissas geométricas por tipologia
PERFIS_TIPOLOGIA: dict[str, dict[str, Any]] = {
    TipologiaEdificacao.EDIFICIO_VERTICAL.value: {
        "codigo": "edificio_vertical",
        "tipo_construcao": "Estrutura de concreto armado com cobertura em laje plana",
        "rf": 1e-2,       # Tabela C.5: Risco de incêndio ordinário
        "rp": 0.5,        # Tabela C.4: Extintores manuais / hidrantes
        "lf": 2e-2,       # Tabela C.2: Edificação multipavimentos / uso misto-residencial
        "hz": 1.0,        # Tabela C.6: Sem perigo especial
        "rt_piso": 1e-2,  # Tabela C.3: Concreto / cerâmica na área externa/térreo
        "pta": 1.0,       # Tabela B.1: Sem medidas adicionais de isolação externa
        # Premissas geométricas e construtivas sugeridas para a interface
        "L_padrao": 24.0,
        "W_padrao": 18.0,
        "H_padrao": 49.0,
        "h_caixa_padrao": 3.8,
        "Ng_padrao": 2.5,
        "usa_descidas_naturais_padrao": True,
        "justificativa_normativa": (
            "Edificação vertical em concreto armado: adota-se captação por Gaiola de Faraday "
            "na cobertura plana, aproveitamento das armaduras contínuas dos pilares como "
            "descidas naturais (NBR 5419-3, item 5.3.5) e, para H > 20 m, anéis horizontais "
            "a cada 20 m com proteção contra descargas laterais nos 20% superiores."
        ),
    },
    TipologiaEdificacao.GALPAO_INDUSTRIAL.value: {
        "codigo": "galpao_industrial",
        "tipo_construcao": "Estrutura metálica aporticada com cobertura em telhas metálicas",
        "rf": 1e-2,       # Tabela C.5: Risco de incêndio ordinário (ajustável p/ 0.1 se carga alta)
        "rp": 0.5,        # Tabela C.4: Hidrantes e extintores manuais
        "lf": 2e-2,       # Tabela C.2: Edificação industrial ou comercial
        "hz": 2.0,        # Tabela C.6: Baixo nível de pânico (ocupação fabril/logística)
        "rt_piso": 1e-2,  # Tabela C.3: Piso industrial de concreto armado (<= 1 kOhm.m)
        "pta": 1.0,       # Tabela B.1: Conservador (1.0) sem isolação externa das colunas
        "L_padrao": 60.0,
        "W_padrao": 30.0,
        "H_padrao": 9.0,
        "h_caixa_padrao": 0.0,
        "Ng_padrao": 4.0,
        "usa_descidas_naturais_padrao": True,
        "justificativa_normativa": (
            "Galpão industrial/comercial metálico: permite avaliar as telhas metálicas da "
            "cobertura como captor natural (desde que atendida a espessura mínima da Tabela 3 "
            "da NBR 5419-3: >= 0,5 mm aço / >= 0,65 mm Al sem risco de ignição interna, ou "
            "cabo captor na cumeeira e beirais) e utiliza os próprios pilares metálicos "
            "estruturais como descidas naturais contínuas."
        ),
    },
    TipologiaEdificacao.RESIDENCIA_UNIFAMILIAR.value: {
        "codigo": "residencia_unifamiliar",
        "tipo_construcao": "Alvenaria convencional com madeiramento e telhado cerâmico",
        "rf": 1e-2,       # Tabela C.5: Risco de incêndio ordinário
        "rp": 1.0,        # Tabela C.4: Sem sistema fixo de combate a incêndio
        "lf": 1e-2,       # Tabela C.2: Residência unifamiliar
        "hz": 1.0,        # Tabela C.6: Sem dificuldade de evacuação
        "rt_piso": 1e-3,  # Tabela C.3: Piso cerâmico / madeira (1 a 10 kOhm.m)
        "pta": 1.0,
        "L_padrao": 15.0,
        "W_padrao": 10.0,
        "H_padrao": 6.0,
        "h_caixa_padrao": 1.5,
        "Ng_padrao": 6.0,
        "usa_descidas_naturais_padrao": False,
        "justificativa_normativa": (
            "Residência unifamiliar baixa (H <= 10 m) em alvenaria e telhado cerâmico: como "
            "não há garantia de continuidade estrutural de pilares, recomendam-se cabo captor "
            "sobre a cumeeira e/ou hastes Franklin (Método do Ângulo de Proteção da NBR 5419-3) "
            "associados a condutores de descida externos aparentes."
        ),
    },
    TipologiaEdificacao.ESTRUTURA_ESPECIAL.value: {
        "codigo": "estrutura_especial",
        "tipo_construcao": "Concreto armado especial / unidade hospitalar de assistência crítica",
        "rf": 1e-2,       # Tabela C.5: Incêndio ordinário (0.1 se áreas com gases/inflamáveis)
        "rp": 0.5,        # Tabela C.4: Hidrantes/brigada (0.2 se sprinklers em toda a planta)
        "lf": 1e-1,       # Tabela C.2: Hospital / escola / edifício cívico (10^-1)
        "hz": 5.0,        # Tabela C.6: Dificuldade de evacuação (pacientes acamados/UTI)
        "rt_piso": 1e-2,  # Tabela C.3: Concreto / piso condutivo hospitalar
        "pta": 1.0,
        "L_padrao": 45.0,
        "W_padrao": 25.0,
        "H_padrao": 24.0,
        "h_caixa_padrao": 4.0,
        "Ng_padrao": 4.0,
        "usa_descidas_naturais_padrao": True,
        "justificativa_normativa": (
            "Estrutura especial / hospitalar (NBR 5419-2, Tabelas C.2 e C.6: Lf = 0,10 e "
            "hz = 5,0 por dificuldade de evacuação de pacientes): demanda rigor máximo no "
            "SPDA (malha Gaiola de Faraday estreita, tipicamente Nível I), descidas estruturais "
            "equipotencializadas e coordenação estrita de DPS/ZPRs conforme NBR 5419-4."
        ),
    },
}

LISTA_TIPOLOGIAS: tuple[str, ...] = tuple(PERFIS_TIPOLOGIA.keys())

# Tabela A.1 - Fator de localização da estrutura (Cd)
FATORES_CD: dict[str, float] = {
    "cercada_mais_altos": 0.25,
    "cercada_mesma_altura_ou_menores": 0.50,
    "isolada": 1.00,
    "isolada_topo_colina": 2.00,
}

# Tabela B.2 - Probabilidade PB de dano físico à estrutura em função do NP do SPDA
PROBABILIDADE_PB: dict[str | None, float] = {
    None: 1.00,
    "IV": 0.20,
    "III": 0.10,
    "II": 0.05,
    "I": 0.02,
}

# Tabela B.3 / B.7 - Probabilidade PEB (DPS coordenado na entrada) em função do NP
PROBABILIDADE_PEB: dict[str | None, float] = {
    None: 1.00,
    "IV": 0.05,
    "III": 0.05,
    "II": 0.02,
    "I": 0.01,
}

# Tabela A.2 - Fator de instalação da linha (Ci)
FATORES_CI: dict[str, float] = {
    "aerea": 1.00,
    "enterrada": 0.50,
    "enterrada_malha": 0.01,
}

# Tabela A.3 - Fator de tipo de linha (Ct)
FATORES_CT: dict[str, float] = {
    "energia_bt": 1.00,
    "sinal": 1.00,
    "energia_at_com_trafo": 0.20,
}

# Tabela A.4 - Fator ambiental da linha (Ce)
FATORES_CE: dict[str, float] = {
    "rural": 1.00,
    "suburbano": 0.50,
    "urbano": 0.10,
    "urbano_edificios_altos": 0.01,
}


def obter_perfil_tipologia(
    tipologia: str | TipologiaEdificacao | None = None,
) -> dict[str, Any]:
    """Retorna o dicionário de parâmetros normativos para a tipologia informada."""
    if tipologia is None:
        chave = TipologiaEdificacao.EDIFICIO_VERTICAL.value
    elif isinstance(tipologia, TipologiaEdificacao):
        chave = tipologia.value
    else:
        chave = str(tipologia).strip()

    if chave in PERFIS_TIPOLOGIA:
        return dict(PERFIS_TIPOLOGIA[chave])

    # Busca flexível por código ou prefixo caso informado via CLI
    chave_lower = chave.lower()
    for nome_oficial, perfil in PERFIS_TIPOLOGIA.items():
        if chave_lower == perfil["codigo"] or chave_lower in nome_oficial.lower():
            retorno = dict(perfil)
            retorno["nome_oficial"] = nome_oficial
            return retorno

    raise ValueError(
        f"Tipologia desconhecida: {tipologia!r}. Opções válidas: {list(LISTA_TIPOLOGIAS)}"
    )


def normalizar_nome_tipologia(tipologia: str | TipologiaEdificacao | None = None) -> str:
    """Normaliza uma string/Enum de tipologia para o rótulo canônico oficial."""
    if tipologia is None:
        return TipologiaEdificacao.EDIFICIO_VERTICAL.value
    if isinstance(tipologia, TipologiaEdificacao):
        return tipologia.value
    chave = str(tipologia).strip()
    if chave in PERFIS_TIPOLOGIA:
        return chave
    chave_lower = chave.lower()
    for nome_oficial, perfil in PERFIS_TIPOLOGIA.items():
        if chave_lower == perfil["codigo"] or chave_lower in nome_oficial.lower():
            return nome_oficial
    raise ValueError(
        f"Tipologia desconhecida: {tipologia!r}. Opções válidas: {list(LISTA_TIPOLOGIAS)}"
    )


@dataclass(frozen=True)
class LinhaConectada:
    """Representa uma linha externa (energia ou sinal/telecom) conectada à estrutura."""

    nome: str = "energia"
    comprimento_m: float = 1000.0
    ci: float = 1.0
    ce: float = 0.5
    ct: float = 1.0
    ptu: float = 1.0
    peb: float = 1.0
    pld: float = 1.0
    cld: float = 1.0
    ndj: float = 0.0


@dataclass(frozen=True)
class ResultadoR1:
    """Resultado detalhado do cálculo do Risco R1 (perda de vida humana)."""

    Ad: float
    Nd: float
    Ra: float
    Rb: float
    Ru: float
    Rv: float
    R1: float
    nivel_aplicado: str | None = None
    tipologia: str = TipologiaEdificacao.EDIFICIO_VERTICAL.value
    tipo_construcao: str = PERFIS_TIPOLOGIA[TipologiaEdificacao.EDIFICIO_VERTICAL.value][
        "tipo_construcao"
    ]
    fatores_utilizados: dict[str, float] = field(default_factory=dict)
    detalhes_linhas: dict[str, dict[str, float]] = field(default_factory=dict)
    # Componentes base sem SPDA/DPS (PB=1.0, PEB=1.0) para reavaliação por nível de proteção
    _ra_base: float = 0.0
    _rb_base: float = 0.0
    _ru_base: float = 0.0
    _rv_base: float = 0.0


def calcular_area_exposicao(L: float, W: float, H: float) -> float:
    """Calcula a Área de Exposição Equivalente (Ad) para estrutura retangular isolada.

    Equação (ABNT NBR 5419-2, A.2.1.1):
        Ad = L * W + 2 * (L + W) * 3 * H + pi * (3 * H)^2
    """
    if L <= 0 or W <= 0 or H <= 0:
        raise ValueError("As dimensões L, W e H devem ser maiores que zero.")

    tres_h = 3.0 * H
    return (L * W) + (2.0 * (L + W) * tres_h) + (math.pi * (tres_h**2))


def calcular_eventos_diretos(Ng: float, Ad: float, Cd: float = 1.0) -> float:
    """Calcula o número anual médio de eventos perigosos diretos na estrutura (Nd).

    Equação (ABNT NBR 5419-2, A.2.4):
        Nd = Ng * Ad * Cd * 10^-6
    """
    if Ng < 0:
        raise ValueError("A densidade de descargas Ng não pode ser negativa.")
    if Ad < 0:
        raise ValueError("A área de exposição Ad não pode ser negativa.")
    if Cd <= 0:
        raise ValueError("O fator de localização Cd deve ser maior que zero.")

    return Ng * Ad * Cd * 1e-6


def calcular_eventos_linha(
    Ng: float,
    Ll: float = 1000.0,
    Ci: float = 1.0,
    Ce: float = 0.5,
    Ct: float = 1.0,
) -> float:
    """Calcula o número anual de eventos perigosos devido a descargas na linha (Nl)."""
    if Ng < 0 or Ll < 0 or Ci < 0 or Ce < 0 or Ct < 0:
        raise ValueError("Os parâmetros da linha e Ng não podem ser negativos.")

    al = 40.0 * Ll
    return Ng * al * Ci * Ce * Ct * 1e-6


def calcular_ra(Nd: float, Pa: float, La: float) -> float:
    """Calcula o componente Ra (choque elétrico por tensão de toque/passo na estrutura)."""
    return Nd * Pa * La


def calcular_rb(Nd: float, Pb: float, Lb: float) -> float:
    """Calcula o componente Rb (dano físico por incêndio/explosão devido a descarga direta)."""
    return Nd * Pb * Lb


def calcular_ru(Nl: float, Pu: float, Lu: float, Ndj: float = 0.0) -> float:
    """Calcula o componente Ru (choque elétrico devido a descargas em linha conectada)."""
    return (Nl + Ndj) * Pu * Lu


def calcular_rv(Nl: float, Pv: float, Lv: float, Ndj: float = 0.0) -> float:
    """Calcula o componente Rv (dano físico por incêndio/explosão via linha conectada)."""
    return (Nl + Ndj) * Pv * Lv


def calcular_risco_r1(
    L: float,
    W: float,
    H: float,
    Ng: float,
    Cd: float = 1.0,
    *,
    tipologia: str | TipologiaEdificacao | None = None,
    nivel_protecao: str | None = None,
    pta: float | None = None,
    rt_piso: float | None = None,
    lt: float = 1e-2,
    rp: float | None = None,
    rf: float | None = None,
    hz: float | None = None,
    lf: float | None = None,
    fator_ocupacao: float = 1.0,
    linhas: list[LinhaConectada] | None = None,
) -> ResultadoR1:
    """Calcula o Risco R1 (perda de vida humana) vinculando fatores padrão à tipologia.

    Os fatores `rf`, `rp`, `lf`, `hz`, `rt_piso` e `pta` assumem automaticamente os
    padrões normativos da `tipologia` escolhida (ABNT NBR 5419-2), podendo ser
    sobrescritos individualmente pelo usuário quando informados explicitamente.
    """
    if nivel_protecao not in PROBABILIDADE_PB:
        raise ValueError(
            f"Nível de proteção inválido: {nivel_protecao!r}. "
            "Use None, 'IV', 'III', 'II' ou 'I'."
        )
    if not (0.0 <= fator_ocupacao <= 1.0):
        raise ValueError("O fator_ocupacao deve estar entre 0.0 e 1.0.")

    nome_tipologia = normalizar_nome_tipologia(tipologia)
    perfil = PERFIS_TIPOLOGIA[nome_tipologia]

    pta_ef = float(perfil["pta"] if pta is None else pta)
    rt_piso_ef = float(perfil["rt_piso"] if rt_piso is None else rt_piso)
    rp_ef = float(perfil["rp"] if rp is None else rp)
    rf_ef = float(perfil["rf"] if rf is None else rf)
    hz_ef = float(perfil["hz"] if hz is None else hz)
    lf_ef = float(perfil["lf"] if lf is None else lf)

    ad = calcular_area_exposicao(L, W, H)
    nd = calcular_eventos_diretos(Ng, ad, Cd=Cd)

    pb = PROBABILIDADE_PB[nivel_protecao]
    peb_nivel = PROBABILIDADE_PEB[nivel_protecao]

    # Perdas relativas (Seção C.3 da ABNT NBR 5419-2)
    la = rt_piso_ef * lt * fator_ocupacao
    lb = rp_ef * rf_ef * hz_ef * lf_ef * fator_ocupacao
    lu = la
    lv = lb

    # Componentes devido a descargas diretas na estrutura (S1)
    ra_base = calcular_ra(nd, pta_ef * 1.0, la)
    rb_base = calcular_rb(nd, 1.0, lb)
    ra = ra_base * pb
    rb = rb_base * pb

    # Linhas conectadas padrão (energia + sinal) caso None
    if linhas is None:
        linhas_avaliadas = [
            LinhaConectada(nome="energia", comprimento_m=500.0, ci=1.0, ce=0.5, ct=1.0),
            LinhaConectada(nome="sinal", comprimento_m=500.0, ci=0.5, ce=0.5, ct=1.0),
        ]
    else:
        linhas_avaliadas = linhas

    ru_total = 0.0
    rv_total = 0.0
    ru_base_total = 0.0
    rv_base_total = 0.0
    detalhes_linhas: dict[str, dict[str, float]] = {}

    for linha in linhas_avaliadas:
        nl = calcular_eventos_linha(
            Ng=Ng,
            Ll=linha.comprimento_m,
            Ci=linha.ci,
            Ce=linha.ce,
            Ct=linha.ct,
        )
        peb_efetivo = peb_nivel if nivel_protecao is not None else linha.peb

        pu_base = linha.ptu * 1.0 * linha.pld * linha.cld
        pv_base = 1.0 * linha.pld * linha.cld

        ru_linha_base = calcular_ru(nl, pu_base, lu, Ndj=linha.ndj)
        rv_linha_base = calcular_rv(nl, pv_base, lv, Ndj=linha.ndj)

        ru_linha = ru_linha_base * peb_efetivo
        rv_linha = rv_linha_base * peb_efetivo

        ru_base_total += ru_linha_base
        rv_base_total += rv_linha_base
        ru_total += ru_linha
        rv_total += rv_linha

        detalhes_linhas[linha.nome] = {
            "Nl": nl,
            "Ru": ru_linha,
            "Rv": rv_linha,
        }

    r1_total = ra + rb + ru_total + rv_total

    return ResultadoR1(
        Ad=ad,
        Nd=nd,
        Ra=ra,
        Rb=rb,
        Ru=ru_total,
        Rv=rv_total,
        R1=r1_total,
        nivel_aplicado=nivel_protecao,
        tipologia=nome_tipologia,
        tipo_construcao=str(perfil["tipo_construcao"]),
        fatores_utilizados={
            "rf": rf_ef,
            "rp": rp_ef,
            "lf": lf_ef,
            "hz": hz_ef,
            "rt_piso": rt_piso_ef,
            "pta": pta_ef,
        },
        detalhes_linhas=detalhes_linhas,
        _ra_base=ra_base,
        _rb_base=rb_base,
        _ru_base=ru_base_total,
        _rv_base=rv_base_total,
    )


def determinar_nivel_protecao(
    R1: float | ResultadoR1,
    RT: float = RISCO_TOLERAVEL_R1,
) -> dict[str, Any]:
    """Avalia se R1 <= RT e, caso contrário, itera entre os Níveis IV, III, II e I."""
    if RT <= 0:
        raise ValueError("O risco tolerável RT deve ser maior que zero.")

    usa_decomposicao = isinstance(R1, ResultadoR1)
    r1_inicial = R1.R1 if usa_decomposicao else float(R1)

    if r1_inicial < 0:
        raise ValueError("O risco R1 não pode ser negativo.")

    if r1_inicial <= RT:
        return {
            "necessita_protecao": False,
            "mitigado": True,
            "nivel_protecao": None,
            "r1_inicial": r1_inicial,
            "r1_final": r1_inicial,
            "rt": RT,
            "iteracoes": [],
        }

    iteracoes: list[dict[str, Any]] = []
    r1_calculado = r1_inicial

    for nivel in ORDEM_NIVEIS_PROTECAO:
        pb = PROBABILIDADE_PB[nivel]
        peb = PROBABILIDADE_PEB[nivel]

        if usa_decomposicao:
            ra_np = R1._ra_base * pb
            rb_np = R1._rb_base * pb
            ru_np = R1._ru_base * peb
            rv_np = R1._rv_base * peb
            r1_calculado = ra_np + rb_np + ru_np + rv_np
            passo = {
                "nivel": nivel,
                "PB": pb,
                "PEB": peb,
                "Ra": ra_np,
                "Rb": rb_np,
                "Ru": ru_np,
                "Rv": rv_np,
                "R1": r1_calculado,
                "atende_RT": r1_calculado <= RT,
            }
        else:
            r1_calculado = r1_inicial * pb
            passo = {
                "nivel": nivel,
                "PB": pb,
                "R1": r1_calculado,
                "atende_RT": r1_calculado <= RT,
            }

        iteracoes.append(passo)

        if r1_calculado <= RT:
            return {
                "necessita_protecao": True,
                "mitigado": True,
                "nivel_protecao": nivel,
                "r1_inicial": r1_inicial,
                "r1_final": r1_calculado,
                "rt": RT,
                "iteracoes": iteracoes,
            }

    return {
        "necessita_protecao": True,
        "mitigado": False,
        "nivel_protecao": "Medidas adicionais além do Nível I",
        "r1_inicial": r1_inicial,
        "r1_final": r1_calculado,
        "rt": RT,
        "iteracoes": iteracoes,
    }


def _ler_float_interativo(mensagem: str, padrao: float) -> float:
    """Lê um float do terminal usando valor padrão caso o usuário pressione Enter."""
    try:
        texto = input(f"{mensagem} [{padrao}]: ").strip()
    except EOFError:
        return padrao
    if not texto:
        return padrao
    return float(texto.replace(",", "."))


def _ler_bool_interativo(mensagem: str, padrao: bool = True) -> bool:
    """Lê uma confirmação S/N do terminal."""
    sufixo = "S/n" if padrao else "s/N"
    try:
        texto = input(f"{mensagem} [{sufixo}]: ").strip().lower()
    except EOFError:
        return padrao
    if not texto:
        return padrao
    return texto in {"s", "sim", "y", "yes", "1"}


def _imprimir_relatorio(resultado: ResultadoR1, decisao: dict[str, Any]) -> None:
    """Formata e imprime no console o resumo técnico do gerenciamento de risco."""
    sep = "=" * 72
    fat = resultado.fatores_utilizados
    print(f"\n{sep}")
    print("  RELATÓRIO DE GERENCIAMENTO DE RISCO - ABNT NBR 5419-2")
    print(sep)
    print(f"  Tipologia da edificação            : {resultado.tipologia}")
    print(f"  Sistema construtivo                : {resultado.tipo_construcao}")
    if fat:
        print(
            f"  Fatores NBR 5419-2 aplicados       : rf={fat['rf']:.3g} | rp={fat['rp']:.2f} | "
            f"Lf={fat['lf']:.3g} | hz={fat['hz']:.1f} | rt={fat['rt_piso']:.3g}"
        )
    print(f"  Área de exposição equivalente (Ad) : {resultado.Ad:,.2f} m²")
    print(f"  Eventos perigosos diretos (Nd)     : {resultado.Nd:.6e} eventos/ano")
    print("-" * 72)
    print("  Decomposição do Risco R1 (Sem SPDA / Sem DPS):")
    print(f"    Ra (choque toque/passo - estrutura) : {resultado.Ra:.4e}")
    print(f"    Rb (incêndio/explosão  - estrutura) : {resultado.Rb:.4e}")
    print(f"    Ru (choque elétrico    - linhas)    : {resultado.Ru:.4e}")
    print(f"    Rv (incêndio/explosão  - linhas)    : {resultado.Rv:.4e}")
    print("-" * 72)
    print(f"  Risco Total Calculado (R1)         : {resultado.R1:.4e}")
    print(f"  Risco Tolerável (RT)               : {decisao['rt']:.4e}")
    print("-" * 72)

    if not decisao["necessita_protecao"]:
        print("  CONCLUSÃO: R1 <= RT -> Estrutura DISPENSADA de SPDA pela NBR 5419-2.")
    else:
        print("  Iteração dos Níveis de Proteção (IV -> I):")
        for item in decisao["iteracoes"]:
            status = "ATENDE (R1 <= RT)" if item["atende_RT"] else "NÃO ATENDE"
            print(
                f"    - Nível {item['nivel']:<3} (PB={item['PB']:.2f}, "
                f"PEB={item.get('PEB', 1.0):.2f}) => R1 = {item['R1']:.4e} [{status}]"
            )
        print("-" * 72)
        if decisao["mitigado"]:
            print(
                f"  CONCLUSÃO: Instalar SPDA + DPS coordenado NÍVEL {decisao['nivel_protecao']} "
                f"(R1 mitigado = {decisao['r1_final']:.4e})."
            )
        else:
            print(
                "  CONCLUSÃO: Mesmo no Nível I, R1 permanece acima de RT "
                f"({decisao['r1_final']:.4e}). Exigem-se medidas complementares."
            )
    print(f"{sep}\n")


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cálculo de Gerenciamento de Risco (R1) conforme ABNT NBR 5419-2 "
            "para múltiplas tipologias de edificações isoladas."
        )
    )
    parser.add_argument("-L", "--comprimento", type=float, help="Comprimento L da estrutura (m)")
    parser.add_argument("-W", "--largura", type=float, help="Largura W da estrutura (m)")
    parser.add_argument("-H", "--altura", type=float, help="Altura H da estrutura (m)")
    parser.add_argument(
        "-Ng",
        "--ng",
        "--densidade-descargas",
        dest="densidade_descargas",
        type=float,
        help="Densidade de descargas atmosféricas Ng (descargas/km²/ano)",
    )
    parser.add_argument(
        "-T",
        "--tipologia",
        type=str,
        default=TipologiaEdificacao.EDIFICIO_VERTICAL.value,
        help="Tipologia da edificação (ex.: edificio_vertical, galpao_industrial, residencia_unifamiliar, estrutura_especial)",
    )
    parser.add_argument(
        "--cd",
        type=float,
        default=1.0,
        help="Fator de localização Cd (padrão: 1.0 para estrutura isolada)",
    )
    parser.add_argument(
        "--rf",
        type=float,
        default=None,
        help="Sobrescreve fator de risco de incêndio rf (padrão: conforme tipologia)",
    )
    parser.add_argument(
        "--lf",
        type=float,
        default=None,
        help="Sobrescreve perda típica por danos físicos Lf (padrão: conforme tipologia)",
    )
    parser.add_argument(
        "--rp",
        type=float,
        default=None,
        help="Sobrescreve fator de medidas contra incêndio rp (padrão: conforme tipologia)",
    )
    parser.add_argument(
        "--sem-linhas",
        action="store_true",
        help="Desconsidera linhas externas de energia e sinal conectadas à estrutura",
    )
    parser.add_argument(
        "--rt",
        type=float,
        default=RISCO_TOLERAVEL_R1,
        help="Risco tolerável RT (padrão: 1e-5)",
    )
    parser.add_argument(
        "-i",
        "--interativo",
        action="store_true",
        help="Força execução em modo interativo passo a passo",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da CLI para avaliação rápida da ABNT NBR 5419-2."""
    args_lista = sys.argv[1:] if argv is None else argv
    parser = _construir_parser()
    args = parser.parse_args(args_lista)

    modo_interativo = args.interativo or len(args_lista) == 0

    try:
        if modo_interativo:
            print("=== Calculadora Universal ABNT NBR 5419-2 ===")
            for idx, nome in enumerate(LISTA_TIPOLOGIAS, start=1):
                print(f"  [{idx}] {nome}")
            try:
                escolha_txt = input("Escolha a tipologia [1]: ").strip()
            except EOFError:
                escolha_txt = ""
            indice = int(escolha_txt) - 1 if escolha_txt.isdigit() else 0
            indice = max(0, min(indice, len(LISTA_TIPOLOGIAS) - 1))
            tipologia = LISTA_TIPOLOGIAS[indice]
            perfil = PERFIS_TIPOLOGIA[tipologia]

            L = _ler_float_interativo("Comprimento L da estrutura (m)", perfil["L_padrao"])
            W = _ler_float_interativo("Largura W da estrutura (m)", perfil["W_padrao"])
            H = _ler_float_interativo("Altura H da estrutura (m)", perfil["H_padrao"])
            Ng = _ler_float_interativo("Densidade Ng (descargas/km²/ano)", perfil["Ng_padrao"])
            Cd = _ler_float_interativo("Fator de localização Cd (1.0 = isolada)", 1.0)
            rf = _ler_float_interativo("Fator de risco de incêndio rf", perfil["rf"])
            lf = _ler_float_interativo("Perda típica Lf", perfil["lf"])
            rp = _ler_float_interativo("Providências contra incêndio rp", perfil["rp"])
            incluir_linhas = _ler_bool_interativo("Incluir linhas conectadas padrão?", True)
            rt = _ler_float_interativo("Risco tolerável RT", RISCO_TOLERAVEL_R1)
            linhas = None if incluir_linhas else []
        else:
            faltantes = [
                nome
                for nome, valor in (
                    ("-L/--comprimento", args.comprimento),
                    ("-W/--largura", args.largura),
                    ("-H/--altura", args.altura),
                    ("-Ng/--densidade-descargas", args.densidade_descargas),
                )
                if valor is None
            ]
            if faltantes:
                parser.error(
                    "No modo não interativo, informe os parâmetros obrigatórios: "
                    + ", ".join(faltantes)
                )
            tipologia = normalizar_nome_tipologia(args.tipologia)
            L = args.comprimento
            W = args.largura
            H = args.altura
            Ng = args.densidade_descargas
            Cd = args.cd
            rf = args.rf
            lf = args.lf
            rp = args.rp
            linhas = [] if args.sem_linhas else None
            rt = args.rt

        resultado = calcular_risco_r1(
            L=L,
            W=W,
            H=H,
            Ng=Ng,
            Cd=Cd,
            tipologia=tipologia,
            rp=rp,
            rf=rf,
            lf=lf,
            linhas=linhas,
        )
        decisao = determinar_nivel_protecao(resultado, RT=rt)
        _imprimir_relatorio(resultado, decisao)
        return 0

    except ValueError as exc:
        print(f"Erro de validação: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
