# Dammam Q3 2026 KPI Summary

**Region:** Dammam (DMM)  
**Period:** Q3 2026 (2026-07-01 to 2026-09-30)

## Key Metrics

| KPI | Value | Definition |
|-----|-------|------------|
| **Backlog** | 8 | Requests with status `open` or `in_progress` (snapshot 2026-09-30) |
| **SLA Compliance Rate** | 72.5% | Share of finished requests (`resolved`/`closed`) with `resolved_hours ≤ sla_hours` |
| **CSAT Score** | 60.2% | Percentage of rated requests (`csat IS NOT NULL`) with `csat ≥ 4` |

## Computation Notes
- **Backlog**: `COUNT(*) FROM requests WHERE region='DMM' AND status IN ('open','in_progress') AND opened_on BETWEEN '2026-07-01' AND '2026-09-30'`
- **SLA Compliance**: `ROUND(100.0 * SUM(resolved_hours <= sla_hours) / COUNT(*), 1) FROM requests WHERE region='DMM' AND status IN ('resolved','closed') AND opened_on BETWEEN '2026-07-01' AND '2026-09-30'`
- **CSAT Score**: `ROUND(100.0 * SUM(csat >= 4) / COUNT(*), 1) FROM requests WHERE region='DMM' AND status IN ('resolved','closed') AND csat IS NOT NULL AND opened_on BETWEEN '2026-07-01' AND '2026-09-30'`

*Report generated from the KPI database (snapshot 2026-09-30).*