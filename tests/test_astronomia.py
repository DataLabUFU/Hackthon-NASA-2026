from datetime import date

import numpy as np
import pytest

from towers.utils.astronomia import comprimento_dia, dia_do_ano, radiacao_extraterrestre


def test_dia_do_ano():
    assert dia_do_ano(date(2026, 1, 1)) == 1
    assert dia_do_ano(date(2026, 9, 3)) == 246
    assert list(dia_do_ano([date(2026, 1, 1), date(2026, 12, 31)])) == [1, 365]


def test_fao56_exemplo_8_radiacao_extraterrestre():
    # FAO-56, exemplo 8: 20°S em 3 de setembro (J = 246) → Ra = 32,2 MJ m⁻² dia⁻¹
    assert radiacao_extraterrestre(-20, 246) == pytest.approx(32.2, abs=0.1)


def test_fao56_exemplo_9_horas_de_luz():
    # FAO-56, exemplo 9: 20°S em 3 de setembro → N = 11,7 h
    assert comprimento_dia(-20, 246) == pytest.approx(11.7, abs=0.05)


def test_equador_tem_12_horas_o_ano_todo():
    assert np.allclose(comprimento_dia(0, np.arange(1, 366)), 12.0)


def test_simetria_entre_hemisferios():
    j = np.arange(1, 366)
    assert np.allclose(comprimento_dia(-25, j) + comprimento_dia(25, j), 24.0)


@pytest.mark.parametrize("lat, j, minimo, maximo", [
    (-30, 355, 13.8, 14.2),   # verão no RS: ~14 h
    (-30, 172, 9.8, 10.4),    # inverno no RS: ~10 h
    (-3, 172, 11.7, 12.0),    # Norte: quase 12 h o ano todo
])
def test_faixas_no_brasil(lat, j, minimo, maximo):
    assert minimo <= comprimento_dia(lat, j) <= maximo


def test_latitude_polar_nao_gera_nan():
    assert not np.isnan(comprimento_dia(80, np.arange(1, 366))).any()
