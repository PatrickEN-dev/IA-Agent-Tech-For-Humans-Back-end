@echo off
echo ================================================
echo   Banco Agil - Sistema de Atendimento Digital
echo ================================================
echo.
echo Iniciando o sistema...
echo.

REM Iniciar API FastAPI em segundo plano
echo [1/2] Iniciando API FastAPI...
start "API FastAPI" cmd /k "python app.py"
timeout /t 3 /nobreak > nul

REM Iniciar UI Streamlit com agente
echo [2/2] Iniciando UI Streamlit com Agente...
start "UI Streamlit" cmd /k "cd src\ui && python -m streamlit run streamlit_app_agent.py"
timeout /t 3 /nobreak > nul

echo.
echo ================================================
echo   Sistema iniciado com sucesso!
echo ================================================
echo.
echo URLs disponiveis:
echo   - API: http://localhost:8000
echo   - Docs API: http://localhost:8000/docs
echo   - UI Streamlit: http://localhost:8502
echo.
echo Pressione qualquer tecla para sair...
pause > nul
