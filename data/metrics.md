# KPI glossary

The official definitions used in the monthly KPI report. Compute every KPI exactly as defined here.

## SLA compliance rate
Aliases: SLA, on-time rate, within SLA, SLA performance

Share of finished requests (status `resolved` or `closed`) whose `resolved_hours <= sla_hours`.
Open, in-progress and cancelled requests are excluded from both numerator and denominator.
Report as a percentage with one decimal.

```sql
SELECT ROUND(100.0 * SUM(resolved_hours <= sla_hours) / COUNT(*), 1)
FROM requests WHERE status IN ('resolved', 'closed')  -- add region / date filters
```

## Backlog
Aliases: open requests, pending requests, outstanding requests, work in progress

Number of requests with status `open` or `in_progress`. Cancelled requests are not backlog.
The database is a snapshot taken at the end of 2026-09-30, so the backlog "now" or "at the end of September" is the
count over all requests with those statuses.

## CSAT score
Aliases: customer satisfaction, satisfaction score, CSAT

Percentage of **rated** requests (`csat IS NOT NULL`) with `csat >= 4`. One decimal.
This is not the average rating. If someone asks for the "average rating", give `ROUND(AVG(csat), 2)` instead and say
that it is a different measure from the CSAT score.

## Average resolution time
Aliases: ART, mean time to resolve, resolution time, time to resolve

`ROUND(AVG(resolved_hours), 1)` over finished requests (status `resolved` or `closed`), in hours.

## Requests per 10k residents
Aliases: demand rate, per capita demand, requests per capita

`ROUND(COUNT(*) * 10000.0 / regions.population, 1)` for a region, counting all requests submitted (every status,
cancelled included). Join `requests.region = regions.code`.

## Cancellation rate
Aliases: cancelled share

Percentage of all requests with status `cancelled`. One decimal.

## Reporting periods
Aliases: quarter, Q3, month, period

Q3 2026 = 2026-07-01 to 2026-09-30, which is the whole dataset. Months are filtered on `opened_on`, e.g.
`opened_on LIKE '2026-08-%'` or `strftime('%m', opened_on) = '08'`.
