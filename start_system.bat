@echo off
echo ================================================
echo   Banco Agil - API do Assistente Virtual
echo ================================================
echo.

REM Ativa o ambiente virtual se existir
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

echo Iniciando a API FastAPI em http://localhost:8000 ...
echo (Swagger em http://localhost:8000/docs)
echo.
echo O front-end (Next.js) fica no repositorio IA-Agent-Tech-For-Humans-Front-end:
echo   npm install ^&^& npm run dev   ->  http://localhost:3000
echo.

python app.py
