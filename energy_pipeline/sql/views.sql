-- Daily view: what a trader would glance at each morning.
CREATE OR REPLACE VIEW daily_summary AS
SELECT
    CAST(timestamp_utc AS DATE)                 AS day_utc,
    COUNT(*)                                    AS hours,
    ROUND(AVG(price_eur_mwh), 2)                AS avg_price_eur_mwh,
    MIN(price_eur_mwh)                          AS min_price_eur_mwh,
    MAX(price_eur_mwh)                          AS max_price_eur_mwh,
    SUM(CASE WHEN price_eur_mwh < 0 THEN 1 ELSE 0 END) AS negative_price_hours,
    ROUND(SUM(wind_generation_mw) / 1000, 1)    AS wind_gwh,
    ROUND(SUM(load_mw) / 1000, 1)               AS load_gwh,
    ROUND(SUM(wind_generation_mw) / SUM(load_mw), 3) AS wind_share,
    ROUND(AVG(wind_speed_100m_ms_mean), 2)      AS avg_wind_speed_100m_ms,
    ROUND(AVG(temperature_c_mean), 1)           AS avg_temperature_c,
    SUM(CASE WHEN had_gap THEN 1 ELSE 0 END)    AS hours_with_gaps
FROM hourly
GROUP BY 1
ORDER BY 1;

-- Merit-order effect: more wind -> lower price. Hours split into 10 equal groups by wind output.
CREATE OR REPLACE VIEW price_by_wind_decile AS
WITH ranked AS (
    SELECT *, NTILE(10) OVER (ORDER BY wind_generation_mw) AS wind_decile
    FROM hourly
    WHERE quality_ok
)
SELECT
    wind_decile,
    COUNT(*)                                 AS hours,
    ROUND(MIN(wind_generation_mw))           AS wind_mw_from,
    ROUND(MAX(wind_generation_mw))           AS wind_mw_to,
    ROUND(AVG(wind_speed_100m_ms_mean), 2)   AS avg_wind_speed_100m_ms,
    ROUND(AVG(price_eur_mwh), 2)             AS avg_price_eur_mwh
FROM ranked
GROUP BY 1
ORDER BY 1;

-- Monthly view for a longer-range picture.
CREATE OR REPLACE VIEW monthly_summary AS
SELECT
    DATE_TRUNC('month', timestamp_utc)       AS month_utc,
    ROUND(AVG(price_eur_mwh), 2)             AS avg_price_eur_mwh,
    ROUND(SUM(wind_generation_mw) / 1e6, 2)  AS wind_twh,
    ROUND(SUM(load_mw) / 1e6, 2)             AS load_twh,
    SUM(CASE WHEN price_eur_mwh < 0 THEN 1 ELSE 0 END) AS negative_price_hours
FROM hourly
GROUP BY 1
ORDER BY 1;
