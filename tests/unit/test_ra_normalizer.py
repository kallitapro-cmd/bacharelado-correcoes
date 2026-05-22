"""Testes unitários para normalize_ra() — Story 1.10, ADR-001."""

from __future__ import annotations

from src.matching.ra_normalizer import normalize_ra


class TestNormalizeRa:
    """Cobre os 8 casos obrigatórios do ADR-001 + casos de formatação."""

    def test_onze_digitos_canónico_sem_alteração(self) -> None:
        assert normalize_ra("20260100418") == "20260100418"

    def test_dez_digitos_2026_insere_zero_posicao_4(self) -> None:
        assert normalize_ra("2026100418") == "20260100418"

    def test_dez_digitos_2025_insere_zero_posicao_4(self) -> None:
        assert normalize_ra("2025100333") == "20250100333"

    def test_ra_especial_0000_sem_alteração(self) -> None:
        assert normalize_ra("0000100041") == "0000100041"

    def test_ra_com_espacos_strip_antes_de_normalizar(self) -> None:
        assert normalize_ra(" 2026100418 ") == "20260100418"

    def test_ra_com_pontos_limpa_antes_de_normalizar(self) -> None:
        assert normalize_ra("2026.100418") == "20260100418"

    def test_ra_com_hifen_limpa_antes_de_normalizar(self) -> None:
        assert normalize_ra("2026-100418") == "20260100418"

    def test_idempotente_aplicar_duas_vezes_mesmo_resultado(self) -> None:
        ra = "2026100418"
        assert normalize_ra(normalize_ra(ra)) == normalize_ra(ra)

    # Casos de robustez extras (ADR-001 tabela completa)

    def test_onze_digitos_com_espaco_final(self) -> None:
        assert normalize_ra("20260100418 ") == "20260100418"

    def test_ra_vazio_retorna_vazio(self) -> None:
        assert normalize_ra("") == ""

    def test_ra_ano_nao_suportado_fallback(self) -> None:
        assert normalize_ra("2024100500") == "2024100500"

    def test_ra_canónico_2025_idempotente(self) -> None:
        assert normalize_ra("20250100621") == "20250100621"
