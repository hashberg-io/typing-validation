@echo off
mypy --strict typing_validation
pytest test --cov=./typing_validation
coverage html
@pause
