import google.generativeai as genai
import os

# --- IMPORTANTE: PEGA AQUÍ TU API KEY QUE EMPIEZA POR AIza... ---
api_key = "AIzaSyAEx3Z2GfWkLyfBYCX0iPTAb9bzHFQ-_bE" 

genai.configure(api_key=api_key)

print(f"🔍 Preguntando a Google qué modelos tienes habilitados...")

try:
    available_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"  ✅ {m.name}")
            available_models.append(m.name)
            
    print("\n--- RESUMEN ---")
    if not available_models:
        print("❌ No te sale NINGÚN modelo. Tu API Key podría estar restringida por tu organización (Universidad).")
    else:
        print("Copia uno de los nombres de arriba (ej: models/gemini-pro) y ponlo en tu código.")

except Exception as e:
    print(f"🔥 Error conectando: {e}")