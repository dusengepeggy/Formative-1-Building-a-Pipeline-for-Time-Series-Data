import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def evaluate(y_true, y_pred):
    """MAE, RMSE and R2 rounded to 3 decimals, as reported in the experiment table."""
    return {"MAE": round(mean_absolute_error(y_true, y_pred), 3),
            "RMSE": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 3),
            "R2": round(r2_score(y_true, y_pred), 3)}
