@echo off
REM CTRL+F: processa os pedidos da pagina "Importar imagens" com a pipeline.
REM Ajuste as 3 pastas abaixo: a do repositorio da pipeline, a dos pesos e a pasta "dados" da interface. Deixe esta janela aberta.
set PIPELINE=C:\caminho\para\repositorio_limpo
set PESOS=C:\caminho\para\pesos
set DADOS=C:\caminho\para\repositorio_limpo\interface\dados

"%PIPELINE%\.venv\Scripts\python.exe" "%~dp0ctrlf_worker.py" --pipeline "%PIPELINE%" --pesos "%PESOS%" --dados "%DADOS%" %*
pause
