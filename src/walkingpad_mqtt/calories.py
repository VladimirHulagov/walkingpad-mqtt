from __future__ import annotations


def estimate_kcal(weight_kg: float, distance_km: float, coefficient: float = 1.03) -> float:
    """Оценка калорий ходьбы: ккал ≈ вес(кг) × дистанция(км) × коэффициент."""
    if weight_kg < 0 or distance_km < 0:
        raise ValueError("weight_kg and distance_km must be non-negative")
    return round(weight_kg * distance_km * coefficient, 1)
