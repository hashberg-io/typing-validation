@echo off
mypy --strict typing_validation
pylint typing_validation
pytest test --cov=./typing_validation
coverage html
@pause
