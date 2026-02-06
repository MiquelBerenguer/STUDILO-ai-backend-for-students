import pytest
import httpx
import asyncio
import os
from uuid import uuid4

# CONFIGURACIÓN
BASE_URL = "http://localhost:8000"
EMAIL = f"test_ingeniero_{uuid4().hex[:6]}@tutor-ia.com"
PASSWORD = "PasswordStrong123!"

# Rutas relativas a los archivos reales
ASSETS_DIR = "tests/assets"
FILE_EXAMEN = "contexto_examen.pdf"      # El archivo de Wuolah
FILE_SOLUCIONES = "contexto_soluciones.pdf" # El archivo manuscrito

@pytest.mark.asyncio
async def test_full_student_flow_with_real_files():
    """
    Flow E2E Real:
    1. Registro & Login
    2. Subida de Contexto 1 (Examen Wuolah)
    3. Subida de Contexto 2 (Soluciones)
    4. Generación de Examen de 'Termodinámica' (Basado en el PDF)
    """
    
    # Verificación de seguridad previa
    if not os.path.exists(os.path.join(ASSETS_DIR, FILE_EXAMEN)):
        pytest.fail(f"❌ No encuentro el archivo {FILE_EXAMEN} en {ASSETS_DIR}. ¿Lo has copiado?")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client: # Timeout aumentado a 60s por los archivos
        
        # ---------------------------------------------------------
        # 1. AUTH (MODIFICADO PARA OBTENER EL ID)
        # ---------------------------------------------------------
        print(f"\n🚀 [1/5] Autenticando usuario: {EMAIL}...")
        
        # 1.1 Registramos y CAPTURAMOS la respuesta para saber el ID
        resp_reg = await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "Test User"})
        assert resp_reg.status_code == 201, f"Fallo en registro: {resp_reg.text}"
        
        # Extraemos el ID del usuario recién creado
        USER_ID = resp_reg.json().get("id")
        print(f"   👤 Usuario creado con ID: {USER_ID}")

        # 1.2 Login normal
        resp_login = await client.post("/auth/token", data={"username": EMAIL, "password": PASSWORD})
        token = resp_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("   ✅ Autenticado.")

        # ---------------------------------------------------------
        # 2. SUBIDA DE ARCHIVOS (REALES)
        # ---------------------------------------------------------
        print("📂 [2/5] Subiendo contextos reales...")
        
        COURSE_ID = str(uuid4()) 

        async def upload_file(filename):
            file_path = os.path.join(ASSETS_DIR, filename)
            with open(file_path, "rb") as f:
                file_content = f.read()
            
            files = {'file': (filename, file_content, 'application/pdf')}
            data_payload = {"course_id": COURSE_ID}

            resp = await client.post(
                "/api/v1/documents/upload", 
                headers=headers, 
                files=files, 
                data=data_payload 
            )
            
            if resp.status_code not in [200, 201]:
                pytest.fail(f"❌ Fallo subiendo {filename}: {resp.text}")
                
            print(f"   ✅ Subido: {filename} (Asignado al CourseID: {COURSE_ID})")

        # Subimos los archivos
        await upload_file(FILE_EXAMEN)
        

        # ---------------------------------------------------------
        # 3. GENERAR EXAMEN (MODIFICADO CON STUDENT_ID)
        # ---------------------------------------------------------
        print("🧠 [3/5] Solicitando examen de Termodinámica...")
        
        exam_payload = {
            "student_id": USER_ID,   # <--- ¡NUEVO! Añadimos el ID que capturamos arriba
            "course_id": COURSE_ID,  
            "topic": "Ciclos Termodinámicos y Refrigeración", 
            "difficulty": "hard",
            "num_questions": 3
        }
        
        resp_gen = await client.post("/api/v1/learning/exams/generate", json=exam_payload, headers=headers)
        
        # Aceptamos 200 (OK), 201 (Created) o 202 (Accepted/Encolado)
        assert resp_gen.status_code in [200, 201, 202], f"❌ Error generando examen: {resp_gen.text}"
        
        # Intentamos obtener el ID de dos formas posibles (task_id o exam_id)
        response_json = resp_gen.json()
        task_id = response_json.get("exam_id") or response_json.get("task_id")
        
        print(f"   ✅ Tarea iniciada: {task_id}")

        # ---------------------------------------------------------
        # 4. POLLING (Esperando a la IA)
        # ---------------------------------------------------------
        print("⏳ [4/5] Procesando con IA (esto puede tardar)...")
        status = "queued"
        for _ in range(90): # Aumentamos intentos a 30 (60 segundos) por si la IA tarda
            await asyncio.sleep(2)
            resp_status = await client.get(f"/api/v1/learning/exams/status/{task_id}", headers=headers)
            status = resp_status.json().get("status")
            if status in ["completed", "failed"]:
                break
        
        if status == "failed":
            error_msg = resp_status.json().get("error_message")
            pytest.fail(f"❌ La generación falló en el Worker: {error_msg}")
            
        assert status == "completed", f"❌ Timeout o estado inesperado: {status}"
        print("   ✅ Examen generado exitosamente.")

        # ---------------------------------------------------------
        # 5. INSPECCIONAR EL EXAMEN GENERADO
        # ---------------------------------------------------------
        print("🧐 [5/6] Inspeccionando las preguntas generadas...")
        
        exam_content = resp_status.json().get("content")
        
        assert exam_content is not None, "❌ Error: El campo 'content' está vacío en la DB."
        questions = exam_content.get("questions", [])
        assert len(questions) > 0, "❌ Error: La IA no generó ninguna pregunta."
        
        print(f"   ✅ Se encontraron {len(questions)} preguntas generadas por la IA.")

        # ---------------------------------------------------------
        # 6. SIMULAR RESOLUCIÓN (SUBMIT JSON)
        # ---------------------------------------------------------
        print("📝 [6/6] Enviando respuestas del alumno (Simulación JSON)...")
        
        answers_list = []
        for q in questions:
            answer_payload = {
                "question_id": q.get("id"), 
                "answer_text": "Respuesta simulada E2E" 
            }
            if "options" in q:
                answer_payload["selected_option"] = "a"
            
            answers_list.append(answer_payload)

        submit_payload = {
            "exam_id": task_id,
            "answers": answers_list
        }

        resp_submit = await client.post("/api/v1/learning/exams/submit", json=submit_payload, headers=headers)
        
        if resp_submit.status_code != 200:
            pytest.fail(f"❌ Falló el envío de respuestas: {resp_submit.text}")
            
        submission_result = resp_submit.json()
        print("   ✅ Respuestas enviadas correctamente.")
        print(f"   📊 Feedback del sistema: {submission_result}")

        print("\n🎉 ¡ENHORABUENA! El Ciclo de Vida del Examen (Generación -> Resolución) funciona perfectamente.")