# CLAUDE.md — Trading Strategy: Elephant Bar

## Project Overview

This repository implements a trading strategy based on the **Elephant Bar** pattern — a technical analysis candlestick pattern characterized by an unusually large-bodied candle that significantly exceeds the average range of recent candles. Elephant bars often signal strong momentum and potential trend continuation or reversal points.

## Repository Structure

This is a newly initialized project. As the codebase grows, maintain the following structure:

```
Trading_strat_elephantBar/
├── CLAUDE.md              # AI assistant guide (this file)
├── README.md              # Project overview and usage instructions
├── requirements.txt       # Python dependencies
├── setup.py / pyproject.toml  # Package configuration (if applicable)
├── src/                   # Main source code
│   ├── strategy/          # Elephant bar strategy logic
│   ├── data/              # Data fetching and processing
│   ├── backtest/          # Backtesting engine and utilities
│   └── utils/             # Shared helpers
├── tests/                 # Unit and integration tests
├── notebooks/             # Jupyter notebooks for exploration/analysis
├── config/                # Configuration files (API keys, strategy params)
└── scripts/               # CLI scripts and entry points
```

## Development Conventions

### Language & Environment

- **Primary language**: Python 3.10+
- **Dependency management**: `requirements.txt` (or `pyproject.toml` if a build system is added)
- Install dependencies: `pip install -r requirements.txt`

### Code Style

- Follow **PEP 8** for Python code
- Use type hints for function signatures
- Keep functions focused and small — prefer pure functions for strategy logic
- Use descriptive variable names (e.g., `elephant_bar_threshold` not `ebt`)

### Testing

- Use **pytest** for testing
- Run tests: `pytest`
- Run with coverage: `pytest --cov`
- Place tests in `tests/` mirroring the `src/` structure

### Git Workflow

- Branch naming: `feature/<description>`, `fix/<description>`, `claude/<description>`
- Write clear, descriptive commit messages
- Keep commits atomic — one logical change per commit

## Key Domain Concepts

- **Elephant Bar**: A candle whose body size is significantly larger (typically 2-3x) than the average body size of the preceding N candles
- **Signal Direction**: Bullish elephant bar (close > open) suggests long entry; bearish (close < open) suggests short entry
- **Confirmation**: Strategies may require confirmation from subsequent candles or additional indicators before entering a trade
- **Risk Management**: Stop-loss placement typically at the opposite end of the elephant bar or at a defined ATR multiple

## Important Notes for AI Assistants

- **No secrets in code**: Never commit API keys, credentials, or tokens. Use environment variables or config files listed in `.gitignore`
- **Data handling**: Financial data can be large — avoid committing raw datasets to git
- **Numerical precision**: Use `decimal.Decimal` or careful float handling for price calculations where precision matters
- **Backtesting integrity**: Never introduce look-ahead bias in backtesting logic — only use data available up to the current bar
- **External APIs**: When integrating with broker/data APIs, handle rate limits and connection errors gracefully
