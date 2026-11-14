"""Acesso aos dados. Ordem de confiança no hackathon:
1) clima_power  -> NASA POWER (API simples, sem cadastro)       [usado pelo app]
2) solo_*       -> SoilGrids (global) / SSURGO (EUA)            [opcional; NÃO TESTADOS]
3) ee_*         -> SRTM e SMAP via Google Earth Engine          [opcional; NÃO TESTADO]
4) previsao_16d -> Open-Meteo (fora da lista da NASA; só curto prazo)

Tudo que falhar deve cair para entrada manual do agrônomo.
"""
import datetime as dt

import numpy as np
import pandas as pd
import requests


def clima_power(lat, lon, ano_ini=2015):
    """Série diária: temperatura, mínima, chuva e umidade da zona radicular (NASA POWER)."""
    fim = dt.date.today() - dt.timedelta(days=5)
    r = requests.get(
        "https://power.larc.nasa.gov/api/temporal/daily/point",
        params=dict(parameters="T2M,T2M_MIN,PRECTOTCORR,GWETROOT", community="AG",
                    latitude=lat, longitude=lon, start=f"{ano_ini}0101",
                    end=fim.strftime("%Y%m%d"), format="JSON"),
        timeout=180)
    r.raise_for_status()
    d = pd.DataFrame(r.json()["properties"]["parameter"]).replace(-999, np.nan)
    d.index = pd.to_datetime(d.index, format="%Y%m%d")
    return d


def anomalia_umidade(clima, dias=30):
    """Umidade da zona radicular dos últimos 30 dias vs. mesma época nos anos anteriores (z-score)."""
    s = clima["GWETROOT"].dropna()
    if s.empty:
        return None
    fim = s.index.max()
    atual = s[fim - pd.Timedelta(days=dias): fim].mean()
    hist = []
    for a in range(1, 10):
        f = fim - pd.DateOffset(years=a)
        j = s[f - pd.Timedelta(days=dias): f]
        if len(j) > dias * 0.8:
            hist.append(j.mean())
    if len(hist) < 3:
        return None
    return float((atual - np.mean(hist)) / (np.std(hist) or 1))


def solo_soilgrids(lat, lon):
    """Argila e matéria orgânica (0-30 cm) do SoilGrids. Global, ~250 m. NÃO TESTADO."""
    params = [("lon", lon), ("lat", lat), ("property", "clay"), ("property", "soc"),
              ("depth", "0-5cm"), ("depth", "5-15cm"), ("depth", "15-30cm"), ("value", "mean")]
    r = requests.get("https://rest.isric.org/soilgrids/v2.0/properties/query", params=params, timeout=60)
    r.raise_for_status()
    v = {}
    for lay in r.json()["properties"]["layers"]:
        f = lay["unit_measure"].get("d_factor") or 1
        vals = [d["values"]["mean"] for d in lay["depths"] if d["values"]["mean"] is not None]
        v[lay["name"]] = float(np.mean(vals)) / f
    return {"argila_pct": v["clay"],                 # %
            "mo_pct": v["soc"] / 10 * 1.724}         # carbono (g/kg) -> matéria orgânica (%)


def solo_ssurgo(lat, lon):
    """Solo do USDA SSURGO via Soil Data Access (só EUA). NÃO TESTADO."""
    sql = f"""SELECT TOP 1 ch.claytotal_r AS argila_pct, ch.om_r AS mo_pct
    FROM mapunit mu JOIN component c ON c.mukey = mu.mukey JOIN chorizon ch ON ch.cokey = c.cokey
    WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
    AND c.majcompflag = 'Yes' ORDER BY c.comppct_r DESC, ch.hzdept_r"""
    r = requests.post("https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
                      json={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=60)
    r.raise_for_status()
    t = r.json()["Table"]
    return {k: float(x) for k, x in zip(t[0], t[1])}


def solo_auto(lat, lon):
    nos_eua = 24 < lat < 50 and -125 < lon < -66
    return solo_ssurgo(lat, lon) if nos_eua else solo_soilgrids(lat, lon)


def ee_indicadores(lat, lon, projeto):
    """Declividade (SRTM) e anomalia de umidade da zona radicular (SMAP L4) via Earth Engine.
    Requer `pip install earthengine-api` e `earthengine authenticate`. NÃO TESTADO."""
    import ee
    ee.Initialize(project=projeto)
    pt = ee.Geometry.Point([lon, lat])
    graus = (ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
             .reduceRegion(ee.Reducer.mean(), pt.buffer(500), 30).get("slope").getInfo())
    col = ee.ImageCollection("NASA/SMAP/SPL4SMGP/007").select("sm_rootzone")  # confira a versão no catálogo

    def media(fim):
        ini = fim - dt.timedelta(days=30)
        return (col.filterDate(str(ini), str(fim)).mean()
                .reduceRegion(ee.Reducer.mean(), pt, 9000).get("sm_rootzone").getInfo())

    hoje = dt.date.today() - dt.timedelta(days=5)
    atual = media(hoje)
    hist = [media(hoje - dt.timedelta(days=365 * k)) for k in range(1, 6)]
    hist = [h for h in hist if h is not None]
    z = (atual - np.mean(hist)) / (np.std(hist) or 1) if atual is not None and len(hist) >= 3 else None
    return {"declividade_pct": float(np.tan(np.radians(graus)) * 100), "smap_anomalia": z}


def previsao_16d(lat, lon):
    """Previsão diária de 16 dias (Open-Meteo, sem chave). Só informativa: não prevê a safra."""
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params=dict(
        latitude=lat, longitude=lon, forecast_days=16, timezone="auto",
        daily="temperature_2m_max,temperature_2m_min,precipitation_sum"))
    r.raise_for_status()
    d = r.json()["daily"]
    return pd.DataFrame({"tmax": d["temperature_2m_max"], "tmin": d["temperature_2m_min"],
                         "chuva_mm": d["precipitation_sum"]}, index=pd.to_datetime(d["time"]))
