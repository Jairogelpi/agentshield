# God Tier Budget & Quota System

Sistema revolucionario de control de gastos con **quotas por usuario, wallets prepagos, y detección de anomalías con ML**.

## Features

### 1. Actor-Level Quotas (Per-User Limits)

**Daily/Monthly Limits**:
- Configure límites individuales por usuario
- Auto-reset diario y mensual
- Jerarquía: User < Dept < Tenant (el más restrictivo gana)

**uso**:
```http
GET /budget/quotas/{user_id}
PUT /budget/quotas/{user_id}
{
  "daily_limit_usd": 50.00,
  "monthly_limit_usd": 1500.00
}
```

### 2. Pre-paid Wallets (Credit System)

**Wallet Types**:
- **POSTPAID**: Facturación mensual (comportamiento existente)
- **PREPAID**: Deducción en tiempo real, bloqueo al llegar a $0

**Top-up API**:
```http
POST /budget/wallets/{wallet_id}/top-up
{
  "amount": 100.00,
  "payment_method": "STRIPE"
}
```

**Conversión**:
```http
POST /budget/wallets/{wallet_id}/convert-to-prepaid
```

**Features**:
- Real-time balance deduction
- Overdraft protection opcional
- Low balance alerts
- Top-up history tracking

### 3. AI-Driven Anomaly Detection

**ML Model**: Isolation Forest (scikit-learn)
- Entrenamiento en histórico de gasto (últimos 30 días)
- Detección en tiempo real
- Features: hourly spend, request count, avg cost, model distribution

**Anomaly Actions**:
- **ALERT** (score 0.6-0.75): Notificar admin
- **THROTTLE** (score 0.75-0.9): Reducir rate limit 50%
- **BLOCK** (score >0.9): Suspender acceso temporalmente

**API**:
```http
GET /budget/anomalies?user_id={uuid}&resolved=false
POST /budget/anomalies/{anomaly_id}/acknowledge
POST /budget/anomalies/train-model/{user_id}
```

## Enforcement Flow

### Real-Time Check (Pre-Request)
```
1. User Quota Check
   ↓ (if OK)
2. Prepaid Wallet Balance Check
   ↓ (if OK)
3. ML Anomaly Detection
   ↓ (if OK)
4. Proceed with request
```

### Post-Request Charging
```
1. Charge hierarchical wallets (Tenant/Dept/User)
2. Increment user quota spend
3. Deduct prepaid wallet balance (if applicable)
4. Update anomaly baseline
```

## Examples

### Example 1: User Quota Exceeded
```
User: john@company.com
Daily Limit: $20.00
Current Spend: $19.50
Request Cost: $1.00

Result: BLOCKED
Reason: "User Quota: Daily limit $20.00 exceeded"
```

### Example 2: Prepaid Wallet Depleted
```
Wallet: dept-marketing (PREPAID)
Balance: $2.50
Request Cost: $3.00
Overdraft Protection: false

Result: BLOCKED
Reason: "Wallet: Insufficient funds (balance: $2.50)"
Action: Email sent to wallet owner for top-up
```

### Example 3: Anomaly Detected
```
User: alice@company.com
Baseline hourly spend: $5 ± $2
Current hourly spend: $50

Anomaly Score: 0.92 (CRITICAL)
Severity: CRITICAL
Action: BLOCK

Result: BLOCKED
Reason: "Anomaly: Anomalous spend detected (score: 0.92)"
Notification: Slack alert to FinOps team
```

### Example 4: Low Balance Alert
```
Wallet: engineering-team (PREPAID)
Balance: $4.50
Low Balance Threshold: $5.00

Result: ALLOWED (but alert sent)
Action: Email to wallet owner
Subject: "Low Balance Alert: $4.50 remaining"
```

## Database Schema

### `user_quotas`
```sql
- user_id (PK)
- tenant_id
- daily_limit_usd
- monthly_limit_usd
- current_daily_spend
- current_monthly_spend
- last_reset_daily
- last_reset_monthly
```

### `wallets` (extended)
```sql
+ wallet_type: POSTPAID | PREPAID
+ overdraft_protection: boolean
+ low_balance_threshold: numeric
+ last_low_balance_alert: timestamp
```

### `wallet_top_ups`
```sql
- id (PK)
- wallet_id
- amount
- payment_method: STRIPE | PAYPAL | CRYPTO | MANUAL
- status: PENDING | COMPLETED | FAILED | REFUNDED
- payment_intent_id
- transaction_id
```

### `spend_anomalies`
```sql
- id (PK)
- user_id
- tenant_id
- detected_at
- anomaly_score (0-1)
- spend_baseline
- spend_actual
- spend_deviation_pct
- action_taken: ALERT | THROTTLE | BLOCK | NONE
- severity: LOW | MEDIUM | HIGH | CRITICAL
- resolved: boolean
- model_version
```

## API Reference

### User Quotas
- `GET /budget/quotas/{user_id}` - Get quota info
- `PUT /budget/quotas/{user_id}` - Update limits
- `POST /budget/quotas/{user_id}/reset-daily` - Manual reset

### Wallets
- `GET /budget/wallets/{wallet_id}` - Get wallet info
- `POST /budget/wallets/{wallet_id}/top-up` - Add credits
- `POST /budget/wallets/{wallet_id}/convert-to-prepaid` - Convert type
- `GET /budget/wallets/{wallet_id}/top-ups` - Top-up history

### Anomalies
- `GET /budget/anomalies` - List anomalies (filter by user/tenant/severity/resolved)
- `POST /budget/anomalies/{anomaly_id}/acknowledge` - Resolve anomaly
- `POST /budget/anomalies/train-model/{user_id}` - Train/retrain ML model

## Best Practices

1. **Set Conservative Quotas**: Start with low limits and increase based on usage
2. **Monitor Anomalies Daily**: Review unresolved anomalies in dashboard
3. **Train Models Regularly**: Retrain ML models monthly for accuracy
4. **Configure Low Balance Alerts**: Set threshold to 10% of avg monthly spend
5. **Use Prepaid for High-Risk Teams**: Reduce financial exposure

## Troubleshooting

### False Positives (Anomaly)
- Acknowledge anomaly with note
- Retrain model after major usage pattern changes
- Adjust thresholds if needed

### Wallet Sync Issues
- Check wallet balance vs DB vs Redis
- Manual reconciliation via admin panel
- Verify top-up completion status

### Quota Not Resetting
- Check last_reset timestamps
- Run manual reset via API
- Verify cron job is running

---

**AgentShield: El único AI gateway con FinOps inteligente y ML-powered spend protection en 2026.**
