.PHONY: install build summary test clean

install:
	pip install -r requirements.txt

build:
	python -m energy_pipeline build

summary:
	python -m energy_pipeline summary

test:
	python -m pytest -q

clean:
	rm -rf data/energy.duckdb data/run_summary.json
