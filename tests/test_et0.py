import numpy as np
import pytest

from towers.utils.et0 import altitude_da_pressao, et0_hargreaves, et0_penman_monteith, pressao_vapor_saturacao


def test_pressao_vapor_saturacao():
    assert pressao_vapor_saturacao(np.array(21.5)) == pytest.approx(2.564, abs=0.003)   # FAO-56 ex. 18
    assert pressao_vapor_saturacao(np.array(12.3)) == pytest.approx(1.431, abs=0.003)


def test_altitude_da_pressao():
    assert altitude_da_pressao(100.1) == pytest.approx(100, abs=15)    # FAO-56 ex. 18: z = 100 m


def test_fao56_exemplo_18_uccle():
    """Uccle (Bélgica), 6/jul: ET0 = 3,9 mm/dia. O exemplo usa URmax/URmin (ea = 1,409 kPa); com a
    UR média (73,5%) o ea fica um pouco maior, então a ET0 sai ligeiramente menor."""
    et0 = et0_penman_monteith(tmax=21.5, tmin=12.3, ur_media=73.5, u2=2.078, rs=22.07,
                              lat=50.8, j=187, pressao_kpa=100.1)
    assert et0 == pytest.approx(3.9, abs=0.2)


def test_hargreaves_ordem_de_grandeza():
    v = et0_hargreaves(30.0, 18.0, -23.0, 15)       # verão no PR
    assert 4.0 < v < 7.0


def test_et0_nunca_negativa():
    assert et0_penman_monteith(5, 2, 99, 0.5, 1.0, -30, 172, 95.0) >= 0
