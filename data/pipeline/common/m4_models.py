"""2차 M4 공통 — DA 재현 패키지에서 뽑은 모델 자산(MinIO raw/model/<버전>/)을 읽어 점수를 낸다.

자산 (data/raw/model/<버전>/, MinIO 에 같은 경로):
  models/{gangnam,chuncheon}_final.joblib             읍면동 IsolationForest (지표 12개)
  models/{gangnam,chuncheon}_reference_final.joblib   격자 IsolationForest (지표 10개)
  registry.json                                       모델 목록 · sha256 · 점수 산식 (-score_samples × 100)
  background_pca_parameters.json                      배경 취약성 점수 S 의 고정 PCA 계수 (평균 · 표준편차 · 방향 · 가중치 · 절편 · 기울기)
  background_thresholds.json                          배경 등급 고정 임계값 (도시별 P20 · P80, 6개월 동 평균으로 보정)
  dong_feature_columns.json / grid_feature_columns.json  모델 입력 지표 순서
모델은 패키지가 고정한 버전(scikit-learn 1.8.0 등, data/requirements.txt)으로만 연다. 버전은 MODEL_VERSION 환경변수(기본 v20261102).
"""
import hashlib
import io
import json
import os

import joblib
import numpy as np
import pandas as pd

from . import minio_connect as connect

CITY = {"강남구": "gangnam", "춘천시": "chuncheon"}
# DB bg_region_indicator 컬럼 → PCA 입력 컬럼 (단위 같음: %, 개/㎢)
BG_COLS = {"male_pct": "male_population_pct", "one_person_hh_pct": "single_person_household_pct_annual",
           "non_apt_pct": "non_apartment_housing_pct_annual", "age65_pct": "population_65plus_pct",
           "park_area_pct": "park_registered_area_pct_snapshot", "bus_stop_density": "bus_stop_density_per_km2_snapshot"}
BAND_RANK = {"낮음": 1, "중간": 2, "높음": 3}


class ModelAssets:
    def __init__(self, version: str | None = None):
        self.version = version or os.environ.get("MODEL_VERSION", "v20261102")
        self.fs, bucket = connect()
        self.prefix = f"{bucket}/raw/model/{self.version}"
        self.registry = self._json("registry.json")
        self.pca = self._json("background_pca_parameters.json")
        self.bg_thresholds = self._json("background_thresholds.json")
        self.dong_features = self._json("dong_feature_columns.json")["features"]
        self.grid_features = self._json("grid_feature_columns.json")["features"]
        self._models: dict[str, object] = {}

    def _read(self, name: str) -> bytes:
        with self.fs.open(f"{self.prefix}/{name}", "rb") as f:
            return f.read()

    def _json(self, name: str) -> dict:
        return json.loads(self._read(name).decode("utf-8"))

    def model(self, unit: str, city: str):
        """unit: dong | grid. registry 의 sha256 과 맞는지 확인하고 연다."""
        info = next(m for m in self.registry["primary_models"] if m["unit"] == unit and m["city"] == city)
        name = info["path"].replace("\\", "/").rsplit("/", 1)[-1]
        if name not in self._models:
            raw = self._read(f"models/{name}")
            if hashlib.sha256(raw).hexdigest() != info["sha256"]:
                raise SystemExit(f"모델 파일 sha256 불일치: {name}")
            mdl = joblib.load(io.BytesIO(raw))
            feats = self.dong_features if unit == "dong" else self.grid_features
            if list(mdl.feature_names_in_) != feats:
                raise SystemExit(f"모델 입력 지표 순서 불일치: {name}")
            self._models[name] = mdl
        return self._models[name], info["model_id"]

    # ---- M4-2 배경 취약성 점수 S = 절편 + 기울기 × Σ w·d·(x − mean)/sd
    def background_score(self, ind: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """ind: bg_region_indicator 6개 컬럼(BG_COLS 키). 반환 (S, 지표별 기여도[n×6])."""
        p = self.pca
        X = ind[list(BG_COLS)].to_numpy(float)
        z = (X - np.asarray(p["mean"])) / np.asarray(p["sd"]) * np.asarray(p["direction"])
        contrib = p["score_slope_on_C"] * z * np.asarray(p["weights"])
        return p["score_intercept_on_C"] + contrib.sum(axis=1), contrib

    def background_band(self, city: str, s: float) -> str:
        c = self.bg_thresholds[city]
        return "낮음" if s < c["p20"] else "중간" if s < c["p80"] else "높음"

    # ---- M4-3 행동 이상 점수 B = -score_samples × 100 (지표가 모두 유한한 행만)
    def anomaly_score(self, unit: str, city: str, feats: pd.DataFrame) -> np.ndarray:
        mdl, _ = self.model(unit, city)
        cols = self.dong_features if unit == "dong" else self.grid_features
        X = feats[cols].to_numpy(float)
        ok = np.isfinite(X).all(axis=1)
        out = np.full(len(X), np.nan)
        if ok.any():
            out[ok] = -mdl.score_samples(pd.DataFrame(X[ok], columns=cols)) * 100
        return out


# ---- M4-4 행동 등급: 그 달 · 그 도시 안 점수의 P20 · P80 (등호: P20 이하 낮음, P80 이상 높음)
def behavior_bands(scores: pd.Series) -> tuple[pd.Series, float, float]:
    p20, p80 = np.quantile(scores.to_numpy(float), [0.2, 0.8])
    if not (p20 < p80):
        raise SystemExit(f"행동 P20 = P80 ({p20}): 등급을 나눌 수 없음")
    return scores.map(lambda b: "낮음" if b <= p20 else "높음" if b >= p80 else "중간"), p20, p80
