# app/services/spend_anomaly_detector.py
"""
AI-Driven Spend Anomaly Detection (God Tier 2026).
ML-powered detection of unusual spending patterns for fraud prevention.
"""
import logging
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
import pickle
import os

from app.database import get_supabase

logger = logging.getLogger("agentshield.anomaly_detector")


class SpendAnomalyDetector:
    """
    Revolutionary ML-powered spend anomaly detection (2026).
    Detects unusual spending patterns using Isolation Forest.
    """
    
    def __init__(self):
        self.models = {}  # {user_id: IsolationForest model}
        self.model_version = "v1.0"
        self.supabase = get_supabase()
        
        # ML hyperparameters
        self.contamination = 0.05  # Expected % of anomalies
        self.n_estimators = 100
        
        # Thresholds
        self.alert_threshold = 0.6   # Score > 0.6 = ALERT
        self.throttle_threshold = 0.75  # Score > 0.75 = THROTTLE
        self.block_threshold = 0.9   # Score > 0.9 = BLOCK
    
    async def train_model(self, user_id: str, force_retrain: bool = False) -> bool:
        """
        Train anomaly detection model for a user based on historical data.
        
        Args:
            user_id: User to train model for
            force_retrain: Force retraining even if model exists
        
        Returns:
            True if training successful
        """
        # Check if model already exists
        if user_id in self.models and not force_retrain:
            logger.info(f"Model already exists for user {user_id}")
            return True
        
        try:
            # Fetch historical spend data (last 30 days)
            training_data = await self._fetch_training_data(user_id)
            
            if len(training_data) < 10:
                logger.warning(f"Insufficient data for user {user_id} (need 10+ samples, got {len(training_data)})")
                return False
            
            # Extract features
            X = self._extract_features(training_data)
            
            # Train Isolation Forest
            model = IsolationForest(
                contamination=self.contamination,
                n_estimators=self.n_estimators,
                random_state=42
            )
            model.fit(X)
            
            # Store model
            self.models[user_id] = model
            
            logger.info(f"✅ Trained anomaly model for user {user_id} with {len(training_data)} samples")
            
            # Persist model to disk
            await self._save_model(user_id, model)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to train model for user {user_id}: {e}")
            return False
    
    async def predict(
        self,
        user_id: str,
        current_spend: float,
        time_window_hours: int = 1
    ) -> Tuple[float, str, str]:
        """
        Predict if current spend is anomalous.
        
        Args:
            user_id: User to check
            current_spend: Current spend in USD
            time_window_hours: Time window (default: 1 hour)
        
        Returns:
            (anomaly_score, severity, action)
            - anomaly_score: 0-1, higher = more anomalous
            - severity: LOW/MEDIUM/HIGH/CRITICAL
            - action: NONE/ALERT/THROTTLE/BLOCK
        """
        # Ensure model is trained
        if user_id not in self.models:
            success = await self.train_model(user_id)
            if not success:
                # No model available, allow but log
                logger.warning(f"No anomaly model for user {user_id}, allowing request")
                return 0.0, "LOW", "NONE"
        
        try:
            # Get baseline spend
            baseline_spend = await self._get_baseline_spend(user_id, time_window_hours)
            
            # Compute features for current window
            features = np.array([[
                current_spend,
                current_spend - baseline_spend,
                (current_spend / baseline_spend) if baseline_spend > 0 else 1.0,
                time_window_hours
            ]])
            
            # Predict anomaly score
            model = self.models[user_id]
            prediction = model.predict(features)[0]  # 1 = normal, -1 = anomaly
            anomaly_score_raw = model.decision_function(features)[0]
            
            # Normalize score to 0-1 (more negative = more anomalous)
            anomaly_score = 1 / (1 + np.exp(anomaly_score_raw))  # Sigmoid
            
            # Determine severity and action
            if anomaly_score >= self.block_threshold:
                severity = "CRITICAL"
                action = "BLOCK"
            elif anomaly_score >= self.throttle_threshold:
                severity = "HIGH"
                action = "THROTTLE"
            elif anomaly_score >= self.alert_threshold:
                severity = "MEDIUM"
                action = "ALERT"
            else:
                severity = "LOW"
                action = "NONE"
            
            # Log anomaly if detected
            if action != "NONE":
                logger.warning(
                    f"🚨 Spend anomaly detected for user {user_id}: "
                    f"score={anomaly_score:.2f}, baseline=${baseline_spend:.2f}, "
                    f"actual=${current_spend:.2f}, action={action}"
                )
                
                # Record anomaly in database
                await self._record_anomaly(
                    user_id=user_id,
                    anomaly_score=anomaly_score,
                    baseline_spend=baseline_spend,
                    actual_spend=current_spend,
                    severity=severity,
                    action=action
                )
            
            return anomaly_score, severity, action
            
        except Exception as e:
            logger.error(f"Anomaly prediction failed for user {user_id}: {e}")
            return 0.0, "LOW", "NONE"
    
    async def _fetch_training_data(self, user_id: str) -> list:
        """Fetch historical spend data for training."""
        try:
            result = self.supabase.rpc(
                "get_user_hourly_spend",
                {
                    "p_user_id": user_id,
                    "p_days_back": 30
                }
            ).execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            # Fallback: manual query
            logger.warning(f"RPC failed, using manual query: {e}")
            
            result = self.supabase.table("receipts")\
                .select("cost_real, created_at")\
                .eq("user_id", user_id)\
                .gte("created_at", (datetime.utcnow() - timedelta(days=30)).isoformat())\
                .order("created_at", desc=True)\
                .limit(1000)\
                .execute()
            
            # Aggregate by hour
            hourly_spend = {}
            for row in result.data:
                hour = datetime.fromisoformat(row["created_at"]).replace(minute=0, second=0, microsecond=0)
                hourly_spend[hour] = hourly_spend.get(hour, 0) + row["cost_real"]
            
            return [{"hour": k, "spend": v} for k, v in hourly_spend.items()]
    
    def _extract_features(self, training_data: list) -> np.ndarray:
        """Extract features from training data."""
        features = []
        
        for row in training_data:
            spend = row.get("spend", row.get("hourly_spend", 0))
            features.append([
                spend,                    # Absolute spend
                0,                        # Deviation (not relevant for training)
                1,                        # Ratio (not relevant for training)
                1                         # Time window (always 1 hour for historical)
            ])
        
        return np.array(features)
    
    async def _get_baseline_spend(self, user_id: str, hours: int) -> float:
        """Get baseline spend for comparison."""
        try:
            result = self.supabase.table("receipts")\
                .select("cost_real")\
                .eq("user_id", user_id)\
                .gte("created_at", (datetime.utcnow() - timedelta(hours=hours)).isoformat())\
                .execute()
            
            if not result.data:
                return 0.0
            
            total = sum(r["cost_real"] for r in result.data)
            return total / hours  # Average per hour
            
        except Exception as e:
            logger.error(f"Failed to get baseline spend: {e}")
            return 0.0
    
    async def _record_anomaly(
        self,
        user_id: str,
        anomaly_score: float,
        baseline_spend: float,
        actual_spend: float,
        severity: str,
        action: str
    ):
        """Record anomaly in database."""
        try:
            # Get tenant_id for user
            user_result = self.supabase.table("user_profiles")\
                .select("tenant_id")\
                .eq("user_id", user_id)\
                .single()\
                .execute()
            
            tenant_id = user_result.data["tenant_id"]
            
            # Calculate deviation
            deviation_pct = ((actual_spend - baseline_spend) / baseline_spend * 100) if baseline_spend > 0 else 0
            
            # Insert anomaly record
            self.supabase.table("spend_anomalies").insert({
                "user_id": user_id,
                "tenant_id": tenant_id,
                "anomaly_score": anomaly_score,
                "spend_baseline": baseline_spend,
                "spend_actual": actual_spend,
                "spend_deviation_pct": deviation_pct,
                "time_window_start": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                "time_window_end": datetime.utcnow().isoformat(),
                "action_taken": action,
                "severity": severity,
                "model_version": self.model_version
            }).execute()
            
        except Exception as e:
            logger.error(f"Failed to record anomaly: {e}")
    
    async def _save_model(self, user_id: str, model):
        """Persist model to disk."""
        try:
            model_dir = "models/anomaly_detection"
            os.makedirs(model_dir, exist_ok=True)
            
            model_path = f"{model_dir}/{user_id}.pkl"
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)
            
            logger.info(f"Saved model for user {user_id} to {model_path}")
            
        except Exception as e:
            logger.warning(f"Failed to save model: {e}")


# Global instance
spend_anomaly_detector = SpendAnomalyDetector()
