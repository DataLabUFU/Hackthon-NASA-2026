"""Configuração comum dos testes."""
import os

# os testes nunca usam o NeonDB (nem quando .streamlit/secrets.toml existe); tests/test_neon.py usa um banco falso
os.environ["RECOMENDADOR_NEON"] = "0"
