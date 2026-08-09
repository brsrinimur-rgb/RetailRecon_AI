@echo off
title RetailRecon AI - POS to GL Control Center
cd /d "%~dp0"
python -m pip install -r requirements.txt
streamlit run Home.py
pause
